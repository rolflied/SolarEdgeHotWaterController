"""Tests for the API helpers and the data model."""

from __future__ import annotations

from datetime import datetime

import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.solaredge_hwc import create_api_session, create_client
from custom_components.solaredge_hwc.api import (
    CookieAuth,
    SolarEdgeAuthError,
    SolarEdgeConnectionError,
    SolarEdgeRateLimitError,
    _FormParser,
    _retry_after,
)
from custom_components.solaredge_hwc.const import (
    AUTH_COOKIE,
    CONF_AUTH_TYPE,
    CONF_COOKIE,
    CONF_SITE_ID,
)
from custom_components.solaredge_hwc.coordinator import HWCData

from .conftest import DEVICE_ID, INFO, SITE_ID, STATE


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


# -- HTTP behaviour of the client --------------------------------------------

STATE_URL = (
    f"https://monitoring.solaredge.com/services/m/so/load-device/site/{SITE_ID}"
    f"/device/{DEVICE_ID}/state"
)
ACTIVATION_URL = (
    f"https://monitoring.solaredge.com/services/m/api/homeautomation/v1.0/{SITE_ID}"
    f"/devices/{DEVICE_ID}/activationState"
)
COOKIE_DATA = {
    CONF_AUTH_TYPE: AUTH_COOKIE,
    CONF_SITE_ID: SITE_ID,
    CONF_COOKIE: "JSESSIONID=abc; CSRF-TOKEN=tok",
}


def _client(hass: HomeAssistant):
    return create_client(hass, create_api_session(hass), COOKIE_DATA, 10)


async def test_client_reads_state(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """The state is decoded and the cookie is sent."""
    aioclient_mock.get(STATE_URL, json=STATE)
    assert await _client(hass).async_get_state(DEVICE_ID) == STATE
    headers = aioclient_mock.mock_calls[0][3]
    assert headers["Cookie"] == "JSESSIONID=abc; CSRF-TOKEN=tok"


async def test_client_put_sends_csrf_and_body(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Commands carry the CSRF token and the activation state."""
    aioclient_mock.put(ACTIVATION_URL, text="")
    await _client(hass).async_set_activation_state(DEVICE_ID, "MANUAL", level=50, duration=600)
    _, _, body, headers = aioclient_mock.mock_calls[0]
    assert body == {"mode": "MANUAL", "level": 50, "duration": 600}
    assert headers["X-CSRF-TOKEN"] == "tok"


@pytest.mark.parametrize(
    "response",
    [
        {"status": 401},
        {"status": 302, "headers": {"Location": "https://monitoring.solaredge.com/login"}},
        {"status": 200, "text": "<html>login</html>"},
    ],
)
async def test_client_expired_cookie(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, response: dict
) -> None:
    """Rejections, login redirects and login pages mean the cookie expired."""
    aioclient_mock.get(STATE_URL, **response)
    with pytest.raises(SolarEdgeAuthError):
        await _client(hass).async_get_state(DEVICE_ID)


async def test_client_rate_limited(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """HTTP 429 carries the bounded Retry-After value."""
    aioclient_mock.get(STATE_URL, status=429, headers={"Retry-After": "120"})
    with pytest.raises(SolarEdgeRateLimitError) as err:
        await _client(hass).async_get_state(DEVICE_ID)
    assert err.value.retry_after == 120


async def test_client_server_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """5xx answers are temporary."""
    aioclient_mock.get(STATE_URL, status=503)
    with pytest.raises(SolarEdgeConnectionError):
        await _client(hass).async_get_state(DEVICE_ID)


@pytest.mark.parametrize(
    ("header", "expected"),
    [(None, 300), ("5", 60), ("90000", 3600), ("Wed, 21 Oct 2026 07:28:00 GMT", 300)],
)
def test_retry_after_bounds(header: str | None, expected: float) -> None:
    """Retry-After values are kept within sane bounds."""
    assert _retry_after(header) == expected
