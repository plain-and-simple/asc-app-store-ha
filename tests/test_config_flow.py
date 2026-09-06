"""Tests for adding, re-authenticating and configuring the integration."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.asc_app_store.const import (
    API_BASE,
    CONF_ISSUER_ID,
    CONF_KEY_ID,
    CONF_PRIVATE_KEY,
    CONF_SCAN_INTERVAL,
    CONF_VENDOR_NUMBER,
    DOMAIN,
)
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import (
    TEST_ISSUER_ID,
    TEST_KEY_ID,
    TEST_PRIVATE_KEY,
    TEST_VENDOR,
    apps_payload,
)


def _user_input(**overrides: str) -> dict[str, str]:
    data = {
        CONF_KEY_ID: TEST_KEY_ID,
        CONF_ISSUER_ID: TEST_ISSUER_ID,
        CONF_PRIVATE_KEY: TEST_PRIVATE_KEY,
        CONF_VENDOR_NUMBER: TEST_VENDOR,
    }
    data.update(overrides)
    return data


async def _start(hass: HomeAssistant) -> str:
    """Open the user flow and return its id."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    return result["flow_id"]


async def test_a_valid_key_creates_the_entry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The happy path: paste a key, get App Store Connect."""
    aioclient_mock.get(f"{API_BASE}/v1/apps", json=apps_payload())

    result = await hass.config_entries.flow.async_configure(
        await _start(hass), _user_input()
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "App Store Connect"
    assert result["data"][CONF_VENDOR_NUMBER] == TEST_VENDOR
    assert result["data"][CONF_KEY_ID] == TEST_KEY_ID


async def test_a_bad_key_says_so_and_lets_the_user_retry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A mistyped key is caught while the real .p8 is still on the clipboard."""
    aioclient_mock.get(f"{API_BASE}/v1/apps", status=401, json={"errors": []})
    flow_id = await _start(hass)

    result = await hass.config_entries.flow.async_configure(flow_id, _user_input())

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API_BASE}/v1/apps", json=apps_payload())

    result = await hass.config_entries.flow.async_configure(flow_id, _user_input())
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_garbage_pem_is_invalid_key(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Do not even call Apple if the paste is not a PEM."""
    result = await hass.config_entries.flow.async_configure(
        await _start(hass), _user_input(**{CONF_PRIVATE_KEY: "nope"})
    )

    assert result["errors"] == {CONF_PRIVATE_KEY: "invalid_key"}
    assert aioclient_mock.call_count == 0


async def test_an_unreachable_api_is_not_reported_as_a_bad_key(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Sending someone to regenerate a working key wastes their afternoon."""
    aioclient_mock.get(f"{API_BASE}/v1/apps", status=500, text="boom")

    result = await hass.config_entries.flow.async_configure(
        await _start(hass), _user_input()
    )

    assert result["errors"] == {"base": "cannot_connect"}


async def test_the_same_vendor_cannot_be_added_twice(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Two entries for one vendor would double every download total."""
    config_entry.add_to_hass(hass)
    aioclient_mock.get(f"{API_BASE}/v1/apps", json=apps_payload())

    result = await hass.config_entries.flow.async_configure(
        await _start(hass), _user_input()
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_swaps_the_key_and_keeps_the_entry(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Rotating a key must not cost the user their recorded history."""
    config_entry.add_to_hass(hass)
    aioclient_mock.get(f"{API_BASE}/v1/apps", json=apps_payload())
    result = await config_entry.start_reauth_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_KEY_ID: "NEWKEYID01",
            CONF_ISSUER_ID: TEST_ISSUER_ID,
            CONF_PRIVATE_KEY: TEST_PRIVATE_KEY,
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_KEY_ID] == "NEWKEYID01"


async def test_options_are_saved(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Changing the interval should stick, and as an int rather than a float."""
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SCAN_INTERVAL: 120},
    )
    await hass.async_block_till_done()

    assert result["data"][CONF_SCAN_INTERVAL] == 120
    assert isinstance(result["data"][CONF_SCAN_INTERVAL], int)
