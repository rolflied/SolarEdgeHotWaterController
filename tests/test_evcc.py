"""Tests for the evcc connection."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er, issue_registry as ir

from custom_components.solaredge_hwc.const import (
    CONF_EVCC,
    CONF_EVCC_MODE_ENTITY,
    CONF_HYSTERESIS,
    CONF_SCAN_INTERVAL,
    CONF_SWITCH_OFF_MODE,
    CONF_TIMEOUT,
    DOMAIN,
)

from .conftest import DEVICE_ID, STATE

MODE = "select.evcc_hot_water_mode"
MODES = ["off", "smart", "now"]
STATUS = "sensor.solaredge_hwc_evcc_status"
ENABLE = "switch.solaredge_hwc_evcc_enable"
CURRENT = "number.solaredge_hwc_evcc_current"


def _set_mode(hass: HomeAssistant, mode: str, options: list[str] = MODES) -> None:
    hass.states.async_set(MODE, mode, {"options": options})


@pytest.fixture
def evcc_entry(config_entry: MockConfigEntry) -> MockConfigEntry:
    """Return an entry with the evcc connection switched on."""
    return MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title=config_entry.title,
        unique_id=config_entry.unique_id,
        data=config_entry.data,
        options={**config_entry.options, CONF_EVCC: True, CONF_EVCC_MODE_ENTITY: MODE},
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _poll(hass: HomeAssistant, entry: MockConfigEntry, mock_client, **state) -> None:
    mock_client["get_state"].return_value = {**STATE, **state}
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()


async def _change_mode(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, mode: str, wait: int = 61
) -> None:
    freezer.tick(timedelta(seconds=wait))
    _set_mode(hass, mode)
    await hass.async_block_till_done()


def _last_command(mock_client) -> tuple[str, dict]:
    call = mock_client["set_state"].call_args
    assert call.args[0] == DEVICE_ID
    return call.args[1], call.kwargs


async def test_modes_are_applied(
    hass: HomeAssistant,
    evcc_entry: MockConfigEntry,
    mock_client: dict[str, AsyncMock],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Off, smart and now map onto off, automatic and on at 100 %."""
    _set_mode(hass, "smart")
    await _setup(hass, evcc_entry)
    # The controller is already in AUTO: nothing to send
    mock_client["set_state"].assert_not_called()
    assert hass.states.get(STATUS).state == "connected"
    assert hass.states.get(STATUS).attributes["applied_operation"] == "auto"

    await _change_mode(hass, freezer, "now")
    mode, kwargs = _last_command(mock_client)
    assert mode == "MANUAL"
    assert kwargs == {"level": 100, "duration": 900}

    await _change_mode(hass, freezer, "off")
    mode, kwargs = _last_command(mock_client)
    assert mode == "MANUAL"
    assert kwargs["level"] == 0
    assert kwargs.get("duration") is None

    await _change_mode(hass, freezer, "smart")
    assert _last_command(mock_client)[0] == "AUTO"
    assert mock_client["set_state"].call_count == 3


async def test_legacy_modes(
    hass: HomeAssistant,
    evcc_entry: MockConfigEntry,
    mock_client: dict[str, AsyncMock],
    freezer: FrozenDateTimeFactory,
) -> None:
    """The mode names of evcc before 0.315 work as well."""
    legacy = ["off", "pv", "minpv", "now"]
    _set_mode(hass, "off", legacy)
    await _setup(hass, evcc_entry)
    assert _last_command(mock_client)[1]["level"] == 0

    freezer.tick(timedelta(seconds=61))
    _set_mode(hass, "minpv", legacy)
    await hass.async_block_till_done()
    assert _last_command(mock_client)[0] == "AUTO"


async def test_commands_are_throttled(
    hass: HomeAssistant,
    evcc_entry: MockConfigEntry,
    mock_client: dict[str, AsyncMock],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Quick changes are combined; only the latest mode is sent."""
    _set_mode(hass, "smart")
    await _setup(hass, evcc_entry)

    await _change_mode(hass, freezer, "now")
    assert mock_client["set_state"].call_count == 1
    await _change_mode(hass, freezer, "off", wait=5)
    await _change_mode(hass, freezer, "smart", wait=5)
    # AUTO is the last mode, but the controller still reports AUTO from the
    # stale poll; the change is applied once the interval has passed
    await _poll(hass, evcc_entry, mock_client, activationMode="MANUAL", percentageLevel=100)
    assert mock_client["set_state"].call_count == 1

    freezer.tick(timedelta(seconds=60))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert mock_client["set_state"].call_count == 2
    assert _last_command(mock_client)[0] == "AUTO"


async def test_on_is_renewed_and_ends(
    hass: HomeAssistant,
    evcc_entry: MockConfigEntry,
    mock_client: dict[str, AsyncMock],
    freezer: FrozenDateTimeFactory,
) -> None:
    """On is renewed while evcc reports now, and not once evcc is gone."""
    _set_mode(hass, "now")
    await _setup(hass, evcc_entry)
    assert mock_client["set_state"].call_count == 1
    await _poll(hass, evcc_entry, mock_client, activationMode="MANUAL", percentageLevel=100)

    freezer.tick(timedelta(minutes=10))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert mock_client["set_state"].call_count == 2
    assert _last_command(mock_client)[1] == {"level": 100, "duration": 900}

    # evcc goes away: no renewal; the issue appears after 10 minutes
    hass.states.async_set(MODE, "unavailable")
    await hass.async_block_till_done()
    issues = ir.async_get(hass)
    issue_id = f"evcc_mode_unavailable_{evcc_entry.entry_id}"
    for _ in range(25):
        freezer.tick(timedelta(seconds=30))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    assert mock_client["set_state"].call_count == 2
    assert issues.async_get_issue(DOMAIN, issue_id) is not None

    # Back with the same mode: on is sent again, the issue disappears
    _set_mode(hass, "now")
    await hass.async_block_till_done()
    assert issues.async_get_issue(DOMAIN, issue_id) is None


async def test_manual_change_wins(
    hass: HomeAssistant,
    evcc_entry: MockConfigEntry,
    mock_client: dict[str, AsyncMock],
    freezer: FrozenDateTimeFactory,
) -> None:
    """A mode chosen by hand is kept until evcc changes its mode."""
    _set_mode(hass, "now")
    await _setup(hass, evcc_entry)
    assert mock_client["set_state"].call_count == 1

    freezer.tick(timedelta(minutes=3))
    await _poll(hass, evcc_entry, mock_client, activationMode="AUTO", percentageLevel=0)
    assert hass.states.get(STATUS).attributes["override"] is True

    freezer.tick(timedelta(minutes=10))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    # Not renewed, and nothing else sent
    assert mock_client["set_state"].call_count == 1

    await _change_mode(hass, freezer, "off")
    assert mock_client["set_state"].call_count == 2


async def test_placeholders_have_no_effect(
    hass: HomeAssistant,
    evcc_entry: MockConfigEntry,
    mock_client: dict[str, AsyncMock],
) -> None:
    """evcc can switch and set the placeholders; the controller is not touched."""
    _set_mode(hass, "smart")
    await _setup(hass, evcc_entry)

    registry = er.async_get(hass)
    assert registry.async_get(ENABLE).hidden_by is er.RegistryEntryHider.INTEGRATION
    assert registry.async_get(CURRENT).hidden_by is er.RegistryEntryHider.INTEGRATION

    await hass.services.async_call("switch", "turn_on", {"entity_id": ENABLE}, blocking=True)
    await hass.services.async_call(
        "number", "set_value", {"entity_id": CURRENT, "value": 6.5}, blocking=True
    )
    assert hass.states.get(ENABLE).state == "on"
    assert hass.states.get(CURRENT).state == "6.5"
    assert hass.states.get(CURRENT).attributes["unit_of_measurement"] == "A"
    mock_client["set_state"].assert_not_called()

    # Heating is reported as charging
    await _poll(hass, evcc_entry, mock_client, percentageLevel=80)
    assert hass.states.get(STATUS).state == "charging"


async def test_disabling_removes_entities(
    hass: HomeAssistant,
    evcc_entry: MockConfigEntry,
    mock_client: dict[str, AsyncMock],
) -> None:
    """Switching the connection off removes the evcc entities."""
    _set_mode(hass, "smart")
    await _setup(hass, evcc_entry)
    assert hass.states.get(STATUS) is not None

    hass.config_entries.async_update_entry(
        evcc_entry, options={**evcc_entry.options, CONF_EVCC: False}
    )
    await hass.config_entries.async_reload(evcc_entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    for entity_id in (STATUS, ENABLE, CURRENT):
        assert registry.async_get(entity_id) is None


async def test_excess_pv_issue(
    hass: HomeAssistant,
    evcc_entry: MockConfigEntry,
    mock_client: dict[str, AsyncMock],
) -> None:
    """A repair issue tells that SolarEdge's excess heating is off."""
    info = mock_client["get_info"].return_value
    mock_client["get_info"].return_value = {
        **info,
        "deviceConfigurations": {**info["deviceConfigurations"], "excessPVEnabled": "OFF"},
    }
    _set_mode(hass, "smart")
    await _setup(hass, evcc_entry)
    issue_id = f"evcc_excess_pv_disabled_{evcc_entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None


async def test_options_flow_evcc(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: dict[str, AsyncMock]
) -> None:
    """The options validate the mode entity and show the evcc configuration."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    hass.states.async_set("select.other", "a", {"options": ["a", "b"]})
    _set_mode(hass, "smart")

    base = {
        CONF_SCAN_INTERVAL: 60,
        CONF_TIMEOUT: 30,
        CONF_SWITCH_OFF_MODE: "auto",
        CONF_HYSTERESIS: 5,
    }
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    # The only evcc mode entity is suggested
    schema = result["data_schema"].schema
    key = next(k for k in schema if k == CONF_EVCC_MODE_ENTITY)
    assert key.description["suggested_value"] == MODE

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**base, CONF_EVCC: True}
    )
    assert result["errors"] == {CONF_EVCC_MODE_ENTITY: "evcc_entity_required"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**base, CONF_EVCC: True, CONF_EVCC_MODE_ENTITY: "select.other"}
    )
    assert result["errors"] == {CONF_EVCC_MODE_ENTITY: "evcc_entity_invalid"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**base, CONF_EVCC: True, CONF_EVCC_MODE_ENTITY: MODE}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "evcc"
    config = result["description_placeholders"]["config"]
    assert f"status: {STATUS}" in config
    assert f"enable: {ENABLE}" in config
    assert f"setMaxCurrent: {CURRENT}" in config
    assert "power: sensor.solaredge_hot_water_controller_power" in config

    with patch("homeassistant.config_entries.ConfigEntries.async_schedule_reload"):
        result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options[CONF_EVCC] is True
    assert config_entry.options[CONF_EVCC_MODE_ENTITY] == MODE
