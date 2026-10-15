"""The SolarEdge Hot Water Controller integration."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import (
    config_validation as cv,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.storage import Store
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
from .evcc import (
    EvccModeFollower,
    async_register_evcc_entities,
    async_remove_evcc_entities,
    evcc_enabled,
    excess_pv_issue_id,
    unavailable_issue_id,
)
from .limiter import STORAGE_VERSION, TemperatureLimiter, storage_key
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
    limiter: TemperatureLimiter
    # Only while the evcc connection is switched on
    evcc: EvccModeFollower | None = None


type SolarEdgeHWCConfigEntry = ConfigEntry[SolarEdgeHWCRuntimeData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions of the integration."""
    async_setup_services(hass)
    return True


@asynccontextmanager
async def temporary_session(
    hass: HomeAssistant, **kwargs: Any
) -> AsyncIterator[aiohttp.ClientSession]:
    """Create a session on Home Assistant's connector for a single task."""
    session = async_create_clientsession(hass, auto_cleanup=False, **kwargs)
    try:
        yield session
    finally:
        session.detach()


def create_client(
    hass: HomeAssistant,
    session: aiohttp.ClientSession,
    data: Mapping[str, Any],
    timeout: int,
) -> SolarEdgeHWCClient:
    """Build the API client for the login method stored in the entry data."""
    auth: SolarEdgeAuth
    if data.get(CONF_AUTH_TYPE) == AUTH_CREDENTIALS:
        auth = OAuthAuth(
            session,
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
            timeout,
            # The login form needs cookies (a fresh jar per login), the API
            # session keeps none
            login_session=lambda: temporary_session(hass, cookie_jar=aiohttp.CookieJar()),
        )
    else:
        auth = CookieAuth(data[CONF_COOKIE])
    return SolarEdgeHWCClient(session, auth, data[CONF_SITE_ID], timeout)


def create_api_session(hass: HomeAssistant, **kwargs: Any) -> aiohttp.ClientSession:
    """
    Create the session for API requests.

    Cookies the portal sets must not mix with the cookie the user pasted,
    so the session keeps none.
    """
    return async_create_clientsession(hass, cookie_jar=aiohttp.DummyCookieJar(), **kwargs)


async def async_setup_entry(hass: HomeAssistant, entry: SolarEdgeHWCConfigEntry) -> bool:
    """Set up SolarEdge Hot Water Controller from a config entry."""
    # Created during setup, so Home Assistant detaches it on unload
    session = create_api_session(hass)
    client = create_client(
        hass, session, entry.data, entry.options.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)
    )
    coordinator = SolarEdgeHWCCoordinator(hass, entry, client)
    # Raises ConfigEntryNotReady / ConfigEntryAuthFailed as appropriate
    await coordinator.async_config_entry_first_refresh()

    limiter = TemperatureLimiter(hass, entry, coordinator)
    await limiter.async_start()

    evcc: EvccModeFollower | None = None
    if evcc_enabled(entry):
        async_register_evcc_entities(hass, entry)
        evcc = EvccModeFollower(hass, entry, coordinator)
        await evcc.async_start()
    else:
        async_remove_evcc_entities(hass, entry)

    entry.runtime_data = SolarEdgeHWCRuntimeData(
        coordinator=coordinator, limiter=limiter, evcc=evcc
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SolarEdgeHWCConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the stored limiter state and the repair issues."""
    await Store(hass, STORAGE_VERSION, storage_key(entry.entry_id)).async_remove()
    ir.async_delete_issue(hass, DOMAIN, f"temperature_unavailable_{entry.entry_id}")
    ir.async_delete_issue(hass, DOMAIN, unavailable_issue_id(entry.entry_id))
    ir.async_delete_issue(hass, DOMAIN, excess_pv_issue_id(entry.entry_id))


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
        hass.config_entries.async_update_entry(entry, data=data, options=options, version=2)

    return True
