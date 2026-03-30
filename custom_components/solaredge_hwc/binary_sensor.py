"""Binary sensor platform for SolarEdge Hot Water Controller."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    HEATING_POWER_THRESHOLD_W,
    STATUS_ONLINE,
    STATUS_CONNECTED,
    ICON_WATER_BOILER,
    ICON_WATER_BOILER_OFF,
    ICON_CHECK_NETWORK,
    ICON_NETWORK_OFF,
)
from .coordinator import SolarEdgeHWCCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SolarEdge HWC binary sensors."""
    coordinator: SolarEdgeHWCCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        [
            HWCHeatingActiveSensor(coordinator, entry),
            HWCDeviceOnlineSensor(coordinator, entry),
        ]
    )


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class SolarEdgeHWCBinarySensorBase(CoordinatorEntity, BinarySensorEntity):
    """Base class for SolarEdge HWC binary sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SolarEdgeHWCCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.device_id)},
            "name": "SolarEdge Hot Water Controller",
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
# Heating active
# ---------------------------------------------------------------------------

class HWCHeatingActiveSensor(SolarEdgeHWCBinarySensorBase):
    """
    Binary sensor: is the hot water controller currently drawing power?

    True  → currently heating (activePowerMeter > threshold)
    False → idle / off
    """

    _attr_translation_key = "heating_active"
    _attr_unique_id = "se_hwc_heating_active"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    @property
    def is_on(self) -> bool:
        """Return True if the controller is actively heating."""
        measurements = self.hwc_data.get("measurements", {})
        power = float(measurements.get("activePowerMeter", 0.0))
        return power > HEATING_POWER_THRESHOLD_W

    @property
    def icon(self) -> str:
        """Show an active or inactive boiler icon."""
        return ICON_WATER_BOILER if self.is_on else ICON_WATER_BOILER_OFF


# ---------------------------------------------------------------------------
# Device online
# ---------------------------------------------------------------------------

class HWCDeviceOnlineSensor(SolarEdgeHWCBinarySensorBase):
    """
    Binary sensor: is the device reachable / online?

    True  → device reports ONLINE or CONNECTED
    False → OFFLINE, DISCONNECTED, or any other status
    """

    _attr_translation_key = "device_online"
    _attr_unique_id = "se_hwc_device_online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self) -> bool:
        """Return True if the device is online."""
        status = self.hwc_data.get("deviceStatus", "")
        return status in (STATUS_ONLINE, STATUS_CONNECTED)

    @property
    def icon(self) -> str:
        """Show the appropriate network icon."""
        return ICON_CHECK_NETWORK if self.is_on else ICON_NETWORK_OFF
