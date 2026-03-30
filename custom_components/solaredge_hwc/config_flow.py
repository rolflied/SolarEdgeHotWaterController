"""Config flow for SolarEdge Hot Water Controller."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    DOMAIN,
    CONF_SITE_ID,
    CONF_DEVICE_ID,
    CONF_COOKIE,
    CONF_SCAN_INTERVAL,
    CONF_TIMEOUT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    API_BASE_URL,
    API_HWC_ENDPOINT,
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
                unique_id = f"{site_id}_{device_id}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"SolarEdge HWC (Site {site_id})",
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

        Lets the user paste a new cookie without having to remove and
        re-add the integration.
        """
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            new_cookie = user_input.get(CONF_COOKIE, "").strip()
            try:
                await validate_connection(
                    site_id=entry.data[CONF_SITE_ID],
                    device_id=entry.data[CONF_DEVICE_ID],
                    cookie=new_cookie,
                    timeout=entry.data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
                )
            except ValueError as err:
                errors["base"] = str(err)
            else:
                new_data = dict(entry.data)
                new_data[CONF_COOKIE] = new_cookie
                return self.async_update_reload_and_abort(
                    entry,
                    data=new_data,
                    reason="reconfigure_successful",
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_COOKIE): str,
                }
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

    Allows updating the browser cookie, scan interval, and timeout
    directly via the Home Assistant UI (Settings → Integrations → Configure).

    IMPORTANT: No __init__ override — HA 2024.12+ sets self.config_entry
    automatically. Defining __init__(config_entry) here causes a 500 error.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ):
        """Manage the options."""
        errors: dict[str, str] = {}

        current_data = self.config_entry.data
        current_scan_interval = current_data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        current_timeout = current_data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)

        if user_input is not None:
            new_cookie = user_input.get(CONF_COOKIE, "").strip()

            # Validate new cookie if one was provided
            if new_cookie:
                try:
                    await validate_connection(
                        site_id=current_data[CONF_SITE_ID],
                        device_id=current_data[CONF_DEVICE_ID],
                        cookie=new_cookie,
                        timeout=user_input.get(CONF_TIMEOUT, current_timeout),
                    )
                except ValueError as err:
                    errors["base"] = str(err)

            if not errors:
                # Build updated config data
                new_data = dict(current_data)
                if new_cookie:
                    new_data[CONF_COOKIE] = new_cookie
                new_data[CONF_SCAN_INTERVAL] = user_input.get(
                    CONF_SCAN_INTERVAL, current_scan_interval
                )
                new_data[CONF_TIMEOUT] = user_input.get(CONF_TIMEOUT, current_timeout)

                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data=new_data,
                )
                return self.async_create_entry(title="", data={})

        options_schema = vol.Schema(
            {
                # Cookie field is optional: leave blank to keep existing cookie
                vol.Optional(CONF_COOKIE): str,
                vol.Optional(
                    CONF_SCAN_INTERVAL, default=current_scan_interval
                ): vol.All(vol.Coerce(int), vol.Range(min=30, max=600)),
                vol.Optional(
                    CONF_TIMEOUT, default=current_timeout
                ): vol.All(vol.Coerce(int), vol.Range(min=10, max=120)),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
            errors=errors,
        )
