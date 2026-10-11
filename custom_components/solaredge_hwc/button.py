"""Button platform: start a boost."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SolarEdgeHWCConfigEntry
from .entity import SolarEdgeHWCEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolarEdgeHWCConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the boost button."""
    async_add_entities([HWCBoostButton(entry.runtime_data.coordinator)])


class HWCBoostButton(SolarEdgeHWCEntity, ButtonEntity):
    """
    Heat with the manual level for the boost duration.

    Afterwards the controller returns to the mode it was in before.
    """

    def __init__(self, coordinator) -> None:
        """Initialize the button."""
        super().__init__(coordinator, ButtonEntityDescription(key="boost", translation_key="boost"))

    async def async_press(self) -> None:
        """Start the boost."""
        await self.coordinator.async_boost()
