"""Poll App Store Connect and share one snapshot with every entity."""

from __future__ import annotations

from datetime import date, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AscApi, AscApiError, AscAuthError
from .const import (
    CONF_ISSUER_ID,
    CONF_KEY_ID,
    CONF_PRIVATE_KEY,
    CONF_SCAN_INTERVAL,
    CONF_VENDOR_NUMBER,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
)
from .models import AscData, empty_builds, empty_downloads

_LOGGER = logging.getLogger(__name__)

type AscConfigEntry = ConfigEntry["AscCoordinator"]


class AscCoordinator(DataUpdateCoordinator[AscData]):
    """Fetch downloads and builds on one schedule, shared by all entities.

    Without a coordinator each per-app sensor would poll independently,
    turning a handful of apps into dozens of JWT-signed requests against
    Apple's rate limit.
    """

    config_entry: AscConfigEntry

    def __init__(self, hass: HomeAssistant, entry: AscConfigEntry) -> None:
        """Build the client and schedule from the entry's data and options."""
        self.api = AscApi(
            async_get_clientsession(hass),
            key_id=entry.data[CONF_KEY_ID],
            issuer_id=entry.data[CONF_ISSUER_ID],
            private_key=entry.data[CONF_PRIVATE_KEY],
            vendor_number=entry.data[CONF_VENDOR_NUMBER],
        )
        interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES)

        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=interval),
        )

    async def _async_update_data(self) -> AscData:
        """Fetch both sides, translating a bad key into a reauth prompt."""
        downloads = empty_downloads()
        builds = empty_builds()

        try:
            builds = await self.api.async_fetch_builds()
        except AscAuthError as err:
            # Raising this specific error is what makes Home Assistant show
            # the reconfigure prompt. A mistyped .p8 is the usual cause.
            raise ConfigEntryAuthFailed(
                "App Store Connect rejected the API key"
            ) from err
        except AscApiError as err:
            _LOGGER.warning("Could not fetch App Store builds: %s", err)
            builds = empty_builds(str(err))

        try:
            downloads = await self.api.async_fetch_downloads(date.today())
        except AscAuthError as err:
            raise ConfigEntryAuthFailed(
                "App Store Connect rejected the API key"
            ) from err
        except AscApiError as err:
            _LOGGER.warning("Could not fetch App Store sales reports: %s", err)
            downloads = empty_downloads(str(err))

        if not downloads.ok and not builds.ok:
            raise UpdateFailed(
                downloads.error or builds.error or "App Store Connect update failed"
            )

        return AscData(downloads=downloads, builds=builds)
