"""Water heater platform: the controller as one entity for the thermostat card."""

from __future__ import annotations

from typing import Any

from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityDescription,
    WaterHeaterEntityFeature,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SolarEdgeHWCConfigEntry
from .const import (
    MAX_TARGET_TEMPERATURE,
    MIN_TARGET_TEMPERATURE,
    OPERATION_AUTO,
    OPERATION_MODES,
    OPERATION_OFF,
)
from .coordinator import SolarEdgeHWCCoordinator
from .entity import SolarEdgeHWCEntity
from .limiter import TemperatureLimiter

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
    async_add_entities([HWCWaterHeater(entry.runtime_data.coordinator, entry.runtime_data.limiter)])


class HWCWaterHeater(SolarEdgeHWCEntity, WaterHeaterEntity):
    """
    Operating mode, water temperature and temperature limit in one entity.

    The target temperature is enforced by Home Assistant (see limiter.py):
    setting it turns the temperature limit on. Turning the entity on returns
    the controller to automatic mode, turning it off keeps the heating
    element off until another mode is chosen.
    """

    _attr_name = None
    _attr_operation_list = OPERATION_MODES
    _attr_min_temp = MIN_TARGET_TEMPERATURE
    _attr_max_temp = MAX_TARGET_TEMPERATURE
    _attr_target_temperature_step = 1

    def __init__(self, coordinator: SolarEdgeHWCCoordinator, limiter: TemperatureLimiter) -> None:
        """Initialize the entity."""
        super().__init__(
            coordinator,
            WaterHeaterEntityDescription(key="water_heater", translation_key="hwc"),
        )
        self._limiter = limiter

    @property
    def supported_features(self) -> WaterHeaterEntityFeature:
        """Offer a target temperature only if a water temperature is available."""
        features = WaterHeaterEntityFeature.OPERATION_MODE | WaterHeaterEntityFeature.ON_OFF
        if self._limiter.has_temperature_source:
            features |= WaterHeaterEntityFeature.TARGET_TEMPERATURE
        return features

    if _NATIVE_TEMPERATURE:
        _attr_native_temperature_unit = UnitOfTemperature.CELSIUS

        @property
        def native_current_temperature(self) -> float | None:
            """Return the water temperature."""
            return self._limiter.temperature

        @property
        def native_target_temperature(self) -> float | None:
            """Return the temperature limit."""
            return self._target_temperature()

    else:
        _attr_temperature_unit = UnitOfTemperature.CELSIUS

        @property
        def current_temperature(self) -> float | None:
            """Return the water temperature."""
            return self._limiter.temperature

        @property
        def target_temperature(self) -> float | None:
            """Return the temperature limit."""
            return self._target_temperature()

    def _target_temperature(self) -> float | None:
        if not self._limiter.has_temperature_source:
            return None
        return self._limiter.target

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Tell whether the limit is on and where the temperature comes from."""
        return {
            "temperature_limit": self._limiter.enabled,
            "temperature_limit_active": self._limiter.active,
            "temperature_source": self._limiter.source,
        }

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the temperature limit and turn it on."""
        await self._limiter.async_set_target(float(kwargs[ATTR_TEMPERATURE]))

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
