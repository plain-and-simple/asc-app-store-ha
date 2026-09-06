"""Shared entity bases defining the App Store Connect device tree."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ASC_ANALYTICS_URL, DOMAIN
from .coordinator import AscCoordinator


class AscHubEntity(CoordinatorEntity[AscCoordinator]):
    """An entity describing the whole App Store Connect team.

    ``has_entity_name`` is off so the translated name is the full entity
    name (``ASC Downloads Status``), which slugifies to the dashboard IDs
    already in use.
    """

    _attr_has_entity_name = False

    def __init__(self, coordinator: AscCoordinator, suffix: str, object_id: str) -> None:
        """Attach this entity to the vendor's hub device."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{suffix}"
        self._attr_translation_key = suffix
        self._attr_suggested_object_id = object_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="App Store Connect",
            manufacturer="Apple",
            model="App Store Connect",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=ASC_ANALYTICS_URL,
        )


class AscAppEntity(CoordinatorEntity[AscCoordinator]):
    """An entity describing one app.

    Names are set explicitly (``ASC Downloads {title} Day``) so the
    entity id is ``sensor.asc_downloads_{slug}_day`` even before
    ``suggested_object_id`` is considered.
    """

    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: AscCoordinator,
        slug: str,
        suffix: str,
        object_id: str,
        app_name: str,
    ) -> None:
        """Attach this entity to its app's device, under the hub."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._slug = slug
        self._attr_unique_id = f"{entry.entry_id}_{slug}_{suffix}"
        self._attr_suggested_object_id = object_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{slug}")},
            name=app_name,
            manufacturer="Apple",
            model="iOS app",
            via_device=(DOMAIN, entry.entry_id),
        )
