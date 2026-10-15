"""Diagnostics support for SolarEdge Hot Water Controller."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import SolarEdgeHWCConfigEntry
from .const import CONF_COOKIE, CONF_SITE_ID
from .evcc import evcc_charger_config

TO_REDACT = {
    CONF_COOKIE,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_SITE_ID,
    "serialNumber",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SolarEdgeHWCConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data.coordinator
    limiter = entry.runtime_data.limiter
    data = coordinator.data
    evcc = entry.runtime_data.evcc
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "last_update_success": coordinator.last_update_success,
        "temperature_limit": {
            "enabled": limiter.enabled,
            "target": limiter.target,
            "hysteresis": limiter.hysteresis,
            "held_from": limiter.held_from,
            "temperature": limiter.temperature,
            "source": limiter.source,
        },
        "evcc": (
            {**evcc.attributes, "config": evcc_charger_config(hass, entry)}
            if evcc is not None
            else None
        ),
        "state": data.state if data else None,
        "info": async_redact_data(data.info, TO_REDACT) if data else None,
    }
