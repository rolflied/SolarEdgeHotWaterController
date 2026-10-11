"""Base entity for SolarEdge Hot Water Controller."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import BASE_URL, DEFAULT_MODEL, DEFAULT_NAME, DOMAIN, MANUFACTURER
from .coordinator import HWCData, SolarEdgeHWCCoordinator


class SolarEdgeHWCEntity(CoordinatorEntity[SolarEdgeHWCCoordinator]):
    """Common base: device info and unique ID."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: SolarEdgeHWCCoordinator, description: EntityDescription
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        # Based on the entry, not the Device ID: replacing the hardware keeps
        # the entities and their history.
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{description.key}"

        info = coordinator.data.device_info if coordinator.data else {}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device_id)},
            # Constant name so entity IDs stay the same across versions
            name=DEFAULT_NAME,
            manufacturer=info.get("manufacturer") or MANUFACTURER,
            model=info.get("model") or DEFAULT_MODEL,
            serial_number=info.get("serialNumber"),
            configuration_url=f"{BASE_URL}/v/s/{coordinator.site_id}/smart-energy/hot-water",
        )

    @property
    def hwc(self) -> HWCData:
        """Return the latest data."""
        return self.coordinator.data
