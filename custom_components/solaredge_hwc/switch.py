"""Switch platform: manual heating on/off."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SolarEdgeHWCConfigEntry
from .const import (
    CONF_SWITCH_OFF_MODE,
    DEFAULT_SWITCH_OFF_MODE,
    OPERATION_AUTO,
    OPERATION_OFF,
    OPERATION_ON,
    SWITCH_OFF_OFF,
)
from .entity import SolarEdgeHWCEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolarEdgeHWCConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the manual heating switch."""
    async_add_entities(
        [
            HWCManualHeatingSwitch(
                entry.runtime_data.coordinator,
                entry.options.get(CONF_SWITCH_OFF_MODE, DEFAULT_SWITCH_OFF_MODE),
            )
        ]
    )


class HWCManualHeatingSwitch(SolarEdgeHWCEntity, SwitchEntity):
    """
    On while the controller heats in manual mode.

    Turning it on heats with the "Manual heating level" until it is turned
    off again. Turning it off returns the controller to automatic mode, or
    keeps it manually off, depending on the integration options.
    """

    def __init__(self, coordinator, off_mode: str) -> None:
        """Initialize the switch."""
        super().__init__(
            coordinator,
            SwitchEntityDescription(key="manual_heating", translation_key="manual_heating"),
        )
        self._off_operation = OPERATION_OFF if off_mode == SWITCH_OFF_OFF else OPERATION_AUTO

    @property
    def is_on(self) -> bool | None:
        """Return True while heating manually."""
        if self.hwc.operation_mode is None:
            return None
        return self.hwc.operation_mode == OPERATION_ON

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start heating manually."""
        await self.coordinator.async_set_operation_mode(OPERATION_ON)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop heating manually."""
        await self.coordinator.async_set_operation_mode(self._off_operation)
