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
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SolarEdgeHWCConfigEntry
from .coordinator import HWCData
from .entity import SolarEdgeHWCEntity

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
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SolarEdge HWC binary sensors."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        HWCBinarySensor(coordinator, description) for description in BINARY_SENSORS
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
