"""Tests for the config flow."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr

from custom_components.solaredge_hwc.api import SolarEdgeAuthError
from custom_components.solaredge_hwc.const import (
    AUTH_COOKIE,
    AUTH_CREDENTIALS,
    CONF_AUTH_TYPE,
    CONF_COOKIE,
    CONF_DEVICE_ID,
    CONF_SCAN_INTERVAL,
    CONF_SITE_ID,
    CONF_SWITCH_OFF_MODE,
    CONF_TIMEOUT,
    DOMAIN,
)

from .conftest import DEVICE_ID, LOAD_DEVICE, SITE_ID


async def test_credentials_flow(hass: HomeAssistant, mock_client: dict[str, AsyncMock]) -> None:
    """Username/password login finds the single device automatically."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "credentials"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: "me@example.com", CONF_PASSWORD: "secret", CONF_SITE_ID: f" {SITE_ID} "},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_AUTH_TYPE: AUTH_CREDENTIALS,
        CONF_USERNAME: "me@example.com",
        CONF_PASSWORD: "secret",
        CONF_SITE_ID: SITE_ID,
        CONF_DEVICE_ID: DEVICE_ID,
    }
    assert result["result"].unique_id == f"{SITE_ID}_{DEVICE_ID}"
    mock_client["login"].assert_awaited()


async def test_credentials_flow_several_devices(
    hass: HomeAssistant, mock_client: dict[str, AsyncMock]
) -> None:
    """With several load devices the user picks one."""
    other = {"deviceInfo": {"deviceId": "999", "name": "Pool"}}
    mock_client["get_devices"].return_value = [LOAD_DEVICE, other]
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "credentials"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: "me@example.com", CONF_PASSWORD: "secret", CONF_SITE_ID: SITE_ID},
    )
    assert result["step_id"] == "select_device"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DEVICE_ID: "999"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_DEVICE_ID] == "999"


async def test_credentials_flow_invalid_auth(
    hass: HomeAssistant, mock_client: dict[str, AsyncMock]
) -> None:
    """Wrong credentials show an error."""
    mock_client["login"].side_effect = SolarEdgeAuthError("nope")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "credentials"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: "me@example.com", CONF_PASSWORD: "bad", CONF_SITE_ID: SITE_ID},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_cookie_flow(hass: HomeAssistant, mock_client: dict[str, AsyncMock]) -> None:
    """Cookie login with a given Device ID."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "cookie"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_SITE_ID: SITE_ID, CONF_DEVICE_ID: DEVICE_ID, CONF_COOKIE: "JSESSIONID=abc"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_AUTH_TYPE] == AUTH_COOKIE
    assert result["options"][CONF_SCAN_INTERVAL] == 60
    mock_client["get_state"].assert_awaited_with(DEVICE_ID)


async def test_reauth(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: dict[str, AsyncMock]
) -> None:
    """A fresh cookie is stored on reauth."""
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_COOKIE: "JSESSIONID=new"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_COOKIE] == "JSESSIONID=new"


async def test_reconfigure_new_device_keeps_device_entry(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    mock_client: dict[str, AsyncMock],
) -> None:
    """After a hardware swap the device registry entry moves to the new ID."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    device = device_registry.async_get_device(identifiers={(DOMAIN, DEVICE_ID)})
    assert device is not None

    result = await config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "reconfigure_cookie"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SITE_ID: SITE_ID, CONF_DEVICE_ID: "1111111"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_DEVICE_ID] == "1111111"
    # Empty cookie field keeps the stored cookie
    assert config_entry.data[CONF_COOKIE] == "JSESSIONID=abc; CSRF-TOKEN=tok"
    assert config_entry.unique_id == f"{SITE_ID}_1111111"
    moved = device_registry.async_get(device.id)
    assert (DOMAIN, "1111111") in moved.identifiers


async def test_options_flow(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: dict[str, AsyncMock]
) -> None:
    """Options are stored and reload the entry."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    with patch(
        "homeassistant.config_entries.ConfigEntries.async_schedule_reload"
    ) as reload:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {CONF_SCAN_INTERVAL: 120, CONF_TIMEOUT: 15, CONF_SWITCH_OFF_MODE: "off"},
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {
        CONF_SCAN_INTERVAL: 120,
        CONF_TIMEOUT: 15,
        CONF_SWITCH_OFF_MODE: "off",
    }
    reload.assert_called_once()
