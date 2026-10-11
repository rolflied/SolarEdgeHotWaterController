"""Tests for the API helpers and the data model."""
from __future__ import annotations

from datetime import datetime

from homeassistant.util import dt as dt_util

from custom_components.solaredge_hwc.api import CookieAuth, _FormParser
from custom_components.solaredge_hwc.coordinator import HWCData

from .conftest import INFO, STATE


async def test_cookie_auth_sends_csrf_token() -> None:
    """The CSRF cookie is echoed in the header Spring Security expects."""
    auth = CookieAuth("Cookie: JSESSIONID=abc; CSRF-TOKEN=tok123; other=1")
    headers = await auth.async_headers()
    assert headers["Cookie"] == "JSESSIONID=abc; CSRF-TOKEN=tok123; other=1"
    assert headers["X-CSRF-TOKEN"] == "tok123"


async def test_cookie_auth_without_csrf() -> None:
    """No CSRF header without the cookie."""
    headers = await CookieAuth("JSESSIONID=abc").async_headers()
    assert "X-CSRF-TOKEN" not in headers


def test_form_parser_reads_first_form_only() -> None:
    """Hidden inputs of the login form are collected."""
    parser = _FormParser()
    parser.feed(
        '<form action="/x"><input name="csrf" value="1"><input name="username">'
        '</form><form><input name="other" value="2"></form>'
    )
    assert parser.form_found
    assert parser.inputs == {"csrf": "1", "username": ""}


def test_data_model() -> None:
    """Values are derived from state and info."""
    data = HWCData(state=STATE, info=INFO)
    assert data.online
    assert data.operation_mode == "auto"
    assert data.temperature == 67.60212
    assert data.power == 0.0
    assert not data.heating
    assert data.rated_power == 3000
    assert data.excess_pv_enabled is True


def test_power_estimated_without_meter() -> None:
    """Without a meter reading the power is estimated from the level."""
    data = HWCData(state={**STATE, "activationMode": "MANUAL", "percentageLevel": 50}, info=INFO)
    assert data.operation_mode == "on"
    assert data.power == 1500
    assert data.power_is_estimated
    assert data.heating


def test_power_measured() -> None:
    """A meter reading wins over the estimate."""
    state = {**STATE, "percentageLevel": 100, "measurements": {"activePowerMeter": 2950.4}}
    data = HWCData(state=state, info=INFO)
    assert data.power == 2950.4
    assert not data.power_is_estimated
    assert data.heating


def test_manual_off_and_offline() -> None:
    """MANUAL at level 0 is off; unknown statuses are offline."""
    data = HWCData(
        state={"activationMode": "MANUAL", "percentageLevel": 0, "deviceStatus": "OFFLINE"}
    )
    assert data.operation_mode == "off"
    assert not data.online
    assert data.power == 0.0


def test_next_schedule_start() -> None:
    """The next enabled schedule start is found across the week."""
    data = HWCData(state=STATE, info=INFO)
    tz = dt_util.get_default_time_zone()
    # Tuesday 2026-10-13 12:00 -> next is Wednesday 10:00
    now = datetime(2026, 10, 13, 12, 0, tzinfo=tz)
    assert data.next_schedule_start(now) == datetime(2026, 10, 14, 10, 0, tzinfo=tz)
    # Monday 09:00 -> same day 10:00
    now = datetime(2026, 10, 12, 9, 0, tzinfo=tz)
    assert data.next_schedule_start(now) == datetime(2026, 10, 12, 10, 0, tzinfo=tz)
