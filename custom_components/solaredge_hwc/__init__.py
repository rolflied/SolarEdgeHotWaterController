"""The SolarEdge Hot Water Controller integration."""
from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .api import CookieAuth, OAuthAuth, SolarEdgeAuth, SolarEdgeHWCClient
from .const import (
    AUTH_COOKIE,
    AUTH_CREDENTIALS,
    CONF_AUTH_TYPE,
    CONF_COOKIE,
    CONF_SCAN_INTERVAL,
    CONF_SITE_ID,
    CONF_TIMEOUT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import SolarEdgeHWCCoordinator
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# Unique IDs of version 1 were the same for every config entry
_V1_UNIQUE_IDS = {
    "se_hwc_power_active": "power",
    "se_hwc_level_percent": "heating_level",
    "se_hwc_activation_mode": "activation_mode",
    "se_hwc_device_status": "device_status",
    "se_hwc_total_energy": "total_energy",
    "se_hwc_heating_active": "heating_active",
    "se_hwc_device_online": "device_online",
}


@dataclass
class SolarEdgeHWCRuntimeData:
    """Objects that live as long as the config entry is loaded."""

    coordinator: SolarEdgeHWCCoordinator
    session: aiohttp.ClientSession
    options: dict[str, Any]


type SolarEdgeHWCConfigEntry = ConfigEntry[SolarEdgeHWCRuntimeData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions of the integration."""
    async_setup_services(hass)
    return True


def create_auth(
    session: aiohttp.ClientSession, data: dict[str, Any], timeout: int
) -> SolarEdgeAuth:
    """Build the authentication strategy stored in the entry data."""
    if data.get(CONF_AUTH_TYPE) == AUTH_CREDENTIALS:
        return OAuthAuth(session, data[CONF_USERNAME], data[CONF_PASSWORD], timeout)
    return CookieAuth(data[CONF_COOKIE])


def create_session() -> aiohttp.ClientSession:
    """
    Create the HTTP session for API requests.

    Cookies the portal sets must not mix with the cookie the user pasted,
    so the session keeps none.
    """
    return aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar())


async def async_setup_entry(hass: HomeAssistant, entry: SolarEdgeHWCConfigEntry) -> bool:
    """Set up SolarEdge Hot Water Controller from a config entry."""
    timeout = entry.options.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)
    session = create_session()
    client = SolarEdgeHWCClient(
        session,
        create_auth(session, dict(entry.data), timeout),
        entry.data[CONF_SITE_ID],
        timeout,
    )
    coordinator = SolarEdgeHWCCoordinator(hass, entry, client)

    try:
        # Raises ConfigEntryNotReady / ConfigEntryAuthFailed as appropriate
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await session.close()
        raise

    entry.runtime_data = SolarEdgeHWCRuntimeData(
        coordinator=coordinator, session=session, options=dict(entry.options)
    )
    entry.async_on_unload(session.close)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SolarEdgeHWCConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(
    hass: HomeAssistant, entry: SolarEdgeHWCConfigEntry
) -> None:
    """
    Reload when the options changed.

    Reauth and reconfigure reload the entry themselves; reacting to their
    data updates here as well would reload it twice.
    """
    if dict(entry.options) != entry.runtime_data.options:
        hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries."""
    if entry.version > 2:
        # Downgrade from a future version
        return False

    if entry.version == 1:
        _LOGGER.debug("Migrating SolarEdge HWC entry %s from version 1", entry.entry_id)
        data = dict(entry.data)
        options = dict(entry.options)
        data.setdefault(CONF_AUTH_TYPE, AUTH_COOKIE)
        # Polling settings are options from version 2 on
        options[CONF_SCAN_INTERVAL] = data.pop(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        options[CONF_TIMEOUT] = data.pop(CONF_TIMEOUT, DEFAULT_TIMEOUT)

        @callback
        def _migrate_unique_id(entity: er.RegistryEntry) -> dict[str, Any] | None:
            key = _V1_UNIQUE_IDS.get(entity.unique_id)
            if key is None:
                return None
            return {"new_unique_id": f"{entry.entry_id}_{key}"}

        await er.async_migrate_entries(hass, entry.entry_id, _migrate_unique_id)
        hass.config_entries.async_update_entry(
            entry, data=data, options=options, version=2
        )

    return True
