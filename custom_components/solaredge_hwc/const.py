"""Constants for the SolarEdge Hot Water Controller integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "solaredge_hwc"
PLATFORMS: Final = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.WATER_HEATER,
]

# ---------------------------------------------------------------------------
# Configuration keys
# ---------------------------------------------------------------------------
CONF_AUTH_TYPE: Final = "auth_type"
CONF_SITE_ID: Final = "site_id"
CONF_DEVICE_ID: Final = "device_id"
CONF_COOKIE: Final = "cookie"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_TIMEOUT: Final = "timeout"
CONF_SWITCH_OFF_MODE: Final = "switch_off_mode"
CONF_TEMPERATURE_SENSOR: Final = "temperature_sensor"
CONF_HYSTERESIS: Final = "hysteresis"
CONF_EVCC: Final = "evcc"
CONF_EVCC_MODE_ENTITY: Final = "evcc_mode_entity"

AUTH_CREDENTIALS: Final = "credentials"
AUTH_COOKIE: Final = "cookie"

# What the "Manual heating" switch does when it is turned off
SWITCH_OFF_AUTO: Final = "auto"
SWITCH_OFF_OFF: Final = "off"

DEFAULT_SCAN_INTERVAL: Final = 60
DEFAULT_TIMEOUT: Final = 30
DEFAULT_SWITCH_OFF_MODE: Final = SWITCH_OFF_AUTO
MIN_SCAN_INTERVAL: Final = 30
MAX_SCAN_INTERVAL: Final = 600
MIN_TIMEOUT: Final = 10
MAX_TIMEOUT: Final = 120

DEFAULT_NAME: Final = "SolarEdge Hot Water Controller"
DEFAULT_MODEL: Final = "Home Hot Water Controller"
MANUFACTURER: Final = "SolarEdge"

# Title used for newly created config entries
ENTRY_TITLE_FORMAT: Final = "SolarEdge HWC (Site {site_id})"

# The static device info (model, rated power, schedules) changes rarely
INFO_REFRESH_INTERVAL: Final = timedelta(minutes=15)
# Delay before re-reading the state after a command, so the cloud has caught up
POST_COMMAND_REFRESH_DELAY: Final = 5

# ---------------------------------------------------------------------------
# SolarEdge monitoring portal (unofficial, reverse engineered)
# ---------------------------------------------------------------------------
BASE_URL: Final = "https://monitoring.solaredge.com"
LOGIN_BASE_URL: Final = "https://login.solaredge.com"
OAUTH_CLIENT_ID: Final = "ugfnsujd3384sshcjehaphlh3"
OAUTH_CALLBACK_URL: Final = f"{BASE_URL}/mfe/auth/callback"
OAUTH_TOKEN_URL: Final = f"{LOGIN_BASE_URL}/oauth2/token"

PATH_DEVICE_STATE: Final = "/services/m/so/load-device/site/{site_id}/device/{device_id}/state"
PATH_DEVICE_INFO: Final = "/services/m/so/load-device/site/{site_id}/device/{device_id}/info"
PATH_DEVICES_LIST_INFO: Final = "/services/m/so/devices-list/site/{site_id}/info"
PATH_ACTIVATION_STATE: Final = (
    "/services/m/api/homeautomation/v1.0/{site_id}/devices/{device_id}/activationState"
)

USER_AGENT: Final = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Activation modes as used by the API
API_MODE_AUTO: Final = "AUTO"
API_MODE_MANUAL: Final = "MANUAL"
API_MODE_SCHEDULE: Final = "SCHEDULE"

# Operating modes offered to the user (select entity and actions)
OPERATION_AUTO: Final = "auto"
OPERATION_ON: Final = "on"
OPERATION_OFF: Final = "off"
OPERATION_SCHEDULE: Final = "schedule"
OPERATION_MODES: Final = [OPERATION_AUTO, OPERATION_ON, OPERATION_OFF, OPERATION_SCHEDULE]

# Status values that mean "the controller talks to the cloud"
ONLINE_STATUSES: Final = frozenset({"ACTIVE", "ONLINE", "CONNECTED"})

# Power threshold (W) above which heating is considered active
HEATING_POWER_THRESHOLD_W: Final = 10.0

# Boost / manual heating defaults
DEFAULT_BOOST_DURATION_MIN: Final = 60
DEFAULT_MANUAL_LEVEL: Final = 100
MAX_BOOST_DURATION_MIN: Final = 1440

# Temperature limit (°C / K)
DEFAULT_TARGET_TEMPERATURE: Final = 60.0
MIN_TARGET_TEMPERATURE: Final = 30.0
MAX_TARGET_TEMPERATURE: Final = 85.0
DEFAULT_HYSTERESIS: Final = 5.0
MIN_HYSTERESIS: Final = 1.0
MAX_HYSTERESIS: Final = 20.0

# Power readings further apart than this are not integrated into energy
MAX_ENERGY_INTEGRATION_GAP: Final = timedelta(minutes=15)

# Actions
SERVICE_SET_OPERATION_MODE: Final = "set_operation_mode"
SERVICE_BOOST: Final = "boost"
ATTR_MODE: Final = "mode"
ATTR_LEVEL: Final = "level"
ATTR_DURATION: Final = "duration"

# ---------------------------------------------------------------------------
# evcc
# ---------------------------------------------------------------------------
# Loadpoint modes as reported by evcc (and the ha-evcc select entity).
# "pv" and "minpv" are the names used before evcc 0.315.
EVCC_MODE_OFF: Final = "off"
EVCC_MODE_SMART: Final = "smart"
EVCC_MODE_NOW: Final = "now"
EVCC_MODE_PV: Final = "pv"
EVCC_MODE_MINPV: Final = "minpv"
EVCC_MODE_OPERATIONS: Final = {
    EVCC_MODE_OFF: OPERATION_OFF,
    EVCC_MODE_SMART: OPERATION_AUTO,
    EVCC_MODE_PV: OPERATION_AUTO,
    EVCC_MODE_MINPV: OPERATION_AUTO,
    EVCC_MODE_NOW: OPERATION_ON,
}
# Level used for the evcc mode "now"
EVCC_ON_LEVEL: Final = 100
# "On" runs for a limited time and is renewed while evcc still wants it, so
# the controller falls back on its own if evcc or Home Assistant goes away
EVCC_ON_DURATION: Final = timedelta(minutes=15)
EVCC_RENEW_INTERVAL: Final = timedelta(minutes=10)
# Commands sent on behalf of evcc are at least this far apart
EVCC_MIN_COMMAND_INTERVAL: Final = timedelta(seconds=60)
# A repair issue appears once the evcc mode has been unavailable this long
EVCC_UNAVAILABLE_ISSUE_DELAY: Final = timedelta(minutes=10)
# Range of the placeholder current entity required by evcc
EVCC_MAX_CURRENT: Final = 32

# Keys and fixed object IDs of the entities evcc reads and writes
EVCC_STATUS_KEY: Final = "evcc_status"
EVCC_ENABLE_KEY: Final = "evcc_enable"
EVCC_CURRENT_KEY: Final = "evcc_current"
# Status values evcc understands without extra configuration
EVCC_STATUS_CONNECTED: Final = "connected"
EVCC_STATUS_CHARGING: Final = "charging"
