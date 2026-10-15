"""Config flow for SolarEdge Hot Water Controller."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import probatio as vol

from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN, SensorDeviceClass
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import create_api_session, create_client
from .api import (
    SolarEdgeAuthError,
    SolarEdgeConnectionError,
    SolarEdgeError,
)
from .const import (
    AUTH_COOKIE,
    AUTH_CREDENTIALS,
    BASE_URL,
    CONF_AUTH_TYPE,
    CONF_COOKIE,
    CONF_DEVICE_ID,
    CONF_EVCC,
    CONF_EVCC_MODE_ENTITY,
    CONF_HYSTERESIS,
    CONF_SCAN_INTERVAL,
    CONF_SITE_ID,
    CONF_SWITCH_OFF_MODE,
    CONF_TEMPERATURE_SENSOR,
    CONF_TIMEOUT,
    DEFAULT_HYSTERESIS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SWITCH_OFF_MODE,
    DEFAULT_TIMEOUT,
    DOMAIN,
    ENTRY_TITLE_FORMAT,
    MAX_HYSTERESIS,
    MAX_SCAN_INTERVAL,
    MAX_TIMEOUT,
    MIN_HYSTERESIS,
    MIN_SCAN_INTERVAL,
    MIN_TIMEOUT,
    SWITCH_OFF_AUTO,
    SWITCH_OFF_OFF,
)
from .evcc import evcc_charger_config, find_mode_entities, is_mode_entity

_LOGGER = logging.getLogger(__name__)

_PASSWORD_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
_MULTILINE_SELECTOR = TextSelector(TextSelectorConfig(multiline=True))


class _FlowError(Exception):
    """Carries the translation key of a form error."""


async def _async_check(
    hass: HomeAssistant,
    data: Mapping[str, Any],
    timeout: int,
    *,
    discover: bool = False,
) -> list[dict[str, Any]]:
    """
    Log in and read the device state (or, with ``discover``, the device list).

    Returns the load devices of the site when ``discover`` is set.
    Raises ``_FlowError`` with the error key on failure.
    """
    # Requests log in first if needed, so the login is checked as well
    session = create_api_session(hass, auto_cleanup=False)
    client = create_client(hass, session, data, timeout)
    try:
        if discover:
            return await client.async_get_load_devices()
        await client.async_get_state(data[CONF_DEVICE_ID])
    except SolarEdgeAuthError as err:
        _LOGGER.debug("Authentication failed: %s", err)
        raise _FlowError("invalid_auth") from err
    except SolarEdgeConnectionError as err:
        _LOGGER.debug("Connection failed: %s", err)
        raise _FlowError("cannot_connect") from err
    except SolarEdgeError as err:
        _LOGGER.debug("Unexpected response: %s", err)
        raise _FlowError("invalid_response") from err
    except Exception as err:
        _LOGGER.exception("Unexpected error while validating")
        raise _FlowError("unknown") from err
    finally:
        session.detach()
    return []


def _clean(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Strip whitespace from all text fields."""
    return {
        key: value.strip() if isinstance(value, str) else value for key, value in user_input.items()
    }


def _device_label(device: dict[str, Any]) -> str:
    """Return a readable label for a discovered device."""
    info = device.get("deviceInfo") or {}
    parts = [str(info.get("name") or info.get("deviceId"))]
    if model := info.get("model"):
        parts.append(str(model))
    parts.append(f"ID {info.get('deviceId')}")
    return " · ".join(parts)


def _unique_id(site_id: str, device_id: str) -> str:
    """Build the config entry unique ID from Site ID and Device ID."""
    return f"{site_id}_{device_id}"


def _credentials_schema(
    defaults: Mapping[str, Any], *, with_device: bool, password_required: bool = True
) -> vol.Schema:
    """Form for username and password login."""
    password_key = vol.Required(CONF_PASSWORD) if password_required else vol.Optional(CONF_PASSWORD)
    schema: dict[Any, Any] = {
        vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, vol.UNDEFINED)): str,
        password_key: _PASSWORD_SELECTOR,
        vol.Required(CONF_SITE_ID, default=defaults.get(CONF_SITE_ID, vol.UNDEFINED)): str,
    }
    if with_device:
        schema[
            vol.Optional(CONF_DEVICE_ID, default=defaults.get(CONF_DEVICE_ID, vol.UNDEFINED))
        ] = str
    return vol.Schema(schema)


def _cookie_schema(defaults: Mapping[str, Any], *, cookie_required: bool) -> vol.Schema:
    """Form for cookie login."""
    cookie_key = vol.Required(CONF_COOKIE) if cookie_required else vol.Optional(CONF_COOKIE)
    return vol.Schema(
        {
            vol.Required(CONF_SITE_ID, default=defaults.get(CONF_SITE_ID, vol.UNDEFINED)): str,
            vol.Optional(CONF_DEVICE_ID, default=defaults.get(CONF_DEVICE_ID, vol.UNDEFINED)): str,
            cookie_key: _MULTILINE_SELECTOR,
        }
    )


@callback
def _async_migrate_device_id(
    hass: HomeAssistant, entry: ConfigEntry, old_device_id: str, new_device_id: str
) -> None:
    """
    Point the existing device registry entry at the new Device ID.

    The device is identified by ``(DOMAIN, device_id)``. Renaming that
    identifier instead of letting Home Assistant create a second device
    keeps all entities, their entity IDs, history and long-term statistics
    on the same device after a hardware replacement.
    """
    if old_device_id == new_device_id:
        return
    device_reg = dr.async_get(hass)
    device = device_reg.async_get_device_by_identifier((DOMAIN, old_device_id), entry.entry_id)
    if device is None:
        return
    if (
        device_reg.async_get_device_by_identifier((DOMAIN, new_device_id), entry.entry_id)
        is not None
    ):
        _LOGGER.warning(
            "A device with ID %s already exists; not migrating device %s",
            new_device_id,
            old_device_id,
        )
        return
    device_reg.async_update_device(device.id, new_identifiers={(DOMAIN, new_device_id)})


class SolarEdgeHWCConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow for SolarEdge Hot Water Controller."""

    VERSION = 2

    def __init__(self) -> None:
        """Initialize the flow."""
        self._data: dict[str, Any] = {}
        self._devices: list[dict[str, Any]] = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SolarEdgeHWCOptionsFlow:
        """Return the options flow handler."""
        return SolarEdgeHWCOptionsFlow()

    # -- initial setup ------------------------------------------------------

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Let the user choose how to log in."""
        return self.async_show_menu(step_id="user", menu_options=["credentials", "cookie"])

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Log in with the SolarEdge account."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**_clean(user_input), CONF_AUTH_TYPE: AUTH_CREDENTIALS}
            try:
                self._devices = await _async_check(self.hass, data, DEFAULT_TIMEOUT, discover=True)
            except _FlowError as err:
                errors["base"] = str(err)
            else:
                self._data = data
                return await self._async_after_discovery(errors)

        return self.async_show_form(
            step_id="credentials",
            data_schema=_credentials_schema(user_input or {}, with_device=False),
            errors=errors,
            description_placeholders={"portal_url": BASE_URL},
        )

    async def async_step_cookie(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Use a browser session cookie."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**_clean(user_input), CONF_AUTH_TYPE: AUTH_COOKIE}
            try:
                if data.get(CONF_DEVICE_ID):
                    await _async_check(self.hass, data, DEFAULT_TIMEOUT)
                    self._data = data
                    return await self._async_create(data)
                self._devices = await _async_check(self.hass, data, DEFAULT_TIMEOUT, discover=True)
            except _FlowError as err:
                errors["base"] = str(err)
            else:
                self._data = data
                return await self._async_after_discovery(errors)

        return self.async_show_form(
            step_id="cookie",
            data_schema=_cookie_schema(user_input or {}, cookie_required=True),
            errors=errors,
            description_placeholders={"portal_url": BASE_URL},
        )

    async def _async_after_discovery(self, errors: dict[str, str]) -> ConfigFlowResult:
        """Pick the device, or ask which one if the site has several."""
        if len(self._devices) == 1:
            device_id = str(self._devices[0]["deviceInfo"]["deviceId"])
            return await self._async_create({**self._data, CONF_DEVICE_ID: device_id})
        if not self._devices:
            return self.async_abort(reason="no_devices")
        return await self.async_step_select_device()

    async def async_step_select_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose one of several load devices."""
        if user_input is not None:
            return await self._async_create(
                {**self._data, CONF_DEVICE_ID: user_input[CONF_DEVICE_ID]}
            )
        options = [
            SelectOptionDict(
                value=str(device["deviceInfo"]["deviceId"]), label=_device_label(device)
            )
            for device in self._devices
        ]
        return self.async_show_form(
            step_id="select_device",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_ID): SelectSelector(
                        SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                    )
                }
            ),
        )

    async def _async_create(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Create the entry once the device is known."""
        await self.async_set_unique_id(_unique_id(data[CONF_SITE_ID], data[CONF_DEVICE_ID]))
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=ENTRY_TITLE_FORMAT.format(site_id=data[CONF_SITE_ID]),
            data=data,
            options={
                CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                CONF_TIMEOUT: DEFAULT_TIMEOUT,
                CONF_SWITCH_OFF_MODE: DEFAULT_SWITCH_OFF_MODE,
            },
        )

    # -- reauthentication ---------------------------------------------------

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Credentials were rejected: ask for new ones."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new password or cookie."""
        entry = self._get_reauth_entry()
        uses_credentials = entry.data.get(CONF_AUTH_TYPE) == AUTH_CREDENTIALS
        errors: dict[str, str] = {}

        if user_input is not None:
            data = {**entry.data, **_clean(user_input)}
            try:
                await _async_check(
                    self.hass, data, entry.options.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)
                )
            except _FlowError as err:
                errors["base"] = str(err)
            else:
                return self.async_update_reload_and_abort(entry, data=data)

        if uses_credentials:
            schema = vol.Schema(
                {
                    vol.Required(CONF_USERNAME, default=entry.data.get(CONF_USERNAME, "")): str,
                    vol.Required(CONF_PASSWORD): _PASSWORD_SELECTOR,
                }
            )
        else:
            schema = vol.Schema({vol.Required(CONF_COOKIE): _MULTILINE_SELECTOR})

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            errors=errors,
        )

    # -- reconfiguration ----------------------------------------------------

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user choose the login method for the new configuration."""
        entry = self._get_reconfigure_entry()
        return self.async_show_menu(
            step_id="reconfigure",
            menu_options=["reconfigure_credentials", "reconfigure_cookie"],
            description_placeholders={
                "site_id": entry.data[CONF_SITE_ID],
                "device_id": entry.data[CONF_DEVICE_ID],
            },
        )

    async def async_step_reconfigure_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change site, device or account."""
        entry = self._get_reconfigure_entry()
        has_password = entry.data.get(CONF_AUTH_TYPE) == AUTH_CREDENTIALS
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {CONF_AUTH_TYPE: AUTH_CREDENTIALS, **_clean(user_input)}
            if not data.get(CONF_PASSWORD) and has_password:
                # An empty field keeps the stored password
                data[CONF_PASSWORD] = entry.data[CONF_PASSWORD]
            if not data.get(CONF_PASSWORD):
                errors["base"] = "password_required"
            else:
                result = await self._async_reconfigure(entry, data, errors)
                if result is not None:
                    return result

        defaults = {**entry.data, **(user_input or {})}
        defaults.pop(CONF_PASSWORD, None)
        return self.async_show_form(
            step_id="reconfigure_credentials",
            data_schema=_credentials_schema(
                defaults, with_device=True, password_required=not has_password
            ),
            errors=errors,
            description_placeholders={
                "site_id": entry.data[CONF_SITE_ID],
                "device_id": entry.data[CONF_DEVICE_ID],
            },
        )

    async def async_step_reconfigure_cookie(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change site, device or cookie."""
        entry = self._get_reconfigure_entry()
        has_cookie = entry.data.get(CONF_AUTH_TYPE, AUTH_COOKIE) == AUTH_COOKIE
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {CONF_AUTH_TYPE: AUTH_COOKIE, **_clean(user_input)}
            if not data.get(CONF_COOKIE) and has_cookie:
                # An empty field keeps the stored cookie
                data[CONF_COOKIE] = entry.data[CONF_COOKIE]
            if not data.get(CONF_COOKIE):
                errors["base"] = "cookie_required"
            else:
                result = await self._async_reconfigure(entry, data, errors)
                if result is not None:
                    return result

        defaults = {**entry.data, **(user_input or {})}
        defaults.pop(CONF_COOKIE, None)
        return self.async_show_form(
            step_id="reconfigure_cookie",
            data_schema=_cookie_schema(defaults, cookie_required=not has_cookie),
            errors=errors,
            description_placeholders={
                "site_id": entry.data[CONF_SITE_ID],
                "device_id": entry.data[CONF_DEVICE_ID],
            },
        )

    async def _async_reconfigure(
        self, entry: ConfigEntry, data: dict[str, Any], errors: dict[str, str]
    ) -> ConfigFlowResult | None:
        """Validate and store a new configuration; fill ``errors`` on failure."""
        timeout = entry.options.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)
        data.setdefault(CONF_DEVICE_ID, "")
        if not data[CONF_DEVICE_ID]:
            data[CONF_DEVICE_ID] = entry.data[CONF_DEVICE_ID]

        new_unique_id = _unique_id(data[CONF_SITE_ID], data[CONF_DEVICE_ID])
        if new_unique_id != entry.unique_id and any(
            other.entry_id != entry.entry_id and other.unique_id == new_unique_id
            for other in self._async_current_entries(include_ignore=False)
        ):
            errors["base"] = "already_configured"
            return None

        try:
            await _async_check(self.hass, data, timeout)
        except _FlowError as err:
            errors["base"] = str(err)
            return None

        _async_migrate_device_id(self.hass, entry, entry.data[CONF_DEVICE_ID], data[CONF_DEVICE_ID])

        update: dict[str, Any] = {"data": data, "unique_id": new_unique_id}
        # Only rewrite the title while it is still the generated one
        if data[CONF_SITE_ID] != entry.data[CONF_SITE_ID] and entry.title == (
            ENTRY_TITLE_FORMAT.format(site_id=entry.data[CONF_SITE_ID])
        ):
            update["title"] = ENTRY_TITLE_FORMAT.format(site_id=data[CONF_SITE_ID])
        return self.async_update_reload_and_abort(entry, **update)


class SolarEdgeHWCOptionsFlow(OptionsFlowWithReload):
    """Polling and behaviour settings; the entry reloads when they change."""

    def __init__(self) -> None:
        """Initialize the flow."""
        self._options: dict[str, Any] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            options: dict[str, Any] = {
                CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                CONF_TIMEOUT: int(user_input[CONF_TIMEOUT]),
                CONF_SWITCH_OFF_MODE: user_input[CONF_SWITCH_OFF_MODE],
                CONF_HYSTERESIS: float(user_input[CONF_HYSTERESIS]),
                CONF_EVCC: bool(user_input.get(CONF_EVCC, False)),
            }
            # Clearing the field removes the fallback sensor
            if sensor := user_input.get(CONF_TEMPERATURE_SENSOR):
                options[CONF_TEMPERATURE_SENSOR] = sensor
            if mode_entity := user_input.get(CONF_EVCC_MODE_ENTITY):
                options[CONF_EVCC_MODE_ENTITY] = mode_entity

            if options[CONF_EVCC]:
                if not mode_entity:
                    errors[CONF_EVCC_MODE_ENTITY] = "evcc_entity_required"
                elif not is_mode_entity(self.hass, mode_entity):
                    errors[CONF_EVCC_MODE_ENTITY] = "evcc_entity_invalid"
            if not errors:
                self._options = options
                if options[CONF_EVCC]:
                    return await self.async_step_evcc()
                return self.async_create_entry(data=options)

        values: dict[str, Any] = {**self.config_entry.options, **(user_input or {})}
        if (
            CONF_EVCC_MODE_ENTITY not in values
            and len(candidates := find_mode_entities(self.hass)) == 1
        ):
            # A single evcc loadpoint: suggest its mode entity
            values[CONF_EVCC_MODE_ENTITY] = candidates[0]

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=values.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL,
                            max=MAX_SCAN_INTERVAL,
                            step=1,
                            unit_of_measurement="s",
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_TIMEOUT, default=values.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_TIMEOUT,
                            max=MAX_TIMEOUT,
                            step=1,
                            unit_of_measurement="s",
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_SWITCH_OFF_MODE,
                        default=values.get(CONF_SWITCH_OFF_MODE, DEFAULT_SWITCH_OFF_MODE),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[SWITCH_OFF_AUTO, SWITCH_OFF_OFF],
                            translation_key=CONF_SWITCH_OFF_MODE,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                    vol.Optional(
                        CONF_TEMPERATURE_SENSOR,
                        description={"suggested_value": values.get(CONF_TEMPERATURE_SENSOR)},
                    ): EntitySelector(
                        EntitySelectorConfig(
                            domain=SENSOR_DOMAIN, device_class=SensorDeviceClass.TEMPERATURE
                        )
                    ),
                    vol.Required(
                        CONF_HYSTERESIS,
                        default=values.get(CONF_HYSTERESIS, DEFAULT_HYSTERESIS),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_HYSTERESIS,
                            max=MAX_HYSTERESIS,
                            step=0.5,
                            unit_of_measurement="K",
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_EVCC, default=values.get(CONF_EVCC, False)
                    ): BooleanSelector(),
                    vol.Optional(
                        CONF_EVCC_MODE_ENTITY,
                        description={"suggested_value": values.get(CONF_EVCC_MODE_ENTITY)},
                    ): EntitySelector(EntitySelectorConfig(domain=["select", "input_select"])),
                }
            ),
            errors=errors,
        )

    async def async_step_evcc(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the configuration to enter in evcc, then save."""
        if user_input is not None:
            return self.async_create_entry(data=self._options)
        return self.async_show_form(
            step_id="evcc",
            data_schema=vol.Schema({}),
            description_placeholders={
                "config": evcc_charger_config(self.hass, self.config_entry),
                "mode_entity": self._options[CONF_EVCC_MODE_ENTITY],
            },
        )
