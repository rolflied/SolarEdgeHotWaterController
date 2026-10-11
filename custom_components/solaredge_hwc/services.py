"""Actions (services) of the SolarEdge Hot Water Controller integration."""
from __future__ import annotations

from typing import TYPE_CHECKING

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_DURATION,
    ATTR_LEVEL,
    ATTR_MODE,
    DOMAIN,
    MAX_BOOST_DURATION_MIN,
    OPERATION_MODES,
    SERVICE_BOOST,
    SERVICE_SET_OPERATION_MODE,
)

if TYPE_CHECKING:
    from .coordinator import SolarEdgeHWCCoordinator

_LEVEL = vol.All(vol.Coerce(int), vol.Range(min=0, max=100))
_DURATION = vol.All(vol.Coerce(int), vol.Range(min=1, max=MAX_BOOST_DURATION_MIN))

SET_OPERATION_MODE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_MODE): vol.In(OPERATION_MODES),
        vol.Optional(ATTR_LEVEL): _LEVEL,
        vol.Optional(ATTR_DURATION): _DURATION,
    }
)

BOOST_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(ATTR_DURATION): _DURATION,
        vol.Optional(ATTR_LEVEL): _LEVEL,
    }
)


@callback
def _coordinator(hass: HomeAssistant, call: ServiceCall) -> SolarEdgeHWCCoordinator:
    """Find the controller an action is meant for."""
    entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]
    if entry_id := call.data.get(ATTR_CONFIG_ENTRY_ID):
        entries = [entry for entry in entries if entry.entry_id == entry_id]
        if not entries:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="entry_not_loaded",
                translation_placeholders={"entry_id": entry_id},
            )
    elif len(entries) != 1:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="entry_required"
        )
    return entries[0].runtime_data.coordinator


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the actions."""

    async def _set_operation_mode(call: ServiceCall) -> None:
        await _coordinator(hass, call).async_set_operation_mode(
            call.data[ATTR_MODE],
            level=call.data.get(ATTR_LEVEL),
            duration=call.data.get(ATTR_DURATION),
        )

    async def _boost(call: ServiceCall) -> None:
        await _coordinator(hass, call).async_boost(
            duration=call.data.get(ATTR_DURATION), level=call.data.get(ATTR_LEVEL)
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_OPERATION_MODE,
        _set_operation_mode,
        schema=SET_OPERATION_MODE_SCHEMA,
    )
    hass.services.async_register(DOMAIN, SERVICE_BOOST, _boost, schema=BOOST_SCHEMA)
