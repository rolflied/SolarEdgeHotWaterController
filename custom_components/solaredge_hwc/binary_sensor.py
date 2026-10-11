"""Binary sensor platform for SolarEdge Hot Water Controller."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SolarEdgeHWCConfigEntry
from .coordinator import HWCData
from .entity import SolarEdgeHWCEntity
from .limiter import TemperatureLimiter

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class HWCBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a SolarEdge HWC binary sensor."""

    value_fn: Callable[[HWCData], bool | None]
    attrs_fn: Callable[[HWCData], dict[str, Any]] | None = None


BINARY_SENSORS: tuple[HWCBinarySensorDescription, ...] = (
    HWCBinarySensorDescription(
        key="heating_active",
        translation_key="heating_active",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda d: d.heating,
    ),
    HWCBinarySensorDescription(
        key="device_online",
        translation_key="device_online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.online,
        attrs_fn=lambda d: {
            "device_status": d.device_status,
            "communication_status": d.state.get("portiaCommunicationStatus"),
        },
    ),
    HWCBinarySensorDescription(
        key="excess_pv",
        translation_key="excess_pv",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.excess_pv_enabled,
    ),
    HWCBinarySensorDescription(
        key="schedule_enabled",
        translation_key="schedule_enabled",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: any(item.get("enable") for item in d.schedules),
        attrs_fn=lambda d: {"schedule_count": len(d.schedules)},
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolarEdgeHWCConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up SolarEdge HWC binary sensors."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            *(HWCBinarySensor(coordinator, description) for description in BINARY_SENSORS),
            HWCTemperatureLimitActive(coordinator, entry.runtime_data.limiter),
        ]
    )


class HWCBinarySensor(SolarEdgeHWCEntity, BinarySensorEntity):
    """A binary sensor whose value comes from the coordinator data."""

    entity_description: HWCBinarySensorDescription

    @property
    def is_on(self) -> bool | None:
        """Return the state."""
        return self.entity_description.value_fn(self.hwc)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.hwc)


class HWCTemperatureLimitActive(SolarEdgeHWCEntity, BinarySensorEntity):
    """On while the temperature limit keeps the heating element off."""

    def __init__(self, coordinator, limiter: TemperatureLimiter) -> None:
        """Initialize the binary sensor."""
        super().__init__(
            coordinator,
            BinarySensorEntityDescription(
                key="temperature_limit_active", translation_key="temperature_limit_active"
            ),
        )
        self._limiter = limiter

    @property
    def is_on(self) -> bool:
        """Return True while the limit holds the controller off."""
        return self._limiter.active
