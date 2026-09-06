"""Tests for entry setup, polling behaviour and recovery."""

from __future__ import annotations

from datetime import timedelta

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.asc_app_store.const import (
    API_BASE,
    CONF_SCAN_INTERVAL,
    DOMAIN,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util


async def test_setup_and_unload(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The integration must come up and go away cleanly."""
    assert setup_integration.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    await hass.async_block_till_done()

    assert setup_integration.state is ConfigEntryState.NOT_LOADED


async def test_setup_retries_when_apple_is_down(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """An outage during a restart should resolve itself, not need a human."""
    aioclient_mock.get(f"{API_BASE}/v1/apps", status=500, text="boom")
    aioclient_mock.get(f"{API_BASE}/v1/salesReports", status=500, text="boom")

    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_a_revoked_key_starts_a_reauth_flow(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_asc: AiohttpClientMocker,
) -> None:
    """Revoking a key should prompt for a new one, not just log errors forever."""
    mock_asc.clear_requests()
    mock_asc.get(f"{API_BASE}/v1/apps", status=401, json={"errors": []})

    await setup_integration.runtime_data.async_refresh()
    await hass.async_block_till_done()

    flows = [
        flow
        for flow in hass.config_entries.flow.async_progress()
        if flow["handler"] == DOMAIN and flow["context"]["source"] == "reauth"
    ]
    assert len(flows) == 1


async def test_first_refresh_auth_failure_is_setup_error(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A bad key on first refresh must fail setup, not leave unknown sensors."""
    aioclient_mock.get(f"{API_BASE}/v1/apps", status=401, json={"errors": []})

    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_the_configured_interval_is_used(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_asc: AiohttpClientMocker,
    freezer,
) -> None:
    """An interval that silently ignores the option would be worse than no option."""
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_SCAN_INTERVAL: 90}
    )
    freezer.move_to("2026-09-06T12:00:00+00:00")
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.runtime_data.update_interval == timedelta(minutes=90)

    calls_before = len(mock_asc.mock_calls)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=91))
    await hass.async_block_till_done()

    assert len(mock_asc.mock_calls) > calls_before


async def test_diagnostics_never_leak_the_private_key(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Diagnostics exist to be pasted into a public issue."""
    from custom_components.asc_app_store.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    result = await async_get_config_entry_diagnostics(hass, setup_integration)
    serialised = str(result)

    assert "BEGIN PRIVATE KEY" not in serialised
    assert result["entry"]["data"]["private_key"] == "**REDACTED**"
    assert result["entry"]["data"]["issuer_id"] == "**REDACTED**"
    assert result["downloads"]["total_day"] == 15
