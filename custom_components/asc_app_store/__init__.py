"""The App Store Connect integration."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .coordinator import AscConfigEntry, AscCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: AscConfigEntry) -> bool:
    """Set up App Store Connect from a config entry."""
    coordinator = AscCoordinator(hass, entry)

    # Fail setup loudly if the very first fetch does not work, so the user
    # sees the problem immediately rather than a set of entities stuck at
    # unknown. A bad key raises ConfigEntryAuthFailed from the coordinator.
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: AscConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: AscConfigEntry) -> None:
    """Reload when options change, so a new interval takes effect at once."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    entry: AscConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Allow deleting the device for an app App Store Connect no longer returns."""
    coordinator = entry.runtime_data
    prefix = f"{entry.entry_id}_"
    data = coordinator.data
    live_slugs = set()
    if data is not None:
        live_slugs.update(data.downloads.apps)
        live_slugs.update(data.builds.apps)

    for domain, identifier in device_entry.identifiers:
        if domain != DOMAIN:
            continue
        if identifier == entry.entry_id:
            return False
        if identifier.startswith(prefix):
            slug = identifier.removeprefix(prefix)
            if slug in live_slugs:
                return False

    return True
