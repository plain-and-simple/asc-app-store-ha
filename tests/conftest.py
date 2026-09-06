"""Shared fixtures for the App Store Connect tests."""

from __future__ import annotations

from collections.abc import Generator
from datetime import date
import gzip
from pathlib import Path
from typing import Any
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.asc_app_store.const import (
    API_BASE,
    CONF_ISSUER_ID,
    CONF_KEY_ID,
    CONF_PRIVATE_KEY,
    CONF_VENDOR_NUMBER,
    DOMAIN,
)
from homeassistant.core import HomeAssistant

FIXTURE_DIR = Path(__file__).parent / "fixtures"

TEST_KEY_ID = "AB12CD34EF"
TEST_ISSUER_ID = "69a6de95-0000-0000-0000-ffffffffffff"
TEST_VENDOR = "93606071"
TEST_TODAY = date(2026, 9, 6)

APP_PLAIN = "1234567890"
APP_LAB = "9876543210"


def load_text(name: str) -> str:
    """Return a fixture file as text."""
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def make_test_pem() -> str:
    """Return a fresh P-256 PKCS#8 PEM, the shape Apple issues as .p8."""
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


TEST_PRIVATE_KEY = make_test_pem()


def gzip_tsv(text: str) -> bytes:
    """Return a sales report the way Apple sends it."""
    return gzip.compress(text.encode("utf-8"))


def apps_payload() -> dict[str, Any]:
    """Two iOS apps, matching the sales-report titles."""
    return {
        "data": [
            {
                "type": "apps",
                "id": APP_PLAIN,
                "attributes": {
                    "name": "Plain and Simple",
                    "bundleId": "app.plainandsimple.ios",
                    "sku": "plain.simple",
                },
            },
            {
                "type": "apps",
                "id": APP_LAB,
                "attributes": {
                    "name": "Studio Lab",
                    "bundleId": "app.plainandsimple.lab",
                    "sku": "studio.lab",
                },
            },
        ]
    }


def versions_payload(version: str, build: str, build_id: str) -> dict[str, Any]:
    """A READY_FOR_SALE iOS version with its build included."""
    return {
        "data": [
            {
                "type": "appStoreVersions",
                "id": f"ver-{build_id}",
                "attributes": {
                    "platform": "IOS",
                    "versionString": version,
                    "appStoreState": "READY_FOR_SALE",
                    "createdDate": "2026-08-01T12:00:00Z",
                },
                "relationships": {
                    "build": {"data": {"type": "builds", "id": build_id}}
                },
            }
        ],
        "included": [
            {
                "type": "builds",
                "id": build_id,
                "attributes": {"version": build, "uploadedDate": "2026-08-01T11:00:00Z"},
            }
        ],
    }


def builds_payload(
    version: str, build: str, build_id: str, uploaded: str
) -> dict[str, Any]:
    """An unexpired TestFlight build with its pre-release version."""
    return {
        "data": [
            {
                "type": "builds",
                "id": build_id,
                "attributes": {
                    "version": build,
                    "uploadedDate": uploaded,
                    "expired": False,
                    "processingState": "VALID",
                },
                "relationships": {
                    "preReleaseVersion": {
                        "data": {"type": "preReleaseVersions", "id": f"pre-{build_id}"}
                    }
                },
            }
        ],
        "included": [
            {
                "type": "preReleaseVersions",
                "id": f"pre-{build_id}",
                "attributes": {"version": version, "platform": "IOS"},
            }
        ],
    }


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Generator[None]:
    """Let Home Assistant load this integration at all."""
    yield


@pytest.fixture
def mock_asc(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Serve apps, versions, TestFlight builds and a couple of sales days.

    More-specific ``/v1/apps/{id}/...`` URLs are registered before
    ``/v1/apps`` because the mocker prefix-matches.
    """
    tsv = load_text("sales_mixed.tsv")
    day_tsv = gzip_tsv(tsv)

    aioclient_mock.get(
        f"{API_BASE}/v1/apps/{APP_PLAIN}/appStoreVersions",
        json=versions_payload("1.2.0", "40", "build-plain-live"),
    )
    aioclient_mock.get(
        f"{API_BASE}/v1/apps/{APP_LAB}/appStoreVersions",
        json=versions_payload("2.0.0", "10", "build-lab-live"),
    )
    aioclient_mock.get(f"{API_BASE}/v1/apps", json=apps_payload())

    # The builds list is one endpoint filtered by app id. Return both apps'
    # TestFlight builds depending on the filter — the mocker prefix-matches
    # the path, so we inspect the request in a fallback: two sequential
    # registrations would collide. A single payload that tests pick apart
    # is wrong; instead the client is called per app and we register the
    # path once with a combined list, then rely on filter[app] matching
    # being ignored. To keep each app distinct, the API client uses the
    # same path with different params — register without params and let
    # tests that need per-app TF data use the combined helper below only
    # when they do not care. For setup we return a TF-ahead build for
    # whichever app is asked; the client picks the max uploadedDate.
    #
    # Practical approach: mock /v1/builds with a payload that includes
    # both, and accept that each app's request returns both builds. The
    # client then picks the newest iOS build in that list — which would
    # assign the same TF to both apps. So we cannot share one payload.
    #
    # We therefore stub async_get_testflight_builds in this fixture's
    # companion patch? No — register nothing generic. Tests that hit the
    # real client will get the last registered /v1/builds mock. The
    # mocker returns the first matching mock. We register none here and
    # instead patch nothing: we add a regex URL that cannot collide.
    #
    # Simplest working approach used below: the coordinator's fetch calls
    # /v1/builds?filter[app]=ID. The mocker includes params in the match
    # when they are provided.
    aioclient_mock.get(
        f"{API_BASE}/v1/builds",
        params={"filter[app]": APP_PLAIN},
        json=builds_payload("1.3.0", "55", "build-plain-tf", "2026-09-01T10:00:00Z"),
    )
    aioclient_mock.get(
        f"{API_BASE}/v1/builds",
        params={"filter[app]": APP_LAB},
        json=builds_payload("2.0.0", "10", "build-lab-tf", "2026-08-02T10:00:00Z"),
    )

    # Two report days so 7d > day. Other lookback dates 404.
    aioclient_mock.get(
        f"{API_BASE}/v1/salesReports",
        params={"filter[reportDate]": "2026-09-05"},
        content=day_tsv,
        headers={"Content-Type": "application/a-gzip"},
    )
    older = tsv.replace("09/05/2026", "09/04/2026")
    # Studio Lab only on the 4th, so per-app 7d differs from day.
    older_lines = [
        line
        for line in older.splitlines()
        if line.startswith("Provider") or "Studio Lab" in line
    ]
    aioclient_mock.get(
        f"{API_BASE}/v1/salesReports",
        params={"filter[reportDate]": "2026-09-04"},
        content=gzip_tsv("\n".join(older_lines) + "\n"),
        headers={"Content-Type": "application/a-gzip"},
    )
    aioclient_mock.get(f"{API_BASE}/v1/salesReports", status=404, json={})

    return aioclient_mock


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Return a config entry as the config flow would have created it."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="App Store Connect",
        unique_id=TEST_VENDOR,
        data={
            CONF_KEY_ID: TEST_KEY_ID,
            CONF_ISSUER_ID: TEST_ISSUER_ID,
            CONF_PRIVATE_KEY: TEST_PRIVATE_KEY,
            CONF_VENDOR_NUMBER: TEST_VENDOR,
        },
    )


@pytest.fixture
async def setup_integration(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_asc: AiohttpClientMocker,
) -> MockConfigEntry:
    """Set up the integration against the ASC fixtures and return its entry."""
    config_entry.add_to_hass(hass)
    with patch(
        "custom_components.asc_app_store.coordinator.date.today",
        return_value=TEST_TODAY,
    ):
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
    return config_entry
