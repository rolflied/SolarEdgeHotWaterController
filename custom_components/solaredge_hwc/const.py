"""Constants for the SolarEdge Hot Water Controller integration."""

DOMAIN = "solaredge_hwc"
PLATFORMS = ["sensor", "binary_sensor"]

# Configuration keys
CONF_SITE_ID = "site_id"
CONF_DEVICE_ID = "device_id"
CONF_COOKIE = "cookie"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_TIMEOUT = "timeout"

# Default values
DEFAULT_SCAN_INTERVAL = 60
DEFAULT_TIMEOUT = 30
DEFAULT_NAME = "SolarEdge Hot Water Controller"

# Title used for newly created config entries
ENTRY_TITLE_FORMAT = "SolarEdge HWC (Site {site_id})"

# API
API_BASE_URL = "https://monitoring.solaredge.com"
API_HWC_ENDPOINT = "/services/m/so/load-device/site/{site_id}/device/{device_id}/state"

# Activation modes
MODE_MANUAL = "MANUAL"
MODE_AUTO = "AUTO"
MODE_SMART_ENERGY = "SMART_ENERGY"
MODE_SCHEDULE = "SCHEDULE"

# Device status values
STATUS_ONLINE = "ONLINE"
STATUS_OFFLINE = "OFFLINE"
STATUS_ERROR = "ERROR"
STATUS_CONNECTED = "CONNECTED"
STATUS_DISCONNECTED = "DISCONNECTED"

# Power threshold (W) above which heating is considered active
HEATING_POWER_THRESHOLD_W = 10.0

# Icons
ICON_WATER_BOILER = "mdi:water-boiler"
ICON_WATER_BOILER_OFF = "mdi:water-boiler-off"
ICON_WATER_BOILER_AUTO = "mdi:water-boiler-auto"
ICON_GAUGE = "mdi:gauge"
ICON_GAUGE_EMPTY = "mdi:gauge-empty"
ICON_LIGHTNING = "mdi:lightning-bolt"
ICON_LIGHTNING_OFF = "mdi:lightning-bolt-outline"
ICON_HAND = "mdi:hand-back-left"
ICON_ROBOT = "mdi:robot"
ICON_SOLAR_POWER = "mdi:solar-power"
ICON_CHECK_NETWORK = "mdi:check-network"
ICON_NETWORK_OFF = "mdi:network-off"
ICON_THERMOMETER = "mdi:thermometer"
ICON_FLASH = "mdi:flash"
ICON_FLASH_OFF = "mdi:flash-off"

# Error message keys (used internally in config flow)
ERROR_AUTH_FAILED = "invalid_auth"
ERROR_CANNOT_CONNECT = "cannot_connect"
ERROR_INVALID_RESPONSE = "invalid_response"
ERROR_UNKNOWN = "unknown"
ERROR_ALREADY_CONFIGURED = "already_configured"
