"""Switch platform: manual heating on/off."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

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
from .limiter import TemperatureLimiter

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolarEdgeHWCConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the manual heating switch."""
    async_add_entities(
        [
            HWCManualHeatingSwitch(
                entry.runtime_data.coordinator,
                entry.options.get(CONF_SWITCH_OFF_MODE, DEFAULT_SWITCH_OFF_MODE),
            ),
            HWCTemperatureLimitSwitch(entry.runtime_data.coordinator, entry.runtime_data.limiter),
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


class HWCTemperatureLimitSwitch(SolarEdgeHWCEntity, SwitchEntity):
    """
    Turns the temperature limit on or off.

    The target is set on the water heater entity. Only available when a
    water temperature is known, from the controller or the fallback sensor.
    """

    def __init__(self, coordinator, limiter: TemperatureLimiter) -> None:
        """Initialize the switch."""
        super().__init__(
            coordinator,
            SwitchEntityDescription(key="temperature_limit", translation_key="temperature_limit"),
        )
        self._limiter = limiter

    @property
    def available(self) -> bool:
        """Without a water temperature there is nothing to limit."""
        return super().available and self._limiter.has_temperature_source

    @property
    def is_on(self) -> bool:
        """Return True while the limit is on."""
        return self._limiter.enabled

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the limit itself."""
        return {
            "target_temperature": self._limiter.target,
            "hysteresis": self._limiter.hysteresis,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the limit on."""
        await self._limiter.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the limit off; a held controller returns to its mode."""
        await self._limiter.async_set_enabled(False)
