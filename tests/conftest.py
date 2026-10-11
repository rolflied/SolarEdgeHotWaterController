"""Fixtures for the SolarEdge Hot Water Controller tests."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solaredge_hwc.const import (
    AUTH_COOKIE,
    CONF_AUTH_TYPE,
    CONF_COOKIE,
    CONF_DEVICE_ID,
    CONF_SCAN_INTERVAL,
    CONF_SITE_ID,
    CONF_SWITCH_OFF_MODE,
    CONF_TIMEOUT,
    DOMAIN,
)

SITE_ID = "1234567"
DEVICE_ID = "7654321"

STATE: dict[str, Any] = {
    "deviceStatus": "ACTIVE",
    "activationMode": "AUTO",
    "percentageLevel": 0,
    "autoOffReason": "PENDING_EXCESS_SOLAR",
    "scheduleType": "EXCESS_PV",
    "measurements": {"measuredTemperature": 67.60212},
    "portiaCommunicationStatus": "ACTIVE",
}

INFO: dict[str, Any] = {
    "deviceInfo": {
        "deviceId": DEVICE_ID,
        "name": "SolarEdge Heizstab",
        "serialNumber": "0000000",
        "manufacturer": "SolarEdge",
        "model": "SMRT-HOT-WTR-30-S2",
        "type": "LEVEL_CTRL",
    },
    "deviceConfigurations": {"iconName": "GENERIC", "ratedPower": 3000, "excessPVEnabled": "ON"},
    "schedules": {
        "allSchedules": [
            {
                "enable": True,
                "scheduledDays": ["MONDAY", "WEDNESDAY"],
                "startTime": 600,
                "endTime": 720,
                "smartSaver": False,
                "triggerId": 0,
            }
        ]
    },
}

LOAD_DEVICE = {
    "portiaCommunicationStatus": "ACTIVE",
    "deviceInfo": {"deviceId": DEVICE_ID, "name": "SolarEdge Heizstab", "type": "LEVEL_CTRL"},
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load the integration from custom_components."""


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Return a cookie based config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title=f"SolarEdge HWC (Site {SITE_ID})",
        unique_id=f"{SITE_ID}_{DEVICE_ID}",
        data={
            CONF_AUTH_TYPE: AUTH_COOKIE,
            CONF_SITE_ID: SITE_ID,
            CONF_DEVICE_ID: DEVICE_ID,
            CONF_COOKIE: "JSESSIONID=abc; CSRF-TOKEN=tok",
        },
        options={CONF_SCAN_INTERVAL: 60, CONF_TIMEOUT: 30, CONF_SWITCH_OFF_MODE: "auto"},
    )


@pytest.fixture
def mock_client() -> Generator[dict[str, AsyncMock]]:
    """Patch the API client methods."""
    base = "custom_components.solaredge_hwc.api.SolarEdgeHWCClient"
    with (
        patch(f"{base}.async_get_state", return_value=dict(STATE)) as get_state,
        patch(f"{base}.async_get_info", return_value=INFO) as get_info,
        patch(f"{base}.async_get_load_devices", return_value=[LOAD_DEVICE]) as get_devices,
        patch(f"{base}.async_set_activation_state", return_value=None) as set_state,
        patch(
            "custom_components.solaredge_hwc.api.OAuthAuth.async_login", return_value=None
        ) as login,
    ):
        yield {
            "get_state": get_state,
            "get_info": get_info,
            "get_devices": get_devices,
            "set_state": set_state,
            "login": login,
        }
