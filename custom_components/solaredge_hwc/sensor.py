"""Sensor platform for SolarEdge Hot Water Controller."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    DOMAIN as SENSOR_DOMAIN,
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    MATCH_ALL,
    EntityCategory,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfRatio,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import SolarEdgeHWCConfigEntry
from .const import (
    DOMAIN,
    EVCC_STATUS_CHARGING,
    EVCC_STATUS_CONNECTED,
    EVCC_STATUS_KEY,
    MAX_ENERGY_INTEGRATION_GAP,
)
from .coordinator import HWCData, SolarEdgeHWCCoordinator
from .entity import SolarEdgeHWCEntity
from .evcc import EvccModeFollower

PARALLEL_UPDATES = 0

ACTIVATION_MODES = ["auto", "manual", "schedule", "smart_energy", "off"]
DEVICE_STATUSES = [
    "active",
    "online",
    "offline",
    "connected",
    "disconnected",
    "error",
    "communication_error",
]


def _enum(value: str | None, options: list[str]) -> str | None:
    """Turn an API value into an enum option, None if it is not a known one."""
    if not value:
        return None
    option = str(value).lower()
    return option if option in options else None


def _lower(value: Any) -> str | None:
    """Lower-case a free text API value."""
    return str(value).lower() if value else None


@dataclass(frozen=True, kw_only=True)
class HWCSensorDescription(SensorEntityDescription):
    """Describes a SolarEdge HWC sensor."""

    value_fn: Callable[[HWCData], Any]
    attrs_fn: Callable[[HWCData], dict[str, Any]] | None = None
    # Attributes that only help when looking at the entity, not in history
    record_attrs: bool = True
    exists_fn: Callable[[HWCData], bool] = lambda _: True


SENSORS: tuple[HWCSensorDescription, ...] = (
    HWCSensorDescription(
        key="power",
        translation_key="power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: d.power,
        record_attrs=False,
        attrs_fn=lambda d: {
            "estimated": d.power_is_estimated,
            **{k: v for k, v in d.measurements.items() if k != "activePowerMeter"},
        },
    ),
    HWCSensorDescription(
        key="heating_level",
        translation_key="heating_level",
        native_unit_of_measurement=UnitOfRatio.PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: d.level,
    ),
    HWCSensorDescription(
        key="water_temperature",
        translation_key="water_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.temperature,
        # Only controllers with a temperature probe report it
        exists_fn=lambda d: d.temperature is not None,
    ),
    HWCSensorDescription(
        key="activation_mode",
        translation_key="activation_mode",
        device_class=SensorDeviceClass.ENUM,
        options=ACTIVATION_MODES,
        value_fn=lambda d: _enum(d.activation_mode, ACTIVATION_MODES),
        attrs_fn=lambda d: {"raw_mode": d.activation_mode},
    ),
    HWCSensorDescription(
        key="auto_off_reason",
        translation_key="auto_off_reason",
        value_fn=lambda d: _lower(d.state.get("autoOffReason")),
    ),
    HWCSensorDescription(
        key="schedule_type",
        translation_key="schedule_type",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _lower(d.state.get("scheduleType")),
    ),
    HWCSensorDescription(
        key="device_status",
        translation_key="device_status",
        device_class=SensorDeviceClass.ENUM,
        options=DEVICE_STATUSES,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _enum(d.device_status, DEVICE_STATUSES),
        record_attrs=False,
        attrs_fn=lambda d: {
            "raw_status": d.device_status,
            # Every field without a dedicated entity, for templates
            **{
                k: v
                for k, v in d.state.items()
                if k
                not in (
                    "measurements",
                    "percentageLevel",
                    "activationMode",
                    "deviceStatus",
                    "autoOffReason",
                    "scheduleType",
                )
            },
        },
    ),
    HWCSensorDescription(
        key="rated_power",
        translation_key="rated_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        value_fn=lambda d: d.rated_power,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolarEdgeHWCConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up SolarEdge HWC sensors from a config entry."""
    coordinator = entry.runtime_data.coordinator
    registry = er.async_get(hass)

    def _wanted(description: HWCSensorDescription) -> bool:
        # Keep an entity created earlier even if the value is missing right now
        unique_id = f"{entry.entry_id}_{description.key}"
        return description.exists_fn(coordinator.data) or (
            registry.async_get_entity_id(SENSOR_DOMAIN, DOMAIN, unique_id) is not None
        )

    entities: list[SensorEntity] = [
        (HWCSensor if description.record_attrs else HWCSensorUnrecordedAttrs)(
            coordinator, description
        )
        for description in SENSORS
        if _wanted(description)
    ]
    entities.append(HWCEnergySensor(coordinator))
    entities.append(HWCNextScheduleSensor(coordinator))
    entities.append(HWCManualUntilSensor(coordinator))
    if (evcc := entry.runtime_data.evcc) is not None:
        entities.append(HWCEvccStatusSensor(coordinator, evcc))
    async_add_entities(entities)


class HWCSensor(SolarEdgeHWCEntity, SensorEntity):
    """A sensor whose value comes straight from the coordinator data."""

    entity_description: HWCSensorDescription

    @property
    def native_value(self) -> Any:
        """Return the value."""
        return self.entity_description.value_fn(self.hwc)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.hwc)


class HWCSensorUnrecordedAttrs(HWCSensor):
    """A sensor whose attributes are not written to the recorder."""

    _unrecorded_attributes = frozenset({MATCH_ALL})


class HWCEnergySensor(SolarEdgeHWCEntity, RestoreSensor):
    """
    Energy used by the heating element, for the Energy dashboard.

    The portal reports no energy counter for the controller, so the power is
    integrated over time (left Riemann sum between two polls). If a counter
    turns up in the measurements it is used instead. Gaps longer than
    MAX_ENERGY_INTEGRATION_GAP (Home Assistant stopped, portal unreachable)
    are skipped rather than guessed.
    """

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.WATT_HOUR
    _attr_suggested_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: SolarEdgeHWCCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            SensorEntityDescription(key="total_energy", translation_key="total_energy"),
        )
        self._energy: float = 0.0
        self._last_power: float | None = None
        self._last_time: datetime | None = None

    async def async_added_to_hass(self) -> None:
        """Restore the counter."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            try:
                self._energy = float(last.native_value or 0)
            except TypeError, ValueError:
                self._energy = 0.0
        self._remember(self.coordinator.data)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Add the energy since the previous poll."""
        if self.coordinator.last_update_success:
            now = dt_util.utcnow()
            if (
                self._last_power is not None
                and self._last_time is not None
                and now - self._last_time <= MAX_ENERGY_INTEGRATION_GAP
            ):
                hours = (now - self._last_time).total_seconds() / 3600
                self._energy += max(self._last_power, 0.0) * hours
            self._remember(self.coordinator.data)
        else:
            self._last_power = None
        super()._handle_coordinator_update()

    def _remember(self, data: HWCData | None) -> None:
        """Store the current power as start of the next interval."""
        self._last_power = data.power if data else None
        self._last_time = dt_util.utcnow()

    @property
    def native_value(self) -> float:
        """Return the energy in Wh."""
        if (counter := self.hwc.energy_counter) is not None:
            return round(counter, 1)
        return round(self._energy, 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Tell where the value comes from."""
        return {"source": "api" if self.hwc.energy_counter is not None else "integrated"}


class HWCNextScheduleSensor(SolarEdgeHWCEntity, SensorEntity):
    """Start of the next enabled time schedule."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    # The schedule list changes rarely and would bloat the history
    _unrecorded_attributes = frozenset({MATCH_ALL})

    def __init__(self, coordinator: SolarEdgeHWCCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            SensorEntityDescription(key="next_schedule", translation_key="next_schedule"),
        )

    @property
    def native_value(self) -> datetime | None:
        """Return the next start."""
        return self.hwc.next_schedule_start(dt_util.now())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the schedules in a readable form."""
        schedules = []
        for item in self.hwc.schedules:
            entry: dict[str, Any] = {
                "enabled": bool(item.get("enable")),
                "days": [str(day).lower() for day in item.get("scheduledDays") or []],
                "smart_saver": bool(item.get("smartSaver")),
            }
            for key, name in (("startTime", "start"), ("endTime", "end")):
                if isinstance(item.get(key), (int, float)):
                    minutes = int(item[key])
                    entry[name] = f"{minutes // 60:02d}:{minutes % 60:02d}"
            for key, name in (
                ("minOnDuration", "min_on_minutes"),
                ("maxOnDuration", "max_on_minutes"),
            ):
                if item.get(key) is not None:
                    entry[name] = item[key]
            schedules.append(entry)
        return {"schedules": schedules}


class HWCManualUntilSensor(SolarEdgeHWCEntity, SensorEntity):
    """End of a timed manual run (boost) started from Home Assistant."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: SolarEdgeHWCCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            SensorEntityDescription(key="boost_end", translation_key="boost_end"),
        )

    @property
    def native_value(self) -> datetime | None:
        """Return the end time."""
        return self.coordinator.manual_until


class HWCEvccStatusSensor(SolarEdgeHWCEntity, SensorEntity):
    """
    Charging status for the Home Assistant charger of evcc.

    evcc reads ``connected`` as status B and ``charging`` as status C. The
    attributes tell which evcc mode was applied to the controller.
    """

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [EVCC_STATUS_CONNECTED, EVCC_STATUS_CHARGING]
    _unrecorded_attributes = frozenset({"last_command", "mode_entity"})

    def __init__(self, coordinator: SolarEdgeHWCCoordinator, evcc: EvccModeFollower) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            SensorEntityDescription(key=EVCC_STATUS_KEY, translation_key=EVCC_STATUS_KEY),
        )
        self._evcc = evcc

    @property
    def native_value(self) -> str:
        """Return the status in the form evcc expects."""
        return EVCC_STATUS_CHARGING if self.hwc.heating else EVCC_STATUS_CONNECTED

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose what was done with the evcc mode."""
        return self._evcc.attributes
