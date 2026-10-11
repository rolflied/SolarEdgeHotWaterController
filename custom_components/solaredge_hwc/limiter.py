"""
Upper temperature limit for the hot water controller.

SolarEdge offers no target temperature, so Home Assistant enforces one:
while the controller heats on its own (automatic or schedule mode) and the
water reaches the target, it is switched off manually. Once the water has
cooled down by the hysteresis, the previous mode is restored. Manual heating
and boosts are left alone, they are explicit requests.

The water temperature comes from the controller, or, if it reports none,
from a temperature sensor chosen in the options.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, UnitOfTemperature
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import (
    API_MODE_AUTO,
    API_MODE_MANUAL,
    API_MODE_SCHEDULE,
    CONF_HYSTERESIS,
    CONF_TEMPERATURE_SENSOR,
    DEFAULT_HYSTERESIS,
    DEFAULT_TARGET_TEMPERATURE,
    DOMAIN,
)

if TYPE_CHECKING:
    from . import SolarEdgeHWCConfigEntry
    from .coordinator import SolarEdgeHWCCoordinator

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
SOURCE_DEVICE = "device"
SOURCE_SENSOR = "sensor"

# Modes in which the controller decides on its own when to heat
_LIMITED_MODES = (API_MODE_AUTO, API_MODE_SCHEDULE)
# Commands sent by the limiter itself are at least this far apart
_MIN_COMMAND_INTERVAL = timedelta(seconds=60)


def storage_key(entry_id: str) -> str:
    """Return the storage key of an entry's limiter state."""
    return f"{DOMAIN}.{entry_id}.limiter"


class TemperatureLimiter:
    """Keep the water below the target temperature."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: SolarEdgeHWCConfigEntry,
        coordinator: SolarEdgeHWCCoordinator,
    ) -> None:
        """Initialize the limiter."""
        self.hass = hass
        self._entry = entry
        self._coordinator = coordinator
        self.sensor_entity_id: str | None = entry.options.get(CONF_TEMPERATURE_SENSOR)
        self.hysteresis: float = entry.options.get(CONF_HYSTERESIS, DEFAULT_HYSTERESIS)
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, storage_key(entry.entry_id)
        )
        self._lock = asyncio.Lock()
        self._last_command: datetime | None = None
        self._issue_id = f"temperature_unavailable_{entry.entry_id}"

        self.enabled = False
        self.target: float = DEFAULT_TARGET_TEMPERATURE
        # Mode the controller was in before the limiter switched it off
        self.held_from: str | None = None

    # -- state ----------------------------------------------------------------

    @property
    def temperature(self) -> float | None:
        """Return the water temperature in °C, from the device or the sensor."""
        temperature, _ = self._temperature_and_source()
        return temperature

    @property
    def source(self) -> str | None:
        """Return where the temperature comes from."""
        _, source = self._temperature_and_source()
        return source

    @property
    def has_temperature_source(self) -> bool:
        """Return True if a temperature can be expected at all."""
        data = self._coordinator.data
        return self.sensor_entity_id is not None or (
            data is not None and data.temperature is not None
        )

    @property
    def active(self) -> bool:
        """Return True while the limiter holds the heating element off."""
        return self.held_from is not None

    def _temperature_and_source(self) -> tuple[float | None, str | None]:
        data = self._coordinator.data
        if data is not None and data.temperature is not None:
            return data.temperature, SOURCE_DEVICE
        if (value := self._sensor_temperature()) is not None:
            return value, SOURCE_SENSOR
        return None, None

    def _sensor_temperature(self) -> float | None:
        """Read the fallback sensor and convert it to °C."""
        if self.sensor_entity_id is None:
            return None
        state = self.hass.states.get(self.sensor_entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        try:
            value = float(state.state)
        except ValueError:
            return None
        unit = state.attributes.get("unit_of_measurement", UnitOfTemperature.CELSIUS)
        try:
            return TemperatureConverter.convert(value, unit, UnitOfTemperature.CELSIUS)
        except HomeAssistantError:
            _LOGGER.warning(
                "Temperature sensor %s has unsupported unit %s", self.sensor_entity_id, unit
            )
            return None

    # -- lifecycle ------------------------------------------------------------

    async def async_start(self) -> None:
        """Restore the stored state and start watching."""
        if stored := await self._store.async_load():
            self.enabled = bool(stored.get("enabled", False))
            self.target = float(stored.get("target", DEFAULT_TARGET_TEMPERATURE))
            self.held_from = stored.get("held_from")

        self._entry.async_on_unload(self._coordinator.async_add_listener(self._schedule))
        if self.sensor_entity_id is not None:
            self._entry.async_on_unload(
                async_track_state_change_event(
                    self.hass, [self.sensor_entity_id], self._handle_sensor_change
                )
            )
        self._schedule()

    @callback
    def _handle_sensor_change(self, event: Event[EventStateChangedData]) -> None:
        """Show the new value and re-check the limit."""
        self._coordinator.async_update_listeners()

    @callback
    def _schedule(self) -> None:
        """Re-check the limit in the background."""
        self._entry.async_create_background_task(
            self.hass, self.async_evaluate(), f"{DOMAIN} temperature limit"
        )

    # -- user changes ---------------------------------------------------------

    async def async_set_target(self, target: float) -> None:
        """Set a new target and enable the limit."""
        self.target = target
        self.enabled = True
        self._last_command = None
        await self._async_changed()

    async def async_set_enabled(self, enabled: bool) -> None:
        """Turn the limit on or off."""
        self.enabled = enabled
        self._last_command = None
        await self._async_changed()

    async def _async_changed(self) -> None:
        await self._async_save()
        self._coordinator.async_update_listeners()
        await self.async_evaluate()

    async def _async_save(self) -> None:
        # Written at once: a reload right after a change must see it
        await self._store.async_save(
            {"enabled": self.enabled, "target": self.target, "held_from": self.held_from}
        )

    # -- control loop ---------------------------------------------------------

    async def async_evaluate(self) -> None:
        """Switch the heating element off or back on as needed."""
        async with self._lock:
            try:
                await self._async_evaluate()
            except HomeAssistantError as err:
                _LOGGER.warning("Temperature limit could not change the controller: %s", err)

    async def _async_evaluate(self) -> None:
        data = self._coordinator.data
        if data is None or not self._coordinator.last_update_success:
            # Without a current state (or a reachable cloud) nothing can be decided
            return
        temperature = self.temperature
        self._update_issue(temperature)

        if self.held_from is not None:
            if not self._still_held(data.activation_mode, data.level):
                # Someone else changed the mode; their choice wins
                _LOGGER.debug("Mode changed while limited; releasing the limit")
                await self._async_set_held(None)
            elif (
                not self.enabled
                or temperature is None
                or temperature <= self.target - self.hysteresis
            ):
                await self._async_release()
            return

        if (
            self.enabled
            and temperature is not None
            and temperature >= self.target
            and data.activation_mode in _LIMITED_MODES
            and self._may_send()
        ):
            _LOGGER.debug(
                "Water at %.1f °C reached the limit of %.1f °C; switching off",
                temperature,
                self.target,
            )
            previous = data.activation_mode
            self._last_command = dt_util.utcnow()
            await self._coordinator.async_set_activation_state(API_MODE_MANUAL, level=0)
            await self._async_set_held(previous)

    def _still_held(self, mode: str | None, level: int | None) -> bool:
        """Return True if the controller is still switched off by the limiter."""
        if mode == API_MODE_MANUAL and not level:
            return True
        # Right after a command the cloud may still report the old mode
        return (
            mode == self.held_from
            and self._last_command is not None
            and dt_util.utcnow() - self._last_command < timedelta(minutes=2)
        )

    async def _async_release(self) -> None:
        """Restore the mode the controller had before."""
        if not self._may_send():
            return
        previous = self.held_from or API_MODE_AUTO
        _LOGGER.debug("Releasing the temperature limit; back to %s", previous)
        self._last_command = dt_util.utcnow()
        await self._coordinator.async_set_activation_state(previous)
        await self._async_set_held(None)

    def _may_send(self) -> bool:
        return self._last_command is None or (
            dt_util.utcnow() - self._last_command >= _MIN_COMMAND_INTERVAL
        )

    async def _async_set_held(self, held_from: str | None) -> None:
        if held_from != self.held_from:
            self.held_from = held_from
            await self._async_save()
            self._coordinator.async_update_listeners()

    @callback
    def _update_issue(self, temperature: float | None) -> None:
        """Show a repair issue while the limit is on but no temperature is known."""
        if self.enabled and temperature is None:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                self._issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="temperature_unavailable",
                translation_placeholders={
                    "entry": self._entry.title,
                    "sensor": self.sensor_entity_id or "-",
                },
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, self._issue_id)
