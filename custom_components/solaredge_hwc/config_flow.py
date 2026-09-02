"""Config flow for SolarEdge Hot Water Controller."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

from .const import (
    DOMAIN,
    CONF_SITE_ID,
    CONF_DEVICE_ID,
    CONF_COOKIE,
    CONF_SCAN_INTERVAL,
    CONF_TIMEOUT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    ENTRY_TITLE_FORMAT,
    API_BASE_URL,
    API_HWC_ENDPOINT,
    ERROR_ALREADY_CONFIGURED,
    ERROR_AUTH_FAILED,
    ERROR_CANNOT_CONNECT,
    ERROR_INVALID_RESPONSE,
    ERROR_UNKNOWN,
)

_LOGGER = logging.getLogger(__name__)


async def validate_connection(
    site_id: str,
    device_id: str,
    cookie: str,
    timeout: int = DEFAULT_TIMEOUT,
) -> None:
    """
    Validate that the given credentials connect to the SolarEdge HWC API.

    Raises ValueError with an error key on failure.
    """
    url = f"{API_BASE_URL}{API_HWC_ENDPOINT.format(site_id=site_id, device_id=device_id)}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": (
            f"https://monitoring.solaredge.com/v/s/{site_id}/smart-energy/hot-water"
        ),
        "Cookie": cookie,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                if response.status in (401, 403):
                    raise ValueError(ERROR_AUTH_FAILED)

                if response.status != 200:
                    _LOGGER.error(
                        "SolarEdge HWC API returned HTTP %s during validation",
                        response.status,
                    )
                    raise ValueError(ERROR_AUTH_FAILED)

                try:
                    data = await response.json(content_type=None)
                except Exception:
                    raise ValueError(ERROR_INVALID_RESPONSE)

                # Basic sanity check: the response should contain HWC-specific fields
                if not any(
                    k in data
                    for k in ("measurements", "percentageLevel", "activationMode", "deviceStatus")
                ):
                    _LOGGER.error(
                        "SolarEdge HWC API response missing expected fields: %s", data
                    )
                    raise ValueError(ERROR_INVALID_RESPONSE)

    except ValueError:
        raise
    except aiohttp.ClientConnectorError as err:
        _LOGGER.error("Cannot connect to SolarEdge API: %s", err)
        raise ValueError(ERROR_CANNOT_CONNECT)
    except aiohttp.ClientError as err:
        _LOGGER.error("HTTP client error during validation: %s", err)
        raise ValueError(ERROR_CANNOT_CONNECT)
    except Exception as err:
        _LOGGER.exception("Unexpected error validating SolarEdge HWC connection: %s", err)
        raise ValueError(ERROR_UNKNOWN)


# ---------------------------------------------------------------------------
# Helpers shared by the reconfigure and the options flow
# ---------------------------------------------------------------------------

def _unique_id(site_id: str, device_id: str) -> str:
    """Build the config entry unique ID from Site ID and Device ID."""
    return f"{site_id}_{device_id}"


@callback
def _async_id_used_by_other_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    unique_id: str,
) -> bool:
    """Return True if another config entry already uses this Site/Device ID pair."""
    return any(
        other.entry_id != entry.entry_id and other.unique_id == unique_id
        for other in hass.config_entries.async_entries(DOMAIN)
    )


@callback
def _async_migrate_device_id(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    old_device_id: str,
    new_device_id: str,
) -> None:
    """
    Point the existing device registry entry at the new Device ID.

    The device is identified by ``(DOMAIN, device_id)``. Renaming that
    identifier instead of letting Home Assistant create a second device
    keeps all entities — and therefore their entity IDs, history and
    long-term statistics — attached to the same device after a hardware
    replacement.
    """
    if old_device_id == new_device_id:
        return

    device_reg = dr.async_get(hass)
    device = device_reg.async_get_device(identifiers={(DOMAIN, old_device_id)})
    if device is None or entry.entry_id not in device.config_entries:
        return

    if device_reg.async_get_device(identifiers={(DOMAIN, new_device_id)}) is not None:
        _LOGGER.warning(
            "A device with ID %s already exists in the device registry; "
            "not migrating device %s",
            new_device_id,
            old_device_id,
        )
        return

    _LOGGER.debug(
        "Migrating SolarEdge HWC device identifier from %s to %s",
        old_device_id,
        new_device_id,
    )
    device_reg.async_update_device(
        device.id, new_identifiers={(DOMAIN, new_device_id)}
    )


async def _async_build_updated_data(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    user_input: dict[str, Any],
) -> tuple[dict[str, Any], str, str | None]:
    """
    Validate user input against the API and return the updated entry data.

    Returns a tuple of ``(new_data, new_unique_id, new_title)`` where
    ``new_title`` is ``None`` if the entry title should stay untouched.

    Raises ``ValueError`` carrying an error key if validation fails.
    """
    current = entry.data

    site_id = (user_input.get(CONF_SITE_ID) or current[CONF_SITE_ID]).strip()
    device_id = (user_input.get(CONF_DEVICE_ID) or current[CONF_DEVICE_ID]).strip()
    # An empty cookie field means "keep the existing cookie"
    cookie = (user_input.get(CONF_COOKIE) or "").strip() or current[CONF_COOKIE]
    scan_interval = user_input.get(
        CONF_SCAN_INTERVAL, current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )
    timeout = user_input.get(
        CONF_TIMEOUT, current.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)
    )

    new_unique_id = _unique_id(site_id, device_id)
    if new_unique_id != entry.unique_id and _async_id_used_by_other_entry(
        hass, entry, new_unique_id
    ):
        raise ValueError(ERROR_ALREADY_CONFIGURED)

    await validate_connection(
        site_id=site_id,
        device_id=device_id,
        cookie=cookie,
        timeout=timeout,
    )

    _async_migrate_device_id(hass, entry, current[CONF_DEVICE_ID], device_id)

    new_data = {
        **current,
        CONF_SITE_ID: site_id,
        CONF_DEVICE_ID: device_id,
        CONF_COOKIE: cookie,
        CONF_SCAN_INTERVAL: scan_interval,
        CONF_TIMEOUT: timeout,
    }

    # Only rewrite the title while it is still the generated one, so that a
    # title the user has customised survives a Site ID change.
    new_title: str | None = None
    old_title = ENTRY_TITLE_FORMAT.format(site_id=current[CONF_SITE_ID])
    if site_id != current[CONF_SITE_ID] and entry.title == old_title:
        new_title = ENTRY_TITLE_FORMAT.format(site_id=site_id)

    return new_data, new_unique_id, new_title


def _credentials_schema(
    site_id: str,
    device_id: str,
    scan_interval: int,
    timeout: int,
) -> vol.Schema:
    """
    Build the schema used by the reconfigure and the options step.

    Site ID and Device ID are pre-filled with the values currently in use;
    the cookie field stays empty and only replaces the stored cookie when
    something is entered.
    """
    return vol.Schema(
        {
            vol.Required(CONF_SITE_ID, default=site_id): str,
            vol.Required(CONF_DEVICE_ID, default=device_id): str,
            vol.Optional(CONF_COOKIE): str,
            vol.Optional(CONF_SCAN_INTERVAL, default=scan_interval): vol.All(
                vol.Coerce(int), vol.Range(min=30, max=600)
            ),
            vol.Optional(CONF_TIMEOUT, default=timeout): vol.All(
                vol.Coerce(int), vol.Range(min=10, max=120)
            ),
        }
    )


class SolarEdgeHWCConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial config flow for SolarEdge Hot Water Controller."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ):
        """Handle the user setup step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            site_id = user_input[CONF_SITE_ID].strip()
            device_id = user_input[CONF_DEVICE_ID].strip()
            cookie = user_input[CONF_COOKIE].strip()

            try:
                await validate_connection(
                    site_id=site_id,
                    device_id=device_id,
                    cookie=cookie,
                    timeout=user_input.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
                )
            except ValueError as err:
                errors["base"] = str(err)
            else:
                await self.async_set_unique_id(_unique_id(site_id, device_id))
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=ENTRY_TITLE_FORMAT.format(site_id=site_id),
                    data={
                        CONF_SITE_ID: site_id,
                        CONF_DEVICE_ID: device_id,
                        CONF_COOKIE: cookie,
                        CONF_SCAN_INTERVAL: user_input.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                        CONF_TIMEOUT: user_input.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
                    },
                )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_SITE_ID): str,
                vol.Required(CONF_DEVICE_ID): str,
                vol.Required(CONF_COOKIE): str,
                vol.Optional(
                    CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                ): vol.All(vol.Coerce(int), vol.Range(min=30, max=600)),
                vol.Optional(
                    CONF_TIMEOUT, default=DEFAULT_TIMEOUT
                ): vol.All(vol.Coerce(int), vol.Range(min=10, max=120)),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ):
        """
        Handle 'Reconfigure' from the three-dot menu.

        Lets the user paste a new cookie and — after a hardware replacement —
        change Site ID and Device ID without removing and re-adding the
        integration. All entities keep their entity IDs and history.
        """
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            try:
                new_data, new_unique_id, new_title = await _async_build_updated_data(
                    self.hass, entry, user_input
                )
            except ValueError as err:
                errors["base"] = str(err)
            else:
                update_args: dict[str, Any] = {
                    "data": new_data,
                    "unique_id": new_unique_id,
                    "reason": "reconfigure_successful",
                }
                if new_title is not None:
                    update_args["title"] = new_title
                return self.async_update_reload_and_abort(entry, **update_args)

        # Pre-fill with what was submitted last (on error) or the stored values
        shown = {**entry.data, **(user_input or {})}

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_credentials_schema(
                site_id=shown[CONF_SITE_ID],
                device_id=shown[CONF_DEVICE_ID],
                scan_interval=shown.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                timeout=shown.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
            ),
            errors=errors,
            description_placeholders={
                "site_id": entry.data.get(CONF_SITE_ID, ""),
                "device_id": entry.data.get(CONF_DEVICE_ID, ""),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "SolarEdgeHWCOptionsFlow":
        """Return the options flow handler."""
        # Note: do NOT pass config_entry here — HA 2024.12+ sets
        # self.config_entry on the OptionsFlow automatically.
        return SolarEdgeHWCOptionsFlow()


class SolarEdgeHWCOptionsFlow(config_entries.OptionsFlow):
    """
    Options flow for SolarEdge Hot Water Controller.

    Allows updating the browser cookie, Site ID, Device ID, scan interval
    and timeout directly via the Home Assistant UI
    (Settings → Integrations → Configure).

    IMPORTANT: No __init__ override — HA 2024.12+ sets self.config_entry
    automatically. Defining __init__(config_entry) here causes a 500 error.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ):
        """Manage the options."""
        errors: dict[str, str] = {}

        entry = self.config_entry
        current_data = entry.data

        if user_input is not None:
            try:
                new_data, new_unique_id, new_title = await _async_build_updated_data(
                    self.hass, entry, user_input
                )
            except ValueError as err:
                errors["base"] = str(err)
            else:
                update_args: dict[str, Any] = {
                    "data": new_data,
                    "unique_id": new_unique_id,
                }
                if new_title is not None:
                    update_args["title"] = new_title
                self.hass.config_entries.async_update_entry(entry, **update_args)
                return self.async_create_entry(title="", data={})

        # Pre-fill with what was submitted last (on error) or the stored values
        shown = {**current_data, **(user_input or {})}

        return self.async_show_form(
            step_id="init",
            data_schema=_credentials_schema(
                site_id=shown[CONF_SITE_ID],
                device_id=shown[CONF_DEVICE_ID],
                scan_interval=shown.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                timeout=shown.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
            ),
            errors=errors,
        )
