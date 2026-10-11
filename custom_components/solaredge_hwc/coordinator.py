"""Data update coordinator for SolarEdge Hot Water Controller."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    SolarEdgeAuthError,
    SolarEdgeError,
    SolarEdgeHWCClient,
)
from .const import (
    API_MODE_AUTO,
    API_MODE_MANUAL,
    API_MODE_SCHEDULE,
    CONF_DEVICE_ID,
    CONF_SCAN_INTERVAL,
    DEFAULT_BOOST_DURATION_MIN,
    DEFAULT_MANUAL_LEVEL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    HEATING_POWER_THRESHOLD_W,
    INFO_REFRESH_INTERVAL,
    ONLINE_STATUSES,
    OPERATION_AUTO,
    OPERATION_OFF,
    OPERATION_ON,
    OPERATION_SCHEDULE,
    POST_COMMAND_REFRESH_DELAY,
)

if TYPE_CHECKING:
    from . import SolarEdgeHWCConfigEntry

_LOGGER = logging.getLogger(__name__)

_WEEKDAYS = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")

# Field names under which an energy counter might show up in "measurements"
_ENERGY_FIELDS = ("totalActiveEnergyMeter", "totalEnergy", "energyTotal", "consumedEnergy")


@dataclass
class HWCData:
    """Snapshot of one hot water controller as reported by the portal."""

    state: dict[str, Any]
    info: dict[str, Any] = field(default_factory=dict)

    # -- state ------------------------------------------------------------

    @property
    def measurements(self) -> dict[str, Any]:
        """Return the measurements block."""
        return self.state.get("measurements") or {}

    @property
    def activation_mode(self) -> str | None:
        """Return the raw activation mode (AUTO, MANUAL, SCHEDULE …)."""
        return self.state.get("activationMode")

    @property
    def level(self) -> int | None:
        """Return the current heating level in percent."""
        return _to_int(self.state.get("percentageLevel"))

    @property
    def measured_power(self) -> float | None:
        """Return the measured power in W, None if the device sent none."""
        return _to_float(self.measurements.get("activePowerMeter"))

    @property
    def temperature(self) -> float | None:
        """Return the measured water temperature in °C."""
        return _to_float(self.measurements.get("measuredTemperature"))

    @property
    def energy_counter(self) -> float | None:
        """Return an energy counter in Wh if the API happens to send one."""
        for key in _ENERGY_FIELDS:
            if (value := _to_float(self.measurements.get(key))) is not None:
                return value
        return None

    @property
    def device_status(self) -> str | None:
        """Return the raw device status."""
        return self.state.get("deviceStatus")

    @property
    def online(self) -> bool:
        """Return True when the controller is connected to the cloud."""
        statuses = {
            status
            for status in (
                self.state.get("deviceStatus"),
                self.state.get("portiaCommunicationStatus"),
            )
            if status
        }
        return bool(statuses) and statuses <= ONLINE_STATUSES

    @property
    def operation_mode(self) -> str | None:
        """Map the API state onto auto / on / off / schedule."""
        mode = self.activation_mode
        if mode == API_MODE_AUTO:
            return OPERATION_AUTO
        if mode == API_MODE_SCHEDULE:
            return OPERATION_SCHEDULE
        if mode == API_MODE_MANUAL:
            return OPERATION_ON if (self.level or 0) > 0 else OPERATION_OFF
        return None

    # -- info -------------------------------------------------------------

    @property
    def device_info(self) -> dict[str, Any]:
        """Return the deviceInfo block of the info response."""
        return self.info.get("deviceInfo") or {}

    @property
    def configuration(self) -> dict[str, Any]:
        """Return the deviceConfigurations block of the info response."""
        return self.info.get("deviceConfigurations") or {}

    @property
    def rated_power(self) -> float | None:
        """Return the rated power of the heating element in W."""
        return _to_float(self.configuration.get("ratedPower"))

    @property
    def excess_pv_enabled(self) -> bool | None:
        """Return whether heating with excess solar power is enabled."""
        value = self.configuration.get("excessPVEnabled")
        if value is None:
            return None
        return str(value).upper() in ("ON", "TRUE", "ENABLED")

    @property
    def schedules(self) -> list[dict[str, Any]]:
        """Return all configured schedules."""
        schedules = (self.info.get("schedules") or {}).get("allSchedules") or []
        return [item for item in schedules if isinstance(item, dict)]

    # -- derived ----------------------------------------------------------

    @property
    def power(self) -> float | None:
        """
        Return the power drawn by the heating element in W.

        The API leaves ``activePowerMeter`` out instead of sending 0 W, and
        controllers without a meter never send it. Without a reading the
        power is 0 W at level 0, otherwise estimated from the rated power.
        """
        if (measured := self.measured_power) is not None:
            return measured
        level = self.level
        if not level:
            return 0.0
        if (rated := self.rated_power) is not None:
            return rated * level / 100
        return None

    @property
    def power_is_estimated(self) -> bool:
        """Return True when ``power`` is an estimate and not a measurement."""
        return self.measured_power is None and bool(self.level)

    @property
    def heating(self) -> bool:
        """Return True while the heating element is switched on."""
        if (measured := self.measured_power) is not None:
            return measured > HEATING_POWER_THRESHOLD_W
        return (self.level or 0) > 0

    def next_schedule_start(self, now: datetime) -> datetime | None:
        """Return the next start of an enabled time schedule after ``now``."""
        upcoming: list[datetime] = []
        for schedule in self.schedules:
            start = _to_int(schedule.get("startTime"))
            if not schedule.get("enable") or start is None:
                continue
            days = {
                _WEEKDAYS.index(day)
                for day in schedule.get("scheduledDays") or []
                if day in _WEEKDAYS
            }
            for offset in range(8):
                day = (now + timedelta(days=offset)).date()
                if day.weekday() not in days:
                    continue
                candidate = dt_util.start_of_local_day(day) + timedelta(minutes=start)
                if candidate > now:
                    upcoming.append(candidate)
                    break
        return min(upcoming, default=None)


def _to_float(value: Any) -> float | None:
    """Convert to float, None for missing or malformed values."""
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    """Convert to int, None for missing or malformed values."""
    number = _to_float(value)
    return round(number) if number is not None else None


class SolarEdgeHWCCoordinator(DataUpdateCoordinator[HWCData]):
    """Poll one hot water controller and send commands to it."""

    config_entry: SolarEdgeHWCConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: SolarEdgeHWCConfigEntry,
        client: SolarEdgeHWCClient,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.data[CONF_DEVICE_ID]}",
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.client = client
        self.device_id: str = entry.data[CONF_DEVICE_ID]
        self.site_id: str = client.site_id
        self._info: dict[str, Any] = {}
        self._info_fetched: datetime | None = None
        self._refresh_unsub: CALLBACK_TYPE | None = None

        # Settings of the number entities, used by the switch and the button
        self.manual_level: int = DEFAULT_MANUAL_LEVEL
        self.boost_duration: int = DEFAULT_BOOST_DURATION_MIN
        # End of a manual run with a duration started from Home Assistant
        self.manual_until: datetime | None = None

    async def _async_update_data(self) -> HWCData:
        """Fetch the state, and the static info every few minutes."""
        try:
            state = await self.client.async_get_state(self.device_id)
        except SolarEdgeAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except SolarEdgeError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err

        now = dt_util.utcnow()
        if self._info_fetched is None or now - self._info_fetched >= INFO_REFRESH_INTERVAL:
            try:
                self._info = await self.client.async_get_info(self.device_id)
            except SolarEdgeAuthError as err:
                raise ConfigEntryAuthFailed(
                    translation_domain=DOMAIN, translation_key="auth_failed"
                ) from err
            except SolarEdgeError as err:
                # The info only adds detail; keep the last copy and retry later
                _LOGGER.debug("Could not fetch device info: %s", err)
            self._info_fetched = now

        data = HWCData(state=state, info=self._info)
        if data.activation_mode != API_MODE_MANUAL or (
            self.manual_until is not None and self.manual_until <= now
        ):
            self.manual_until = None
        return data

    async def async_set_operation_mode(
        self,
        operation: str,
        level: int | None = None,
        duration: int | None = None,
    ) -> None:
        """
        Switch the controller to auto / on / off / schedule.

        ``level`` (percent) and ``duration`` (minutes) only apply to ``on``.
        """
        if operation == OPERATION_AUTO:
            await self.async_set_activation_state(API_MODE_AUTO)
        elif operation == OPERATION_SCHEDULE:
            await self.async_set_activation_state(API_MODE_SCHEDULE)
        elif operation == OPERATION_OFF:
            await self.async_set_activation_state(API_MODE_MANUAL, level=0)
        elif operation == OPERATION_ON:
            await self.async_set_activation_state(
                API_MODE_MANUAL,
                level=self.manual_level if level is None else level,
                duration=duration * 60 if duration else None,
            )
        else:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="invalid_mode",
                translation_placeholders={"mode": operation},
            )

    async def async_boost(
        self, duration: int | None = None, level: int | None = None
    ) -> None:
        """Heat for a limited time, then return to the previous mode."""
        minutes = self.boost_duration if duration is None else duration
        await self.async_set_operation_mode(
            OPERATION_ON,
            level=self.manual_level if level is None else level,
            duration=minutes or None,
        )

    async def async_set_activation_state(
        self,
        mode: str,
        level: int | None = None,
        duration: int | None = None,
    ) -> None:
        """Send a command, update the state optimistically and re-read it soon."""
        _LOGGER.debug(
            "Setting activation state of %s: mode=%s level=%s duration=%s",
            self.device_id,
            mode,
            level,
            duration,
        )
        try:
            await self.client.async_set_activation_state(
                self.device_id, mode, level=level, duration=duration
            )
        except SolarEdgeAuthError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except SolarEdgeError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err

        self.manual_until = (
            dt_util.utcnow() + timedelta(seconds=duration)
            if mode == API_MODE_MANUAL and duration
            else None
        )

        if self.data is not None:
            state = {**self.data.state, "activationMode": mode}
            if level is not None:
                state["percentageLevel"] = level
            self.async_set_updated_data(HWCData(state=state, info=self.data.info))

        self._schedule_refresh_after_command()

    @callback
    def _schedule_refresh_after_command(self) -> None:
        """Re-read the state shortly after a command took effect."""
        if self._refresh_unsub is not None:
            self._refresh_unsub()

        @callback
        def _refresh(_now: datetime) -> None:
            self._refresh_unsub = None
            self.hass.async_create_task(self.async_request_refresh())

        self._refresh_unsub = async_call_later(
            self.hass, POST_COMMAND_REFRESH_DELAY, _refresh
        )

    async def async_shutdown(self) -> None:
        """Cancel a pending refresh when the entry is unloaded."""
        if self._refresh_unsub is not None:
            self._refresh_unsub()
            self._refresh_unsub = None
        await super().async_shutdown()
