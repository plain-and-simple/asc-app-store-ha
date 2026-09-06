"""Async client for the App Store Connect API.

Two quirks matter more than the rest:

* Sales reports are gzipped TSVs, not JSON, and a 404 for a given day is
  normal — Apple simply has not published that report yet.
* ``GET /v1/apps/{id}/appStoreVersions`` rejects ``sort`` with
  ``PARAMETER_ERROR.ILLEGAL``. Newest-live is chosen in Python.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
import gzip
import json
import logging
import time
from typing import Any
from urllib.parse import urlencode

import aiohttp

from .const import API_BASE
from .jwt import JWT_LIFETIME_SECONDS, JwtError, create_asc_jwt
from .models import (
    AppRelease,
    BuildsSnapshot,
    DownloadsSnapshot,
    SalesRow,
    aggregate_downloads,
    empty_builds,
    empty_downloads,
    is_tf_ahead_of_live,
    lookback_dates,
    parse_sales_tsv,
    slugify_name,
)

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=45)
# Refresh a minute before Apple would reject the token, so a long sales
# lookback never dies mid-loop on an expired JWT.
TOKEN_REFRESH_SKEW_SECONDS = 60


class AscError(Exception):
    """Base error for every failure this client reports."""


class AscAuthError(AscError):
    """Apple rejected the JWT — the key, issuer or .p8 is wrong."""


class AscApiError(AscError):
    """Apple was reachable but the request did not succeed."""

    def __init__(self, message: str, status: int | None = None) -> None:
        """Keep the HTTP status so callers can tell 404 from a real failure."""
        super().__init__(message)
        self.status = status


class AscApi:
    """Talk to App Store Connect with a cached ES256 JWT."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        key_id: str,
        issuer_id: str,
        private_key: str,
        vendor_number: str,
    ) -> None:
        """Store credentials. The session belongs to Home Assistant."""
        self._session = session
        self._key_id = key_id
        self._issuer_id = issuer_id
        self._private_key = private_key
        self.vendor_number = vendor_number
        self._token: str | None = None
        self._token_issued_at: int = 0

    def _token_for(self, now: int | None = None) -> str:
        """Return a cached JWT, or mint a new one if it is about to expire."""
        moment = int(time.time() if now is None else now)
        still_valid = (
            self._token is not None
            and moment < self._token_issued_at + JWT_LIFETIME_SECONDS - TOKEN_REFRESH_SKEW_SECONDS
        )
        if still_valid and self._token is not None:
            return self._token

        try:
            self._token = create_asc_jwt(
                key_id=self._key_id,
                issuer_id=self._issuer_id,
                private_key_pem=self._private_key,
                now=moment,
            )
        except JwtError as err:
            raise AscAuthError(str(err)) from err

        self._token_issued_at = moment
        return self._token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token_for()}",
            "Accept": "application/json",
        }

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        accept: str = "application/json",
    ) -> tuple[int, bytes, str]:
        """Make one request and return status, raw body, and content type."""
        headers = {**self._headers(), "Accept": accept}

        try:
            async with self._session.request(
                method,
                url,
                params=params,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            ) as response:
                body = await response.read()
                content_type = response.headers.get("Content-Type", "")
                if response.status in (401, 403):
                    raise AscAuthError(
                        f"App Store Connect rejected the API key ({response.status})"
                    )
                return response.status, body, content_type
        except TimeoutError as err:
            raise AscApiError(f"Timed out talking to App Store Connect at {url}") from err
        except aiohttp.ClientError as err:
            raise AscApiError(f"Could not reach App Store Connect at {url}: {err}") from err

    async def _get_json(
        self, path: str, params: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """GET a JSON:API path and raise on anything unusable."""
        url = path if path.startswith("http") else f"{API_BASE}{path}"
        status, body, _content_type = await self._request("GET", url, params=params)

        if status >= 400:
            raise AscApiError(
                f"App Store Connect returned {status} for {path}: {_error_text(body)}",
                status=status,
            )

        try:
            payload = json.loads(body.decode() or "{}")
        except (ValueError, UnicodeDecodeError) as err:
            raise AscApiError(
                f"App Store Connect returned a non-JSON body for {path}",
                status=status,
            ) from err

        if not isinstance(payload, dict):
            raise AscApiError(
                f"App Store Connect returned an unexpected body for {path}",
                status=status,
            )
        return payload

    async def _get_pages(
        self, path: str, params: dict[str, str] | None = None
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Follow ``links.next`` and return every data/included resource."""
        data: list[dict[str, Any]] = []
        included: list[dict[str, Any]] = []
        url = f"{API_BASE}{path}"
        query = params

        while url:
            body = await self._get_json(url, query)
            data.extend(item for item in body.get("data") or [] if isinstance(item, dict))
            included.extend(
                item for item in body.get("included") or [] if isinstance(item, dict)
            )
            next_url = (body.get("links") or {}).get("next")
            url = next_url if isinstance(next_url, str) and next_url else ""
            query = None

        return data, included

    async def async_list_apps(self) -> list[dict[str, Any]]:
        """Return the team's apps. Used as the credential probe."""
        data, _included = await self._get_pages(
            "/v1/apps",
            {
                "fields[apps]": "name,bundleId,sku",
                "limit": "200",
            },
        )
        return data

    async def async_get_sales_report(self, report_date: date) -> str | None:
        """Download one DAILY SUMMARY SALES TSV, or None when Apple has none.

        A 404 is the usual answer for today, weekends, and the far end of the
        lookback — it is not a failure.
        """
        params = {
            "filter[frequency]": "DAILY",
            "filter[reportType]": "SALES",
            "filter[reportSubType]": "SUMMARY",
            "filter[vendorNumber]": self.vendor_number,
            "filter[reportDate]": report_date.isoformat(),
            "filter[version]": "1_0",
        }
        url = f"{API_BASE}/v1/salesReports"
        status, body, content_type = await self._request(
            "GET",
            url,
            params=params,
            accept="application/a-gzip",
        )

        if status == 404:
            return None

        if status >= 400:
            raise AscApiError(
                f"App Store Connect returned {status} for salesReports"
                f" ({report_date}): {_error_text(body)}",
                status=status,
            )

        return _decode_sales_body(body, content_type)

    async def async_get_app_store_versions(
        self, app_id: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Return iOS App Store versions. Never sends ``sort``."""
        # Apple answers PARAMETER_ERROR.ILLEGAL if `sort` is present, even
        # with a documented value. Filter and pick READY_FOR_SALE ourselves.
        return await self._get_pages(
            f"/v1/apps/{app_id}/appStoreVersions",
            {
                "filter[platform]": "IOS",
                "filter[appStoreState]": "READY_FOR_SALE",
                "include": "build",
                "limit": "50",
            },
        )

    async def async_get_testflight_builds(
        self, app_id: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Return unexpired TestFlight builds for one app."""
        return await self._get_pages(
            "/v1/builds",
            {
                "filter[app]": app_id,
                "filter[expired]": "false",
                "include": "preReleaseVersion",
                "limit": "50",
            },
        )

    async def async_fetch_downloads(self, today: date) -> DownloadsSnapshot:
        """Pull the lookback window and aggregate first-time App Units."""
        rows: list[SalesRow] = []
        latest: date | None = None

        for report_date in lookback_dates(today):
            try:
                text = await self.async_get_sales_report(report_date)
            except AscAuthError:
                raise
            except AscApiError as err:
                _LOGGER.warning(
                    "Sales report for %s failed: %s", report_date, err
                )
                continue

            if text is None:
                continue

            # Trust the requested report date: Apple's TSV Begin Date matches
            # the filter, but a mock or a delayed file should not shift units
            # onto a different calendar day than the one we asked for.
            parsed = [
                replace(row, report_date=report_date) for row in parse_sales_tsv(text)
            ]
            rows.extend(parsed)
            if latest is None or report_date > latest:
                latest = report_date

        if latest is None and not rows:
            return empty_downloads(
                "No daily sales reports in the lookback window"
            )

        return aggregate_downloads(rows, latest_date=latest)

    async def async_fetch_builds(self) -> BuildsSnapshot:
        """Return live vs TestFlight for every app in the team."""
        apps = await self.async_list_apps()
        releases: dict[str, AppRelease] = {}
        used_slugs: set[str] = set()

        for app in apps:
            app_id = str(app.get("id") or "")
            attributes = app.get("attributes") or {}
            name = str(attributes.get("name") or app_id or "App")
            slug = _unique_slug(slugify_name(name), used_slugs)
            used_slugs.add(slug)

            live_version, live_build = await self._live_ios(app_id)
            tf_version, tf_build = await self._latest_testflight(app_id)

            releases[slug] = AppRelease(
                slug=slug,
                name=name,
                app_id=app_id,
                bundle_id=attributes.get("bundleId"),
                live_version=live_version,
                live_build=live_build,
                tf_version=tf_version,
                tf_build=tf_build,
                tf_ahead_of_live=is_tf_ahead_of_live(
                    tf_version, tf_build, live_version, live_build
                ),
            )

        return BuildsSnapshot(ok=True, error=None, apps=releases)

    async def _live_ios(self, app_id: str) -> tuple[str | None, str | None]:
        """Return the live iOS marketing version and its build number."""
        versions, included = await self.async_get_app_store_versions(app_id)
        if not versions:
            return None, None

        # No server-side sort: pick the newest createdDate among READY_FOR_SALE.
        chosen = max(versions, key=_created_date)
        attributes = chosen.get("attributes") or {}
        live_version = attributes.get("versionString")
        build_ref = ((chosen.get("relationships") or {}).get("build") or {}).get(
            "data"
        )
        live_build = None
        if isinstance(build_ref, dict):
            live_build = _included_attribute(included, "builds", build_ref.get("id"), "version")
        return (
            str(live_version) if live_version else None,
            str(live_build) if live_build else None,
        )

    async def _latest_testflight(self, app_id: str) -> tuple[str | None, str | None]:
        """Return the newest unexpired TestFlight marketing version and build."""
        builds, included = await self.async_get_testflight_builds(app_id)
        if not builds:
            return None, None

        ios_builds = [
            build
            for build in builds
            if _build_platform(build, included) in (None, "IOS")
        ]
        candidates = ios_builds or builds
        chosen = max(candidates, key=_uploaded_date)
        attributes = chosen.get("attributes") or {}
        tf_build = attributes.get("version")
        pre_ref = (
            (chosen.get("relationships") or {}).get("preReleaseVersion") or {}
        ).get("data")
        tf_version = None
        if isinstance(pre_ref, dict):
            tf_version = _included_attribute(
                included, "preReleaseVersions", pre_ref.get("id"), "version"
            )
        return (
            str(tf_version) if tf_version else None,
            str(tf_build) if tf_build else None,
        )


def _decode_sales_body(body: bytes, content_type: str) -> str:
    """Gunzip a sales report, or accept a body that is already text."""
    if not body:
        return ""

    if body[:2] == b"\x1f\x8b" or "gzip" in content_type:
        try:
            return gzip.decompress(body).decode("utf-8")
        except (OSError, UnicodeDecodeError) as err:
            raise AscApiError(f"Could not decompress sales report: {err}") from err

    try:
        return body.decode("utf-8")
    except UnicodeDecodeError as err:
        raise AscApiError(f"Sales report was not UTF-8: {err}") from err


def _error_text(body: bytes) -> str:
    """Pull the most useful message out of Apple's JSON:API error list."""
    if not body:
        return "no details provided"
    try:
        payload = json.loads(body.decode())
    except (ValueError, UnicodeDecodeError):
        return "no details provided"

    if not isinstance(payload, dict):
        return "no details provided"

    errors = payload.get("errors")
    if isinstance(errors, list):
        details = []
        for item in errors:
            if not isinstance(item, dict):
                continue
            code = item.get("code")
            detail = item.get("detail") or item.get("title")
            if code and detail:
                details.append(f"{code}: {detail}")
            elif detail:
                details.append(str(detail))
        if details:
            return "; ".join(details)

    return "no details provided"


def _created_date(resource: dict[str, Any]) -> str:
    return str((resource.get("attributes") or {}).get("createdDate") or "")


def _uploaded_date(resource: dict[str, Any]) -> str:
    return str((resource.get("attributes") or {}).get("uploadedDate") or "")


def _included_attribute(
    included: list[dict[str, Any]],
    resource_type: str,
    resource_id: Any,
    attribute: str,
) -> Any:
    for item in included:
        if item.get("type") == resource_type and item.get("id") == resource_id:
            return (item.get("attributes") or {}).get(attribute)
    return None


def _build_platform(
    build: dict[str, Any], included: list[dict[str, Any]]
) -> str | None:
    pre_ref = ((build.get("relationships") or {}).get("preReleaseVersion") or {}).get(
        "data"
    )
    if not isinstance(pre_ref, dict):
        return None
    platform = _included_attribute(
        included, "preReleaseVersions", pre_ref.get("id"), "platform"
    )
    return str(platform) if platform else None


def _unique_slug(slug: str, used: set[str]) -> str:
    if slug not in used:
        return slug
    suffix = 2
    while f"{slug}_{suffix}" in used:
        suffix += 1
    return f"{slug}_{suffix}"


def sales_report_url(vendor_number: str, report_date: date) -> str:
    """Return the salesReports URL for a vendor and day (useful in tests)."""
    query = urlencode(
        {
            "filter[frequency]": "DAILY",
            "filter[reportType]": "SALES",
            "filter[reportSubType]": "SUMMARY",
            "filter[vendorNumber]": vendor_number,
            "filter[reportDate]": report_date.isoformat(),
            "filter[version]": "1_0",
        }
    )
    return f"{API_BASE}/v1/salesReports?{query}"
