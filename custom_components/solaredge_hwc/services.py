"""Actions (services) of the SolarEdge Hot Water Controller integration."""

from __future__ import annotations

import probatio as vol

from homeassistant.components.water_heater import DOMAIN as WATER_HEATER_DOMAIN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import service

from .const import (
    ATTR_DURATION,
    ATTR_LEVEL,
    ATTR_MODE,
    DOMAIN,
    MAX_BOOST_DURATION_MIN,
    OPERATION_MODES,
    SERVICE_BOOST,
    SERVICE_SET_OPERATION_MODE,
)

_LEVEL = vol.All(vol.Coerce(int), vol.Range(min=0, max=100))
_DURATION = vol.All(vol.Coerce(int), vol.Range(min=1, max=MAX_BOOST_DURATION_MIN))


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """
    Register the actions.

    Both target the water heater entity of a controller, so automations pick
    the controller with the regular target selector (entity, device or area).
    """
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_SET_OPERATION_MODE,
        entity_domain=WATER_HEATER_DOMAIN,
        schema={
            vol.Required(ATTR_MODE): vol.In(OPERATION_MODES),
            vol.Optional(ATTR_LEVEL): _LEVEL,
            vol.Optional(ATTR_DURATION): _DURATION,
        },
        func="async_set_hwc_operation_mode",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_BOOST,
        entity_domain=WATER_HEATER_DOMAIN,
        schema={
            vol.Optional(ATTR_DURATION): _DURATION,
            vol.Optional(ATTR_LEVEL): _LEVEL,
        },
        func="async_boost",
    )
