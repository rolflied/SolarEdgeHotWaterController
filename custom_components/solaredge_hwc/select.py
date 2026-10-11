"""Select platform: operating mode of the hot water controller."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SolarEdgeHWCConfigEntry
from .const import OPERATION_MODES
from .entity import SolarEdgeHWCEntity

# Commands go to the cloud one after another
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolarEdgeHWCConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the operating mode select."""
    async_add_entities([HWCOperationModeSelect(entry.runtime_data.coordinator)])


class HWCOperationModeSelect(SolarEdgeHWCEntity, SelectEntity):
    """
    Auto / On / Off / Schedule.

    "On" heats manually with the level of the "Manual heating level" number
    until another mode is chosen; "Off" keeps the element off the same way.
    """

    _attr_options = OPERATION_MODES

    def __init__(self, coordinator) -> None:
        """Initialize the select."""
        super().__init__(
            coordinator,
            SelectEntityDescription(key="operation_mode", translation_key="operation_mode"),
        )

    @property
    def current_option(self) -> str | None:
        """Return the current operating mode."""
        return self.hwc.operation_mode

    async def async_select_option(self, option: str) -> None:
        """Change the operating mode."""
        await self.coordinator.async_set_operation_mode(option)
