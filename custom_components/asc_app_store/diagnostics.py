"""Diagnostics for the App Store Connect integration.

The point of this file is that a user can attach a bug report without
pasting a live .p8 into a public GitHub issue.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_ISSUER_ID, CONF_PRIVATE_KEY
from .coordinator import AscConfigEntry

TO_REDACT_ENTRY = {CONF_PRIVATE_KEY, CONF_ISSUER_ID}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: AscConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT_ENTRY),
            "options": dict(entry.options),
        },
        "last_update_success": coordinator.last_update_success,
        "downloads": None
        if data is None
        else {
            "ok": data.downloads.ok,
            "error": data.downloads.error,
            "latest_date": data.downloads.latest_date,
            "total_day": data.downloads.total_day,
            "total_7d": data.downloads.total_7d,
            "by_day": data.downloads.by_day,
            "apps": [asdict(app) for app in data.downloads.apps.values()],
        },
        "builds": None
        if data is None
        else {
            "ok": data.builds.ok,
            "error": data.builds.error,
            "apps": [asdict(app) for app in data.builds.apps.values()],
        },
    }
