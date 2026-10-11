"""Water heater platform: the controller as one entity for the thermostat card."""

from __future__ import annotations

from typing import Any

from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityDescription,
    WaterHeaterEntityFeature,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SolarEdgeHWCConfigEntry
from .const import OPERATION_AUTO, OPERATION_MODES, OPERATION_OFF
from .coordinator import SolarEdgeHWCCoordinator
from .entity import SolarEdgeHWCEntity

PARALLEL_UPDATES = 1

# Home Assistant 2026.11 renames the temperature properties with a native_
# prefix and warns about the old names; support both until 2026.10 is gone.
_NATIVE_TEMPERATURE = hasattr(WaterHeaterEntity, "native_current_temperature")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolarEdgeHWCConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the water heater entity."""
    async_add_entities([HWCWaterHeater(entry.runtime_data.coordinator)])


class HWCWaterHeater(SolarEdgeHWCEntity, WaterHeaterEntity):
    """
    Operating mode and water temperature in one entity.

    SolarEdge offers no target temperature, so none can be set. Turning the
    entity on returns the controller to automatic mode, turning it off keeps
    the heating element off until another mode is chosen.
    """

    _attr_name = None
    _attr_operation_list = OPERATION_MODES
    _attr_supported_features = (
        WaterHeaterEntityFeature.OPERATION_MODE | WaterHeaterEntityFeature.ON_OFF
    )

    def __init__(self, coordinator: SolarEdgeHWCCoordinator) -> None:
        """Initialize the entity."""
        super().__init__(
            coordinator,
            WaterHeaterEntityDescription(key="water_heater", translation_key="hwc"),
        )

    if _NATIVE_TEMPERATURE:
        _attr_native_temperature_unit = UnitOfTemperature.CELSIUS

        @property
        def native_current_temperature(self) -> float | None:
            """Return the water temperature."""
            return self.hwc.temperature

    else:
        _attr_temperature_unit = UnitOfTemperature.CELSIUS

        @property
        def current_temperature(self) -> float | None:
            """Return the water temperature."""
            return self.hwc.temperature

    @property
    def current_operation(self) -> str | None:
        """Return auto / on / off / schedule."""
        return self.hwc.operation_mode

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        """Change the operating mode."""
        await self.coordinator.async_set_operation_mode(operation_mode)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Return to automatic mode."""
        await self.coordinator.async_set_operation_mode(OPERATION_AUTO)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Keep the heating element off."""
        await self.coordinator.async_set_operation_mode(OPERATION_OFF)

    # -- entity actions of the integration ------------------------------------

    async def async_set_hwc_operation_mode(
        self, mode: str, level: int | None = None, duration: int | None = None
    ) -> None:
        """Action solaredge_hwc.set_operation_mode."""
        await self.coordinator.async_set_operation_mode(mode, level=level, duration=duration)

    async def async_boost(self, duration: int | None = None, level: int | None = None) -> None:
        """Action solaredge_hwc.boost."""
        await self.coordinator.async_boost(duration=duration, level=level)
