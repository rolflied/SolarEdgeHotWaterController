"""
Number platform: settings for manual heating and boost.

These values live in Home Assistant only; SolarEdge receives them with the
next command sent by the switch, the select or the boost button.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntityDescription,
    NumberMode,
    RestoreNumber,
)
from homeassistant.const import EntityCategory, UnitOfRatio, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SolarEdgeHWCConfigEntry
from .const import DEFAULT_BOOST_DURATION_MIN, DEFAULT_MANUAL_LEVEL, MAX_BOOST_DURATION_MIN
from .coordinator import SolarEdgeHWCCoordinator
from .entity import SolarEdgeHWCEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class HWCNumberDescription(NumberEntityDescription):
    """Describes a setting stored on the coordinator."""

    default: int
    set_fn: Callable[[SolarEdgeHWCCoordinator, int], None]


NUMBERS: tuple[HWCNumberDescription, ...] = (
    HWCNumberDescription(
        key="manual_level",
        translation_key="manual_level",
        entity_category=EntityCategory.CONFIG,
        native_min_value=1,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=UnitOfRatio.PERCENTAGE,
        mode=NumberMode.SLIDER,
        default=DEFAULT_MANUAL_LEVEL,
        set_fn=lambda c, v: setattr(c, "manual_level", v),
    ),
    HWCNumberDescription(
        key="boost_duration",
        translation_key="boost_duration",
        entity_category=EntityCategory.CONFIG,
        native_min_value=5,
        native_max_value=MAX_BOOST_DURATION_MIN,
        native_step=5,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        mode=NumberMode.BOX,
        default=DEFAULT_BOOST_DURATION_MIN,
        set_fn=lambda c, v: setattr(c, "boost_duration", v),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolarEdgeHWCConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the setting numbers."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(HWCSettingNumber(coordinator, description) for description in NUMBERS)


class HWCSettingNumber(SolarEdgeHWCEntity, RestoreNumber):
    """A setting that is kept across restarts."""

    entity_description: HWCNumberDescription

    def __init__(
        self, coordinator: SolarEdgeHWCCoordinator, description: HWCNumberDescription
    ) -> None:
        """Initialize the number."""
        super().__init__(coordinator, description)
        self._attr_native_value = description.default

    @property
    def available(self) -> bool:
        """A local setting can always be changed."""
        return True

    async def async_added_to_hass(self) -> None:
        """Restore the last value."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_number_data()) is not None and (
            last.native_value is not None
        ):
            value = min(max(last.native_value, self.native_min_value), self.native_max_value)
            self._attr_native_value = value
        self.entity_description.set_fn(self.coordinator, int(self._attr_native_value))

    async def async_set_native_value(self, value: float) -> None:
        """Store a new value."""
        self._attr_native_value = value
        self.entity_description.set_fn(self.coordinator, int(value))
        self.async_write_ha_state()
