"""Tests for the App Store Connect client."""

from __future__ import annotations

from datetime import date

import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.asc_app_store.api import (
    AscApi,
    AscApiError,
    AscAuthError,
)
from custom_components.asc_app_store.const import API_BASE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .conftest import (
    APP_PLAIN,
    TEST_ISSUER_ID,
    TEST_KEY_ID,
    TEST_PRIVATE_KEY,
    TEST_TODAY,
    TEST_VENDOR,
    gzip_tsv,
    load_text,
)


def _api(hass: HomeAssistant, vendor: str = TEST_VENDOR) -> AscApi:
    """Build a client on Home Assistant's shared session."""
    return AscApi(
        async_get_clientsession(hass),
        key_id=TEST_KEY_ID,
        issuer_id=TEST_ISSUER_ID,
        private_key=TEST_PRIVATE_KEY,
        vendor_number=vendor,
    )


async def test_sales_report_is_gunzipped(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Apple sends application/a-gzip; callers get TSV text."""
    tsv = load_text("sales_mixed.tsv")
    aioclient_mock.get(
        f"{API_BASE}/v1/salesReports",
        content=gzip_tsv(tsv),
        headers={"Content-Type": "application/a-gzip"},
    )

    text = await _api(hass).async_get_sales_report(date(2026, 9, 5))
    assert text is not None
    assert "Product Type Identifier" in text
    assert "Plain and Simple" in text


async def test_missing_sales_report_is_none(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 404 is the usual answer for today, not a failure."""
    aioclient_mock.get(f"{API_BASE}/v1/salesReports", status=404, json={})
    assert await _api(hass).async_get_sales_report(TEST_TODAY) is None


async def test_rejected_jwt_is_auth_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """401 must not be reported as 'cannot reach Apple'."""
    aioclient_mock.get(f"{API_BASE}/v1/apps", status=401, json={"errors": []})

    with pytest.raises(AscAuthError):
        await _api(hass).async_list_apps()


async def test_app_store_versions_never_sends_sort(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Apple returns PARAMETER_ERROR.ILLEGAL if ``sort`` is present."""
    aioclient_mock.get(
        f"{API_BASE}/v1/apps/{APP_PLAIN}/appStoreVersions",
        json={"data": [], "included": []},
    )

    await _api(hass).async_get_app_store_versions(APP_PLAIN)

    _method, url, kwargs = aioclient_mock.mock_calls[0]
    params = kwargs.get("params") or {}
    assert "sort" not in params
    assert "sort" not in str(url)


async def test_fetch_downloads_aggregates_lookback(
    hass: HomeAssistant, mock_asc: AiohttpClientMocker
) -> None:
    """Two report days become a daily total and a larger 7-day total."""
    snapshot = await _api(hass).async_fetch_downloads(TEST_TODAY)

    assert snapshot.ok
    # 5+2 Plain, 4+1 Lab, 1 bundle, 2 Mac on the 5th.
    assert snapshot.total_day == 15
    assert snapshot.total_7d > snapshot.total_day
    assert "plain_and_simple" in snapshot.apps
    assert snapshot.apps["plain_and_simple"].units_day == 7


async def test_server_error_on_sales_is_api_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 500 is not a missing report."""
    aioclient_mock.get(f"{API_BASE}/v1/salesReports", status=500, text="boom")

    with pytest.raises(AscApiError) as err:
        await _api(hass).async_get_sales_report(TEST_TODAY)

    assert err.value.status == 500
