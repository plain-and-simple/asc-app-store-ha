"""Normalised downloads and build snapshots, plus the sales-report parsers.

Everything downstream — coordinator, sensors, diagnostics — reads these
dataclasses and never touches a TSV row or an ASC JSON:API document again.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import re
from typing import Any

from .const import FIRST_TIME_APP_UNITS, SALES_LOOKBACK_DAYS, UPDATE_PRODUCT_TYPES

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify_name(name: str) -> str:
    """Return a stable entity-id slug from an App Store title.

    Dashboards already address sensors as ``sensor.asc_downloads_{slug}_day``
    and ``sensor.asc_app_{slug}_release``, so this must stay boring: lowercase,
    underscores, no punctuation.
    """
    slug = _SLUG_RE.sub("_", name.strip().lower()).strip("_")
    return slug or "app"


def is_first_time_app_unit(product_type: str) -> bool:
    """Return True for a first-time App Units product type.

    Apple's summary sales report mixes first downloads with updates, IAP and
    other rows. Updates (``7``, ``7F``, ``F7``) look like units but are not
    new users — counting them would silently inflate every dashboard.
    """
    identifier = product_type.strip()
    if identifier in UPDATE_PRODUCT_TYPES:
        return False
    return identifier in FIRST_TIME_APP_UNITS


def _optional_cell(cells: list[str], index: dict[str, int], name: str) -> str:
    """Return a trimmed optional column, or empty if the row is short."""
    position = index.get(name)
    if position is None or position >= len(cells):
        return ""
    return cells[position].strip()


def parse_report_date(raw: str) -> date | None:
    """Parse a sales-report Begin Date, which arrives as MM/DD/YYYY."""
    text = raw.strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


@dataclass(frozen=True, slots=True)
class SalesRow:
    """One first-time App Units row after product-type filtering."""

    report_date: date
    title: str
    slug: str
    sku: str
    apple_identifier: str
    units: int
    product_type: str


def parse_sales_tsv(text: str) -> list[SalesRow]:
    """Parse a DAILY SUMMARY SALES TSV and keep first-time App Units only."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return []

    header = [column.strip() for column in lines[0].split("\t")]
    index = {name: position for position, name in enumerate(header)}

    required = ("Product Type Identifier", "Units", "Begin Date", "Title")
    if any(name not in index for name in required):
        return []

    needed = max(index[name] for name in required)

    rows: list[SalesRow] = []
    for line in lines[1:]:
        cells = line.split("\t")
        if len(cells) <= needed:
            continue

        product_type = cells[index["Product Type Identifier"]].strip()
        if not is_first_time_app_unit(product_type):
            continue

        report_date = parse_report_date(cells[index["Begin Date"]])
        if report_date is None:
            continue

        try:
            units = int(float(cells[index["Units"]].strip() or "0"))
        except ValueError:
            continue

        title = cells[index["Title"]].strip()
        sku = _optional_cell(cells, index, "SKU")
        apple_id = _optional_cell(cells, index, "Apple Identifier")
        rows.append(
            SalesRow(
                report_date=report_date,
                title=title,
                slug=slugify_name(title),
                sku=sku,
                apple_identifier=apple_id,
                units=units,
                product_type=product_type,
            )
        )

    return rows


@dataclass(frozen=True, slots=True)
class AppDownloads:
    """Per-app first-time downloads for the latest day and trailing week."""

    slug: str
    title: str
    apple_identifier: str | None
    sku: str | None
    units_day: int
    units_7d: int
    by_day: dict[str, int]


@dataclass(frozen=True, slots=True)
class DownloadsSnapshot:
    """Studio-wide App Units plus the per-app breakdown."""

    ok: bool
    error: str | None
    latest_date: str | None
    total_day: int
    total_7d: int
    by_day: dict[str, int]
    apps: dict[str, AppDownloads] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AppRelease:
    """Live App Store version versus the latest unexpired TestFlight build."""

    slug: str
    name: str
    app_id: str
    bundle_id: str | None
    live_version: str | None
    live_build: str | None
    tf_version: str | None
    tf_build: str | None
    tf_ahead_of_live: bool


@dataclass(frozen=True, slots=True)
class BuildsSnapshot:
    """One release row per app in the App Store Connect team."""

    ok: bool
    error: str | None
    apps: dict[str, AppRelease] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AscData:
    """The one snapshot every entity reads."""

    downloads: DownloadsSnapshot
    builds: BuildsSnapshot


def empty_downloads(error: str | None = None) -> DownloadsSnapshot:
    """Return an empty downloads snapshot, optionally recording why."""
    return DownloadsSnapshot(
        ok=error is None,
        error=error,
        latest_date=None,
        total_day=0,
        total_7d=0,
        by_day={},
        apps={},
    )


def empty_builds(error: str | None = None) -> BuildsSnapshot:
    """Return an empty builds snapshot, optionally recording why."""
    return BuildsSnapshot(ok=error is None, error=error, apps={})


def _iso(day: date) -> str:
    return day.isoformat()


def aggregate_downloads(
    rows: list[SalesRow],
    *,
    latest_date: date | None = None,
) -> DownloadsSnapshot:
    """Roll first-time units into daily totals, 7-day totals, and per-app rows.

    ``by_day`` lives on the daily total sensor so a dashboard can chart the
    week without a separate history helper. Missing days stay absent rather
    than being filled with zeroes — a hole in Apple's reports is not a day
    of zero downloads.
    """
    if not rows and latest_date is None:
        return empty_downloads()

    if latest_date is None:
        latest_date = max(row.report_date for row in rows)

    week_start = latest_date - timedelta(days=6)
    studio_by_day: dict[str, int] = {}
    per_app: dict[str, dict[str, Any]] = {}

    for row in rows:
        day_key = _iso(row.report_date)
        studio_by_day[day_key] = studio_by_day.get(day_key, 0) + row.units

        bucket = per_app.setdefault(
            row.slug,
            {
                "title": row.title,
                "apple_identifier": row.apple_identifier or None,
                "sku": row.sku or None,
                "by_day": {},
            },
        )
        bucket["by_day"][day_key] = bucket["by_day"].get(day_key, 0) + row.units
        if row.apple_identifier:
            bucket["apple_identifier"] = row.apple_identifier
        if row.sku:
            bucket["sku"] = row.sku
        if row.title:
            bucket["title"] = row.title

    latest_key = _iso(latest_date)
    apps = {
        slug: AppDownloads(
            slug=slug,
            title=str(info["title"]),
            apple_identifier=info["apple_identifier"],
            sku=info["sku"],
            units_day=int(info["by_day"].get(latest_key, 0)),
            units_7d=sum(
                units
                for day, units in info["by_day"].items()
                if week_start <= date.fromisoformat(day) <= latest_date
            ),
            by_day=dict(sorted(info["by_day"].items())),
        )
        for slug, info in per_app.items()
    }

    return DownloadsSnapshot(
        ok=True,
        error=None,
        latest_date=latest_key,
        total_day=studio_by_day.get(latest_key, 0),
        total_7d=sum(
            units
            for day, units in studio_by_day.items()
            if week_start <= date.fromisoformat(day) <= latest_date
        ),
        by_day=dict(sorted(studio_by_day.items())),
        apps=apps,
    )


def lookback_dates(today: date, days: int = SALES_LOOKBACK_DAYS) -> list[date]:
    """Return the calendar days to request, newest first."""
    return [today - timedelta(days=offset) for offset in range(days)]


def _version_parts(value: str) -> tuple[int, ...]:
    """Split a marketing version or build number into comparable ints."""
    parts: list[int] = []
    for piece in str(value).split("."):
        digits = "".join(character for character in piece if character.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_tf_ahead_of_live(
    tf_version: str | None,
    tf_build: str | None,
    live_version: str | None,
    live_build: str | None,
) -> bool:
    """Return True when TestFlight is a newer version or a newer build."""
    if not tf_version or not live_version:
        return False

    tf_ver = _version_parts(tf_version)
    live_ver = _version_parts(live_version)
    if tf_ver > live_ver:
        return True
    if tf_ver < live_ver:
        return False

    if not tf_build or not live_build:
        return False
    return _version_parts(tf_build) > _version_parts(live_build)
