"""Sensors for App Store downloads and live vs TestFlight builds."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import AscConfigEntry, AscCoordinator
from .entity import AscAppEntity, AscHubEntity
from .models import AppDownloads, AppRelease


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AscConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up hub sensors and one set of sensors per app."""
    coordinator = entry.runtime_data

    async_add_entities(
        [
            AscDownloadsStatusSensor(coordinator),
            AscDownloadsTotalSensor(coordinator, "day"),
            AscDownloadsTotalSensor(coordinator, "7d"),
            AscBuildsStatusSensor(coordinator),
        ]
    )

    known_download_slugs: set[str] = set()
    known_release_slugs: set[str] = set()

    @callback
    def _async_add_new_apps() -> None:
        entities: list[SensorEntity] = []
        data = coordinator.data

        if data is not None:
            for slug, app in data.downloads.apps.items():
                if slug in known_download_slugs:
                    continue
                known_download_slugs.add(slug)
                entities.append(AscAppDownloadsSensor(coordinator, app, "day"))
                entities.append(AscAppDownloadsSensor(coordinator, app, "7d"))

            for slug, release in data.builds.apps.items():
                if slug in known_release_slugs:
                    continue
                known_release_slugs.add(slug)
                entities.append(AscAppReleaseSensor(coordinator, release))

        if entities:
            async_add_entities(entities)

    _async_add_new_apps()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_apps))


class AscDownloadsStatusSensor(AscHubEntity, SensorEntity):
    """Health of the last sales-report fetch."""

    _attr_translation_key = "downloads_status"
    _attr_icon = "mdi:cloud-download-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: AscCoordinator) -> None:
        """Initialise the downloads status sensor."""
        super().__init__(coordinator, "downloads_status", "asc_downloads_status")

    @property
    def native_value(self) -> str | None:
        """Return ok or error."""
        if self.coordinator.data is None:
            return None
        return "ok" if self.coordinator.data.downloads.ok else "error"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the last report date and any error text."""
        if (data := self.coordinator.data) is None:
            return None
        return {
            "latest_date": data.downloads.latest_date,
            "error": data.downloads.error,
        }


class AscDownloadsTotalSensor(AscHubEntity, SensorEntity):
    """Studio-wide first-time App Units for the latest day or trailing week."""

    _attr_icon = "mdi:download"
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "downloads"

    def __init__(self, coordinator: AscCoordinator, period: str) -> None:
        """Initialise one studio total."""
        super().__init__(
            coordinator,
            f"downloads_total_{period}",
            f"asc_downloads_total_{period}",
        )
        self._period = period
        self._attr_translation_key = f"downloads_total_{period}"

    @property
    def native_value(self) -> int | None:
        """Return the studio total."""
        if (data := self.coordinator.data) is None or not data.downloads.ok:
            return None
        if self._period == "day":
            return data.downloads.total_day
        return data.downloads.total_7d

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose by_day on the daily sensor for dashboard charts."""
        if self._period != "day" or (data := self.coordinator.data) is None:
            return None
        return {
            "by_day": data.downloads.by_day,
            "latest_date": data.downloads.latest_date,
        }


class AscBuildsStatusSensor(AscHubEntity, SensorEntity):
    """Health of the last App Store versions / TestFlight fetch."""

    _attr_translation_key = "app_builds_status"
    _attr_icon = "mdi:source-branch"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: AscCoordinator) -> None:
        """Initialise the builds status sensor."""
        super().__init__(coordinator, "app_builds_status", "asc_app_builds_status")

    @property
    def native_value(self) -> str | None:
        """Return ok or error."""
        if self.coordinator.data is None:
            return None
        return "ok" if self.coordinator.data.builds.ok else "error"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return any error text."""
        if (data := self.coordinator.data) is None:
            return None
        return {"error": data.builds.error}


class AscAppDownloadsSensor(AscAppEntity, SensorEntity):
    """First-time App Units for one app, for the latest day or trailing week."""

    _attr_icon = "mdi:download"
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "downloads"

    def __init__(
        self, coordinator: AscCoordinator, app: AppDownloads, period: str
    ) -> None:
        """Initialise one per-app download sensor."""
        label = "Day" if period == "day" else "7d"
        super().__init__(
            coordinator,
            app.slug,
            f"downloads_{period}",
            f"asc_downloads_{app.slug}_{period}",
            app.title,
        )
        self._period = period
        self._attr_name = f"ASC Downloads {app.title} {label}"
        self._attr_translation_key = f"downloads_{period}"

    @property
    def _app(self) -> AppDownloads | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.downloads.apps.get(self._slug)

    @property
    def available(self) -> bool:
        """Stay around if a refresh omitted this app — keep its history."""
        return super().available and self._app is not None

    @property
    def native_value(self) -> int | None:
        """Return this app's units for the period."""
        if (app := self._app) is None:
            return None
        return app.units_day if self._period == "day" else app.units_7d

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return identifiers useful on a dashboard card."""
        if (app := self._app) is None:
            return None
        attrs: dict[str, Any] = {
            "apple_identifier": app.apple_identifier,
            "sku": app.sku,
        }
        if self._period == "day":
            attrs["by_day"] = app.by_day
        return attrs


class AscAppReleaseSensor(AscAppEntity, SensorEntity):
    """Live App Store version versus the latest unexpired TestFlight build."""

    _attr_translation_key = "app_release"
    _attr_icon = "mdi:rocket-launch-outline"

    def __init__(self, coordinator: AscCoordinator, release: AppRelease) -> None:
        """Initialise one per-app release sensor."""
        super().__init__(
            coordinator,
            release.slug,
            "release",
            f"asc_app_{release.slug}_release",
            release.name,
        )
        self._attr_name = f"ASC App {release.name} Release"

    @property
    def _release(self) -> AppRelease | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.builds.apps.get(self._slug)

    @property
    def available(self) -> bool:
        """Stay around if a refresh omitted this app — keep its history."""
        return super().available and self._release is not None

    @property
    def native_value(self) -> str | None:
        """Return a short live-vs-TestFlight summary."""
        if (release := self._release) is None:
            return None
        live = _format_version(release.live_version, release.live_build)
        tf_ver = _format_version(release.tf_version, release.tf_build)
        if live and tf_ver:
            return f"{live} / TF {tf_ver}"
        return live or (f"TF {tf_ver}" if tf_ver else None)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the fields dashboards already bind to."""
        if (release := self._release) is None:
            return None
        return {
            "live_version": release.live_version,
            "live_build": release.live_build,
            "tf_version": release.tf_version,
            "tf_build": release.tf_build,
            "tf_ahead_of_live": release.tf_ahead_of_live,
            "bundle_id": release.bundle_id,
        }


def _format_version(version: str | None, build: str | None) -> str | None:
    if version and build:
        return f"{version} ({build})"
    return version or build
