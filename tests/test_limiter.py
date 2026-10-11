"""Tests for the temperature limit and the fallback temperature sensor."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from custom_components.solaredge_hwc.const import (
    CONF_HYSTERESIS,
    CONF_TEMPERATURE_SENSOR,
    DOMAIN,
)

from .conftest import STATE

HEATER = "water_heater.solaredge_hot_water_controller"
LIMIT_SWITCH = "switch.solaredge_hot_water_controller_temperature_limit"
LIMIT_REACHED = "binary_sensor.solaredge_hot_water_controller_temperature_limit_reached"


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _poll(hass: HomeAssistant, entry: MockConfigEntry, mock_client, **state) -> None:
    """Let the coordinator read a new state."""
    mock_client["get_state"].return_value = {**STATE, **state}
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()


async def _set_target(hass: HomeAssistant, target: float) -> None:
    await hass.services.async_call(
        "water_heater",
        "set_temperature",
        {"entity_id": HEATER, "temperature": target},
        blocking=True,
    )
    await hass.async_block_till_done()


async def test_limit_switches_off_and_back(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: dict[str, AsyncMock],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Reaching the target switches off; cooling below the hysteresis restores auto."""
    await _setup(hass, config_entry)
    assert hass.states.get(LIMIT_SWITCH).state == "off"
    mock_client["set_state"].assert_not_called()

    # 67.6 °C in AUTO and a target of 60 °C: switch off
    await _set_target(hass, 60)
    assert hass.states.get(LIMIT_SWITCH).state == "on"
    assert hass.states.get(HEATER).attributes["temperature"] == 60
    call = mock_client["set_state"].call_args
    assert call.args[1:] == ("7654321", "MANUAL")[1:]
    assert call.kwargs["level"] == 0
    assert hass.states.get(LIMIT_REACHED).state == "on"

    # Still above target - hysteresis (55 °C): nothing happens
    mock_client["set_state"].reset_mock()
    freezer.tick(timedelta(minutes=3))
    await _poll(
        hass,
        config_entry,
        mock_client,
        activationMode="MANUAL",
        percentageLevel=0,
        measurements={"measuredTemperature": 57.0},
    )
    mock_client["set_state"].assert_not_called()

    # Below 55 °C: back to the previous mode
    await _poll(
        hass,
        config_entry,
        mock_client,
        activationMode="MANUAL",
        percentageLevel=0,
        measurements={"measuredTemperature": 54.0},
    )
    assert mock_client["set_state"].call_args.args[1] == "AUTO"
    assert hass.states.get(LIMIT_REACHED).state == "off"


async def test_limit_ignores_manual_heating(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: dict[str, AsyncMock]
) -> None:
    """Manual heating is an explicit request and not limited."""
    mock_client["get_state"].return_value = {
        **STATE,
        "activationMode": "MANUAL",
        "percentageLevel": 100,
    }
    await _setup(hass, config_entry)
    await _set_target(hass, 60)
    mock_client["set_state"].assert_not_called()
    assert hass.states.get(LIMIT_REACHED).state == "off"


async def test_turning_limit_off_releases(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: dict[str, AsyncMock],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Turning the limit off returns a held controller to its mode."""
    await _setup(hass, config_entry)
    await _set_target(hass, 60)
    await _poll(hass, config_entry, mock_client, activationMode="MANUAL", percentageLevel=0)
    await hass.services.async_call("switch", "turn_off", {"entity_id": LIMIT_SWITCH}, blocking=True)
    assert mock_client["set_state"].call_args.args[1] == "AUTO"
    assert hass.states.get(LIMIT_SWITCH).state == "off"


async def test_fallback_sensor_and_outage(
    hass: HomeAssistant,
    mock_client: dict[str, AsyncMock],
    issue_registry: ir.IssueRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Without a probe the sensor is used; losing it releases the limit."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id="1_2",
        data={
            "auth_type": "cookie",
            "site_id": "1",
            "device_id": "2",
            "cookie": "JSESSIONID=abc",
        },
        options={CONF_TEMPERATURE_SENSOR: "sensor.boiler", CONF_HYSTERESIS: 5},
    )
    mock_client["get_state"].return_value = {**STATE, "measurements": {}}
    hass.states.async_set("sensor.boiler", "149", {"unit_of_measurement": "°F"})
    await _setup(hass, entry)

    state = hass.states.get(HEATER)
    assert state.attributes["current_temperature"] == 65.0
    assert state.attributes["temperature_source"] == "sensor"

    await _set_target(hass, 60)
    assert mock_client["set_state"].call_args.kwargs["level"] == 0
    await _poll(
        hass, entry, mock_client, activationMode="MANUAL", percentageLevel=0, measurements={}
    )

    # The sensor goes away: release and report it
    freezer.tick(timedelta(minutes=3))
    hass.states.async_set("sensor.boiler", "unavailable")
    await hass.async_block_till_done()
    await _poll(
        hass, entry, mock_client, activationMode="MANUAL", percentageLevel=0, measurements={}
    )
    assert mock_client["set_state"].call_args.args[1] == "AUTO"
    assert issue_registry.async_get_issue(DOMAIN, f"temperature_unavailable_{entry.entry_id}")

    # Back again: the issue disappears
    hass.states.async_set("sensor.boiler", "120", {"unit_of_measurement": "°F"})
    await hass.async_block_till_done()
    assert not issue_registry.async_get_issue(DOMAIN, f"temperature_unavailable_{entry.entry_id}")


async def test_limit_survives_restart(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: dict[str, AsyncMock],
    freezer: FrozenDateTimeFactory,
) -> None:
    """A held controller is still released after a reload."""
    await _setup(hass, config_entry)
    await _set_target(hass, 60)
    mock_client["get_state"].return_value = {
        **STATE,
        "activationMode": "MANUAL",
        "percentageLevel": 0,
        "measurements": {"measuredTemperature": 50.0},
    }
    freezer.tick(timedelta(seconds=2))
    await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=3))
    await config_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert mock_client["set_state"].call_args.args[1] == "AUTO"
