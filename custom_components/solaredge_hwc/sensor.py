"""Sensor platform for SolarEdge Hot Water Controller."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfEnergy,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    HEATING_POWER_THRESHOLD_W,
    MODE_MANUAL,
    MODE_SMART_ENERGY,
    STATUS_ONLINE,
    STATUS_CONNECTED,
    ICON_LIGHTNING,
    ICON_LIGHTNING_OFF,
    ICON_GAUGE,
    ICON_GAUGE_EMPTY,
    ICON_HAND,
    ICON_ROBOT,
    ICON_SOLAR_POWER,
    ICON_CHECK_NETWORK,
    ICON_NETWORK_OFF,
    ICON_FLASH,
)
from .coordinator import SolarEdgeHWCCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SolarEdge HWC sensors from a config entry."""
    coordinator: SolarEdgeHWCCoordinator = hass.data[DOMAIN][entry.entry_id]

    sensors: list[SensorEntity] = [
        HWCPowerSensor(coordinator, entry),
        HWCLevelSensor(coordinator, entry),
        HWCActivationModeSensor(coordinator, entry),
        HWCDeviceStatusSensor(coordinator, entry),
    ]

    # Add energy sensor only if the API returns total energy data
    # (will return unavailable if field is missing, which is fine)
    sensors.append(HWCTotalEnergySensor(coordinator, entry))

    async_add_entities(sensors)


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class SolarEdgeHWCSensorBase(CoordinatorEntity, SensorEntity):
    """Base class for all SolarEdge HWC sensors."""

    def __init__(
        self,
        coordinator: SolarEdgeHWCCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.device_id)},
            "name": "SolarEdge Warmwasser-Controller",
            "manufacturer": "SolarEdge",
            "model": "Home Hot Water Controller",
            "configuration_url": (
                f"https://monitoring.solaredge.com/v/s/"
                f"{coordinator.site_id}/smart-energy/hot-water"
            ),
        }

    @property
    def hwc_data(self) -> dict[str, Any]:
        """Return coordinator data, or empty dict if unavailable."""
        return self.coordinator.data if self.coordinator.data else {}


# ---------------------------------------------------------------------------
# Power sensor  (Leistung)
# ---------------------------------------------------------------------------

class HWCPowerSensor(SolarEdgeHWCSensorBase):
    """Current electrical power consumption of the hot water controller."""

    _attr_name = "SolarEdge HWC Leistung"
    _attr_unique_id = "se_hwc_power_active"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    @property
    def native_value(self) -> float:
        """Return active power in watts, or 0 if the API reports no value.

        The SolarEdge API omits activePowerMeter when power is zero,
        so a missing value is treated as 0 W rather than unknown.
        """
        measurements = self.hwc_data.get("measurements") or {}
        raw = measurements.get("activePowerMeter")
        if raw is None:
            return 0.0
        return round(float(raw), 2)

    @property
    def icon(self) -> str:
        """Use filled bolt when actively consuming power."""
        value = self.native_value
        if value and value > HEATING_POWER_THRESHOLD_W:
            return ICON_LIGHTNING
        return ICON_LIGHTNING_OFF

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """
        Expose all remaining measurement fields as attributes.
        This makes additional API fields (reactive power, voltage, current, etc.)
        visible even before dedicated sensors are created for them.
        """
        measurements = self.hwc_data.get("measurements", {})
        return {
            key: value
            for key, value in measurements.items()
            if key != "activePowerMeter"
        }


# ---------------------------------------------------------------------------
# Level sensor  (Füllstand / Heizstufe)
# ---------------------------------------------------------------------------

class HWCLevelSensor(SolarEdgeHWCSensorBase):
    """Heating level percentage (how much of the target temperature is reached)."""

    _attr_name = "SolarEdge HWC Heizstufe"
    _attr_unique_id = "se_hwc_level_percent"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    @property
    def native_value(self) -> int | None:
        """Return the heating level as a percentage."""
        level = self.hwc_data.get("percentageLevel")
        if level is None:
            return None
        return int(level)

    @property
    def icon(self) -> str:
        """Show a full or empty gauge depending on level."""
        level = self.native_value
        if level is not None and level > 5:
            return ICON_GAUGE
        return ICON_GAUGE_EMPTY


# ---------------------------------------------------------------------------
# Activation mode sensor  (Aktivierungsmodus)
# ---------------------------------------------------------------------------

class HWCActivationModeSensor(SolarEdgeHWCSensorBase):
    """Current activation / operating mode of the controller."""

    _attr_name = "SolarEdge HWC Aktivierungsmodus"
    _attr_unique_id = "se_hwc_activation_mode"

    # Human-readable German translations for known mode values
    _MODE_LABELS: dict[str, str] = {
        "MANUAL": "Manuell",
        "AUTO": "Automatisch",
        "SMART_ENERGY": "Smart Energy",
        "SCHEDULE": "Zeitplan",
        "OFF": "Aus",
    }

    @property
    def native_value(self) -> str | None:
        """Return the activation mode in a readable form."""
        mode = self.hwc_data.get("activationMode")
        if mode is None:
            return None
        return self._MODE_LABELS.get(mode, mode.replace("_", " ").title())

    @property
    def icon(self) -> str:
        """Return icon matching the current mode."""
        mode = self.hwc_data.get("activationMode", "")
        if mode == "MANUAL":
            return ICON_HAND
        if mode == "SMART_ENERGY":
            return ICON_SOLAR_POWER
        # AUTO / SCHEDULE
        return ICON_ROBOT

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the raw API value so automations can compare against it."""
        return {"raw_mode": self.hwc_data.get("activationMode", "")}


# ---------------------------------------------------------------------------
# Device status sensor  (Gerätestatus)
# ---------------------------------------------------------------------------

class HWCDeviceStatusSensor(SolarEdgeHWCSensorBase):
    """
    Device / connection status reported by the SolarEdge cloud.

    Also exposes all additional, unmapped API fields as attributes so
    that users can inspect the full API response in the entity panel.
    """

    _attr_name = "SolarEdge HWC Gerätestatus"
    _attr_unique_id = "se_hwc_device_status"

    _STATUS_LABELS: dict[str, str] = {
        "ONLINE": "Online",
        "OFFLINE": "Offline",
        "ERROR": "Fehler",
        "CONNECTED": "Verbunden",
        "DISCONNECTED": "Getrennt",
        "COMMUNICATION_ERROR": "Kommunikationsfehler",
    }

    @property
    def native_value(self) -> str | None:
        """Return the device status in a readable form."""
        status = self.hwc_data.get("deviceStatus")
        if status is None:
            return None
        return self._STATUS_LABELS.get(status, status.replace("_", " ").title())

    @property
    def icon(self) -> str:
        """Use a network-check icon when online, network-off when not."""
        status = self.hwc_data.get("deviceStatus", "")
        if status in (STATUS_ONLINE, STATUS_CONNECTED):
            return ICON_CHECK_NETWORK
        return ICON_NETWORK_OFF

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """
        Expose every remaining top-level API field as an attribute.
        This covers any fields the API returns that do not have a
        dedicated sensor, making them available for use in templates
        and automations without any code changes.
        """
        known_keys = {
            "measurements",
            "percentageLevel",
            "activationMode",
            "deviceStatus",
        }
        attrs: dict[str, Any] = {
            "raw_status": self.hwc_data.get("deviceStatus", ""),
        }
        for key, value in self.hwc_data.items():
            if key not in known_keys:
                attrs[key] = value
        return attrs


# ---------------------------------------------------------------------------
# Total energy sensor  (Gesamtenergie – für Langzeitstatistiken / Energiedashboard)
# ---------------------------------------------------------------------------

class HWCTotalEnergySensor(SolarEdgeHWCSensorBase):
    """
    Total accumulated energy consumed by the hot water controller.

    Uses SensorStateClass.TOTAL_INCREASING so Home Assistant can track
    long-term statistics and display the data in the Energy Dashboard.

    This sensor is only meaningful if the API returns
    measurements.totalActiveEnergyMeter (or a similarly named field).
    It will show as "unavailable" if the field is absent.
    """

    _attr_name = "SolarEdge HWC Gesamtenergie"
    _attr_unique_id = "se_hwc_total_energy"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = ICON_FLASH
    _attr_suggested_display_precision = 0

    # Possible field names for the energy counter in the API response
    _ENERGY_FIELD_CANDIDATES = (
        "totalActiveEnergyMeter",
        "totalEnergy",
        "energyTotal",
        "consumedEnergy",
    )

    @property
    def native_value(self) -> float | None:
        """Return the total energy in Wh, or None if unavailable."""
        measurements = self.hwc_data.get("measurements", {})
        for field in self._ENERGY_FIELD_CANDIDATES:
            value = measurements.get(field)
            if value is not None:
                return round(float(value), 1)
        return None
