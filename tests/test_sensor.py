"""Tests for the download and release sensors, including dashboard entity IDs."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.asc_app_store.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er


def _state(hass: HomeAssistant, entity_id: str):
    state = hass.states.get(entity_id)
    assert state is not None, f"missing {entity_id}"
    return state


async def test_required_entity_ids_exist(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Dashboards already address these ids — they must be created exactly."""
    expected = {
        "sensor.asc_downloads_status",
        "sensor.asc_downloads_total_day",
        "sensor.asc_downloads_total_7d",
        "sensor.asc_downloads_plain_and_simple_day",
        "sensor.asc_downloads_plain_and_simple_7d",
        "sensor.asc_downloads_studio_lab_day",
        "sensor.asc_downloads_studio_lab_7d",
        "sensor.asc_app_builds_status",
        "sensor.asc_app_plain_and_simple_release",
        "sensor.asc_app_studio_lab_release",
    }
    present = {state.entity_id for state in hass.states.async_all()}
    missing = expected - present
    assert not missing, f"missing entity ids: {sorted(missing)}"


async def test_download_totals_exclude_updates(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """99 update units in the fixture must not appear on the daily total."""
    daily = _state(hass, "sensor.asc_downloads_total_day")
    assert daily.state == "15"
    assert daily.attributes["by_day"]["2026-09-05"] == 15

    weekly = _state(hass, "sensor.asc_downloads_total_7d")
    assert int(weekly.state) > 15

    plain = _state(hass, "sensor.asc_downloads_plain_and_simple_day")
    assert plain.state == "7"


async def test_status_sensors_are_ok(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """A successful first refresh should say so on both status sensors."""
    assert _state(hass, "sensor.asc_downloads_status").state == "ok"
    assert _state(hass, "sensor.asc_app_builds_status").state == "ok"


async def test_release_sensor_exposes_live_and_testflight(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The attributes dashboards bind to must be present and typed."""
    state = _state(hass, "sensor.asc_app_plain_and_simple_release")
    assert state.attributes["live_version"] == "1.2.0"
    assert state.attributes["live_build"] == "40"
    assert state.attributes["tf_version"] == "1.3.0"
    assert state.attributes["tf_build"] == "55"
    assert state.attributes["tf_ahead_of_live"] is True

    lab = _state(hass, "sensor.asc_app_studio_lab_release")
    assert lab.attributes["live_version"] == "2.0.0"
    assert lab.attributes["tf_version"] == "2.0.0"
    assert lab.attributes["tf_ahead_of_live"] is False


async def test_apps_are_grouped_under_a_hub_device(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Grouping is the whole reason for a device per app rather than a flat list."""
    devices = dr.async_get(hass)
    entry_id = setup_integration.entry_id

    hub = devices.async_get_device(identifiers={(DOMAIN, entry_id)})
    assert hub is not None
    assert hub.name == "App Store Connect"

    app_device = devices.async_get_device(
        identifiers={(DOMAIN, f"{entry_id}_plain_and_simple")}
    )
    assert app_device is not None
    assert app_device.name == "Plain and Simple"
    assert app_device.via_device_id == hub.id


async def test_unique_ids_are_stable(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Renaming an entity in the UI must not lose it on the next restart."""
    registry = er.async_get(hass)
    entry_id = setup_integration.entry_id

    assert (
        registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry_id}_downloads_status"
        )
        == "sensor.asc_downloads_status"
    )
    assert (
        registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry_id}_plain_and_simple_release"
        )
        == "sensor.asc_app_plain_and_simple_release"
    )
