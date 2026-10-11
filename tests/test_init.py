"""Tests for setup, migration, entities and actions."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.solaredge_hwc.api import (
    SolarEdgeAuthError,
    SolarEdgeConnectionError,
    SolarEdgeRateLimitError,
)
from custom_components.solaredge_hwc.const import (
    AUTH_COOKIE,
    CONF_AUTH_TYPE,
    CONF_COOKIE,
    CONF_DEVICE_ID,
    CONF_SCAN_INTERVAL,
    CONF_SITE_ID,
    CONF_TIMEOUT,
    DOMAIN,
)

from .conftest import DEVICE_ID, SITE_ID


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_creates_entities(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: dict[str, AsyncMock]
) -> None:
    """All platforms come up with the expected values."""
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    prefix = "solaredge_hot_water_controller"
    assert hass.states.get(f"sensor.{prefix}_power").state == "0.0"
    assert hass.states.get(f"sensor.{prefix}_water_temperature").state == "67.60212"
    assert hass.states.get(f"sensor.{prefix}_activation_mode").state == "auto"
    assert hass.states.get(f"sensor.{prefix}_device_status").state == "active"
    assert hass.states.get(f"sensor.{prefix}_reason_heating_is_off").state == "pending_excess_solar"
    assert hass.states.get(f"binary_sensor.{prefix}_device_online").state == "on"
    assert hass.states.get(f"binary_sensor.{prefix}_heating_active").state == "off"
    assert hass.states.get(f"binary_sensor.{prefix}_excess_solar_heating").state == "on"
    assert hass.states.get(f"select.{prefix}_operating_mode").state == "auto"
    assert hass.states.get(f"switch.{prefix}_manual_heating").state == "off"
    assert hass.states.get(f"number.{prefix}_boost_duration").state == "60"
    assert hass.states.get(f"sensor.{prefix}_total_energy") is not None
    assert hass.states.get(f"sensor.{prefix}_next_scheduled_start").state != "unknown"
    heater = hass.states.get(f"water_heater.{prefix}")
    assert heater.state == "auto"
    assert heater.attributes["current_temperature"] == 67.6
    assert heater.attributes["operation_list"] == ["auto", "on", "off", "schedule"]

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_retry_on_connection_error(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: dict[str, AsyncMock]
) -> None:
    """A temporary error retries the setup later."""
    mock_client["get_state"].side_effect = SolarEdgeConnectionError("down")
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_auth_error_starts_reauth(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: dict[str, AsyncMock]
) -> None:
    """A rejected login asks the user to log in again."""
    mock_client["get_state"].side_effect = SolarEdgeAuthError("expired")
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


@pytest.mark.parametrize(
    ("option", "expected"),
    [
        ("auto", ("AUTO",)),
        ("schedule", ("SCHEDULE",)),
        ("off", ("MANUAL", 0, None)),
        ("on", ("MANUAL", 100, None)),
    ],
)
async def test_select_operation_mode(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: dict[str, AsyncMock],
    option: str,
    expected: tuple,
) -> None:
    """The select sends the matching activation state."""
    await _setup(hass, config_entry)
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.solaredge_hot_water_controller_operating_mode", "option": option},
        blocking=True,
    )
    call = mock_client["set_state"].call_args
    assert call.args[1] == expected[0]
    if len(expected) > 1:
        assert call.kwargs == {"level": expected[1], "duration": expected[2]}
    assert hass.states.get("select.solaredge_hot_water_controller_operating_mode").state == option


async def test_switch_and_boost(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: dict[str, AsyncMock]
) -> None:
    """Switch, boost button and the settings numbers work together."""
    await _setup(hass, config_entry)
    prefix = "solaredge_hot_water_controller"

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": f"number.{prefix}_manual_heating_level", "value": 50},
        blocking=True,
    )
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": f"switch.{prefix}_manual_heating"}, blocking=True
    )
    assert mock_client["set_state"].call_args.args[1:] == (DEVICE_ID, "MANUAL")[1:]
    assert mock_client["set_state"].call_args.kwargs == {"level": 50, "duration": None}
    assert hass.states.get(f"switch.{prefix}_manual_heating").state == "on"
    assert hass.states.get(f"sensor.{prefix}_power").state == "1500.0"

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": f"switch.{prefix}_manual_heating"}, blocking=True
    )
    assert mock_client["set_state"].call_args.args[1] == "AUTO"

    await hass.services.async_call(
        "button", "press", {"entity_id": f"button.{prefix}_boost"}, blocking=True
    )
    assert mock_client["set_state"].call_args.kwargs == {"level": 50, "duration": 3600}
    assert hass.states.get(f"sensor.{prefix}_manual_heating_until").state != "unknown"


async def test_actions(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: dict[str, AsyncMock]
) -> None:
    """The actions reach the controller targeted by its water heater entity."""
    await _setup(hass, config_entry)
    target = {"entity_id": "water_heater.solaredge_hot_water_controller"}
    await hass.services.async_call(
        DOMAIN,
        "set_operation_mode",
        {**target, "mode": "on", "level": 80, "duration": 30},
        blocking=True,
    )
    assert mock_client["set_state"].call_args.kwargs == {"level": 80, "duration": 1800}

    await hass.services.async_call(DOMAIN, "boost", {**target, "duration": 10}, blocking=True)
    assert mock_client["set_state"].call_args.kwargs == {"level": 100, "duration": 600}


@pytest.mark.parametrize(
    ("service", "data", "expected_mode", "expected_level"),
    [
        ("set_operation_mode", {"operation_mode": "schedule"}, "SCHEDULE", None),
        ("turn_on", {}, "AUTO", None),
        ("turn_off", {}, "MANUAL", 0),
    ],
)
async def test_water_heater(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: dict[str, AsyncMock],
    service: str,
    data: dict,
    expected_mode: str,
    expected_level: int | None,
) -> None:
    """The water heater entity sends the matching activation state."""
    await _setup(hass, config_entry)
    await hass.services.async_call(
        "water_heater",
        service,
        {"entity_id": "water_heater.solaredge_hot_water_controller", **data},
        blocking=True,
    )
    call = mock_client["set_state"].call_args
    assert call.args[1] == expected_mode
    assert call.kwargs.get("level") == expected_level


async def test_rate_limit_delays_next_poll(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: dict[str, AsyncMock]
) -> None:
    """HTTP 429 postpones the next poll by the requested time."""
    await _setup(hass, config_entry)
    coordinator = config_entry.runtime_data.coordinator
    mock_client["get_state"].side_effect = SolarEdgeRateLimitError("slow down", 600)
    await coordinator.async_refresh()
    assert not coordinator.last_update_success
    # The next poll is scheduled after the requested 600 s, not after 60 s
    next_poll = coordinator._unsub_refresh.__self__.when() - hass.loop.time()
    assert 590 < next_poll <= 601


async def test_command_error(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: dict[str, AsyncMock]
) -> None:
    """A failed command is reported to the user."""
    await _setup(hass, config_entry)
    mock_client["set_state"].side_effect = SolarEdgeConnectionError("down")
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": "button.solaredge_hot_water_controller_boost"},
            blocking=True,
        )


async def test_migrate_v1(
    hass: HomeAssistant, entity_registry: er.EntityRegistry, mock_client: dict[str, AsyncMock]
) -> None:
    """Version 1 entries keep their entities under new unique IDs."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        unique_id=f"{SITE_ID}_{DEVICE_ID}",
        data={
            CONF_SITE_ID: SITE_ID,
            CONF_DEVICE_ID: DEVICE_ID,
            CONF_COOKIE: "JSESSIONID=abc",
            CONF_SCAN_INTERVAL: 120,
            CONF_TIMEOUT: 20,
        },
    )
    entry.add_to_hass(hass)
    old = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "se_hwc_power_active",
        config_entry=entry,
        suggested_object_id="solaredge_hot_water_controller_power",
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.version == 2
    assert entry.data[CONF_AUTH_TYPE] == AUTH_COOKIE
    assert CONF_SCAN_INTERVAL not in entry.data
    assert entry.options[CONF_SCAN_INTERVAL] == 120
    assert entry.options[CONF_TIMEOUT] == 20
    migrated = entity_registry.async_get(old.entity_id)
    assert migrated.unique_id == f"{entry.entry_id}_power"
    assert hass.states.get(old.entity_id) is not None
