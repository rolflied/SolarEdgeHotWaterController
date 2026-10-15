"""
Let evcc choose the operating mode of the hot water controller.

SolarEdge regulates the excess solar power itself, so evcc does not control
the heating element. It only picks the mode of its loadpoint, which this
module reads from a select entity (as provided by the ha-evcc integration)
and maps onto the controller:

* ``off`` → off (manual, level 0)
* ``smart`` (``pv``, ``minpv`` before evcc 0.315) → automatic
* ``now`` → on at 100 %, for a limited time that is renewed while evcc
  still reports ``now``

Commands are only sent when the evcc mode changes. A mode chosen by hand in
Home Assistant or the SolarEdge app is kept until the next change in evcc.

evcc also shows the controller as a loadpoint. Its Home Assistant charger
needs an enable switch and a current entity; this integration provides them
as placeholders without any effect (see the switch and number platforms).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.number import DOMAIN as NUMBER_DOMAIN
from homeassistant.components.select import ATTR_OPTIONS
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, EntityCategory
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.util import dt as dt_util

from .const import (
    API_MODE_MANUAL,
    CONF_EVCC,
    CONF_EVCC_MODE_ENTITY,
    DOMAIN,
    EVCC_CURRENT_KEY,
    EVCC_ENABLE_KEY,
    EVCC_MIN_COMMAND_INTERVAL,
    EVCC_MODE_NOW,
    EVCC_MODE_OFF,
    EVCC_MODE_OPERATIONS,
    EVCC_MODE_PV,
    EVCC_MODE_SMART,
    EVCC_ON_DURATION,
    EVCC_ON_LEVEL,
    EVCC_RENEW_INTERVAL,
    EVCC_STATUS_KEY,
    EVCC_UNAVAILABLE_ISSUE_DELAY,
    OPERATION_ON,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from . import SolarEdgeHWCConfigEntry
    from .coordinator import SolarEdgeHWCCoordinator

_LOGGER = logging.getLogger(__name__)

# How often pending commands, renewals and the availability are checked
_CHECK_INTERVAL = timedelta(seconds=30)
# How long the cloud may lag behind a command before its state is trusted
_COMMAND_GRACE = timedelta(minutes=2)

# Entities created for evcc: (platform, key, hidden in the UI)
EVCC_ENTITIES: tuple[tuple[str, str, bool], ...] = (
    (SENSOR_DOMAIN, EVCC_STATUS_KEY, False),
    (SWITCH_DOMAIN, EVCC_ENABLE_KEY, True),
    (NUMBER_DOMAIN, EVCC_CURRENT_KEY, True),
)


def evcc_enabled(entry: ConfigEntry) -> bool:
    """Return True if the evcc connection is switched on in the options."""
    return bool(entry.options.get(CONF_EVCC)) and bool(entry.options.get(CONF_EVCC_MODE_ENTITY))


def is_mode_entity(hass: HomeAssistant, entity_id: str) -> bool:
    """Return True if the entity offers the loadpoint modes of evcc."""
    if (state := hass.states.get(entity_id)) is None:
        return False
    options = set(state.attributes.get(ATTR_OPTIONS) or [])
    return {EVCC_MODE_OFF, EVCC_MODE_NOW} <= options and bool(
        options & {EVCC_MODE_SMART, EVCC_MODE_PV}
    )


def find_mode_entities(hass: HomeAssistant) -> list[str]:
    """Return the select entities that look like an evcc loadpoint mode."""
    return sorted(
        state.entity_id
        for state in hass.states.async_all(("select", "input_select"))
        if is_mode_entity(hass, state.entity_id)
    )


def unavailable_issue_id(entry_id: str) -> str:
    """Return the ID of the repair issue for a missing evcc mode."""
    return f"evcc_mode_unavailable_{entry_id}"


def excess_pv_issue_id(entry_id: str) -> str:
    """Return the ID of the repair issue for disabled excess solar heating."""
    return f"evcc_excess_pv_disabled_{entry_id}"


# ---------------------------------------------------------------------------
# Entity registry helpers
# ---------------------------------------------------------------------------


@callback
def async_register_evcc_entities(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, str]:
    """
    Register the evcc entities with fixed entity IDs; return them by key.

    Registering them up front gives them IDs that do not depend on the UI
    language, so the evcc configuration can be shown before they are loaded.
    """
    registry = er.async_get(hass)
    entity_ids: dict[str, str] = {}
    for platform, key, hidden in EVCC_ENTITIES:
        unique_id = f"{entry.entry_id}_{key}"
        if (entity_id := registry.async_get_entity_id(platform, DOMAIN, unique_id)) is None:
            entity_id = registry.async_get_or_create(
                platform,
                DOMAIN,
                unique_id,
                config_entry=entry,
                suggested_object_id=f"{DOMAIN}_{key}",
                entity_category=EntityCategory.DIAGNOSTIC if hidden else None,
                hidden_by=er.RegistryEntryHider.INTEGRATION if hidden else None,
            ).entity_id
        entity_ids[key] = entity_id
    return entity_ids


@callback
def async_remove_evcc_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove the evcc entities after the connection was switched off."""
    registry = er.async_get(hass)
    for platform, key, _ in EVCC_ENTITIES:
        if entity_id := registry.async_get_entity_id(platform, DOMAIN, f"{entry.entry_id}_{key}"):
            registry.async_remove(entity_id)
    ir.async_delete_issue(hass, DOMAIN, unavailable_issue_id(entry.entry_id))
    ir.async_delete_issue(hass, DOMAIN, excess_pv_issue_id(entry.entry_id))


def _entity_id(hass: HomeAssistant, entry: ConfigEntry, platform: str, key: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{entry.entry_id}_{key}")


def evcc_charger_config(hass: HomeAssistant, entry: ConfigEntry) -> str:
    """Return the evcc charger and loadpoint configuration as YAML."""
    ids = async_register_evcc_entities(hass, entry)
    try:
        uri = get_url(hass, allow_external=False)
    except NoURLAvailableError:
        uri = "http://homeassistant.local:8123"

    lines = [
        "chargers:",
        "  - name: hot_water",
        "    type: template",
        "    template: homeassistant",
        f"    uri: {uri}",
        f"    status: {ids[EVCC_STATUS_KEY]}",
        f"    enabled: {ids[EVCC_ENABLE_KEY]}",
        f"    enable: {ids[EVCC_ENABLE_KEY]}",
        f"    setMaxCurrent: {ids[EVCC_CURRENT_KEY]}",
    ]
    if power := _entity_id(hass, entry, SENSOR_DOMAIN, "power"):
        lines.append(f"    power: {power}")
    if energy := _entity_id(hass, entry, SENSOR_DOMAIN, "total_energy"):
        lines.append(f"    energy: {energy}")
    if temp := _entity_id(hass, entry, SENSOR_DOMAIN, "water_temperature"):
        lines.append(f"    # temp: {temp}  # evcc nightly or newer than 0.317")
    lines += [
        "    heating: true",
        "    integrateddevice: true",
        "",
        "loadpoints:",
        "  - title: Hot water",
        "    charger: hot_water",
        "    mode: smart",
        "    phases: 1",
        "    priority: 0  # below the wallbox",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Mode follower
# ---------------------------------------------------------------------------


class EvccModeFollower:
    """Apply the evcc loadpoint mode to the controller."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: SolarEdgeHWCConfigEntry,
        coordinator: SolarEdgeHWCCoordinator,
    ) -> None:
        """Initialize the follower."""
        self.hass = hass
        self._entry = entry
        self._coordinator = coordinator
        self.mode_entity_id: str = entry.options[CONF_EVCC_MODE_ENTITY]
        self._lock = asyncio.Lock()

        # Last valid mode read from evcc
        self.evcc_mode: str | None = None
        # Operation sent (or found already set) for that mode
        self.applied_operation: str | None = None
        # True while a new mode still has to be sent
        self._pending = False
        self.last_command: datetime | None = None
        self._last_on: datetime | None = None
        self._unavailable_since: datetime | None = None

    # -- state ----------------------------------------------------------------

    @property
    def target_operation(self) -> str | None:
        """Return the operation that belongs to the current evcc mode."""
        return EVCC_MODE_OPERATIONS.get(self.evcc_mode) if self.evcc_mode else None

    @property
    def override(self) -> bool:
        """Return True if the mode was changed by hand after evcc set it."""
        data = self._coordinator.data
        if self.applied_operation is None or self._pending or data is None:
            return False
        return data.operation_mode != self.applied_operation and not self._in_grace()

    @property
    def attributes(self) -> dict[str, Any]:
        """Describe the state for the status entity."""
        return {
            "evcc_mode": self.evcc_mode,
            "applied_operation": self.applied_operation,
            "override": self.override,
            "last_command": self.last_command.isoformat() if self.last_command else None,
            "mode_entity": self.mode_entity_id,
        }

    def _read_mode(self) -> str | None:
        """Return the evcc mode, None if it is unknown."""
        state = self.hass.states.get(self.mode_entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        mode = state.state.lower()
        return mode if mode in EVCC_MODE_OPERATIONS else None

    def _in_grace(self) -> bool:
        return self.last_command is not None and (
            dt_util.utcnow() - self.last_command < _COMMAND_GRACE
        )

    def _may_send(self) -> bool:
        return self.last_command is None or (
            dt_util.utcnow() - self.last_command >= EVCC_MIN_COMMAND_INTERVAL
        )

    # -- lifecycle ------------------------------------------------------------

    async def async_start(self) -> None:
        """Start watching the evcc mode."""
        self._entry.async_on_unload(
            async_track_state_change_event(
                self.hass, [self.mode_entity_id], self._handle_mode_change
            )
        )
        self._entry.async_on_unload(
            async_track_time_interval(self.hass, self._handle_interval, _CHECK_INTERVAL)
        )
        self._entry.async_on_unload(self._coordinator.async_add_listener(self._update_issues))
        self._update_issues()
        await self.async_evaluate()

    @callback
    def _handle_mode_change(self, event: Event[EventStateChangedData]) -> None:
        self._schedule()

    @callback
    def _handle_interval(self, _now: datetime) -> None:
        self._schedule()

    @callback
    def _schedule(self) -> None:
        self._entry.async_create_background_task(
            self.hass, self.async_evaluate(), f"{DOMAIN} evcc mode"
        )

    # -- control loop ---------------------------------------------------------

    async def async_evaluate(self) -> None:
        """Send what the evcc mode asks for."""
        async with self._lock:
            before = self._snapshot()
            try:
                await self._async_evaluate()
            except HomeAssistantError as err:
                # Retried on the next check
                _LOGGER.warning("Could not apply the evcc mode %s: %s", self.evcc_mode, err)
            if self._snapshot() != before:
                self._coordinator.async_update_listeners()

    def _snapshot(self) -> tuple[Any, ...]:
        return (self.evcc_mode, self.applied_operation, self._pending, self.last_command)

    async def _async_evaluate(self) -> None:
        mode = self._read_mode()
        self._update_availability(mode is not None)
        if mode is None:
            # Without a mode nothing is sent; a running "on" is not renewed
            # and ends on its own
            return

        if mode != self.evcc_mode:
            _LOGGER.debug("evcc mode changed from %s to %s", self.evcc_mode, mode)
            self.evcc_mode = mode
            self._pending = True

        data = self._coordinator.data
        if data is None:
            return
        target = EVCC_MODE_OPERATIONS[mode]

        if self._pending:
            if target != OPERATION_ON and data.operation_mode == target:
                # Already there (e.g. after a restart); nothing to send
                self.applied_operation = target
                self._pending = False
                return
            if not self._may_send():
                return
            await self._async_send(target)
            self._pending = False
            return

        # "On" is renewed while evcc still wants it, unless someone changed
        # the mode by hand in the meantime
        if (
            target == OPERATION_ON
            and self.applied_operation == OPERATION_ON
            and not self.override
            and self._last_on is not None
            and dt_util.utcnow() - self._last_on >= EVCC_RENEW_INTERVAL
            and self._may_send()
        ):
            await self._async_send(OPERATION_ON)

    async def _async_send(self, operation: str) -> None:
        """Send one command and remember it."""
        now = dt_util.utcnow()
        # Counted even if it fails, so a broken cloud is not hammered
        self.last_command = now
        _LOGGER.debug("Applying evcc mode %s: %s", self.evcc_mode, operation)
        if operation == OPERATION_ON:
            await self._coordinator.async_set_activation_state(
                API_MODE_MANUAL,
                level=EVCC_ON_LEVEL,
                duration=int(EVCC_ON_DURATION.total_seconds()),
            )
            self._last_on = now
        else:
            await self._coordinator.async_set_operation_mode(operation)
            self._last_on = None
        self.applied_operation = operation

    # -- repair issues --------------------------------------------------------

    @callback
    def _update_availability(self, available: bool) -> None:
        issue_id = unavailable_issue_id(self._entry.entry_id)
        if available:
            self._unavailable_since = None
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
            return
        now = dt_util.utcnow()
        if self._unavailable_since is None:
            self._unavailable_since = now
        if now - self._unavailable_since >= EVCC_UNAVAILABLE_ISSUE_DELAY:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="evcc_mode_unavailable",
                translation_placeholders={
                    "entry": self._entry.title,
                    "entity": self.mode_entity_id,
                },
            )

    @callback
    def _update_issues(self) -> None:
        """Warn if SolarEdge's own excess solar heating is off."""
        data = self._coordinator.data
        issue_id = excess_pv_issue_id(self._entry.entry_id)
        if data is not None and data.excess_pv_enabled is False:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="evcc_excess_pv_disabled",
                translation_placeholders={"entry": self._entry.title},
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
