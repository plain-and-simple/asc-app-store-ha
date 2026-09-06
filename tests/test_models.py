"""Tests for product-type filtering and download aggregation.

These run without Home Assistant because the arithmetic they protect — first-time
App Units versus updates — is the thing dashboards already treat as new users.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from custom_components.asc_app_store.models import (
    SalesRow,
    aggregate_downloads,
    is_first_time_app_unit,
    is_tf_ahead_of_live,
    parse_sales_tsv,
    slugify_name,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sales_mixed.tsv"


def test_first_time_product_types_are_kept() -> None:
    """These identifiers are first-time App Units in Apple's sales report."""
    for identifier in ("1", "1F", "1T", "F1", "1-B"):
        assert is_first_time_app_unit(identifier), identifier


def test_updates_and_iap_are_not_app_units() -> None:
    """A version bump or an IAP must never land in the download sensors."""
    for identifier in ("7", "7F", "F7", "IA1", "IA9", "FI1"):
        assert not is_first_time_app_unit(identifier), identifier


def test_parse_sales_tsv_drops_updates() -> None:
    """The mixed fixture has 99+12+3 update units that must vanish."""
    rows = parse_sales_tsv(FIXTURE.read_text(encoding="utf-8"))
    types = {row.product_type for row in rows}
    assert types <= {"1", "1F", "1T", "F1", "1-B"}
    assert "7" not in types
    assert sum(row.units for row in rows) == 5 + 2 + 4 + 1 + 1 + 2


def test_aggregation_sums_the_day_and_the_week() -> None:
    """Country rows collapse, updates stay out, 7d is the trailing week."""
    rows = [
        SalesRow(
            report_date=date(2026, 9, 5),
            title="Plain and Simple",
            slug="plain_and_simple",
            sku="plain.simple",
            apple_identifier="123",
            units=7,
            product_type="1",
        ),
        SalesRow(
            report_date=date(2026, 9, 4),
            title="Plain and Simple",
            slug="plain_and_simple",
            sku="plain.simple",
            apple_identifier="123",
            units=3,
            product_type="1",
        ),
        SalesRow(
            report_date=date(2026, 8, 20),
            title="Plain and Simple",
            slug="plain_and_simple",
            sku="plain.simple",
            apple_identifier="123",
            units=100,
            product_type="1",
        ),
        SalesRow(
            report_date=date(2026, 9, 5),
            title="Studio Lab",
            slug="studio_lab",
            sku="studio.lab",
            apple_identifier="987",
            units=4,
            product_type="1F",
        ),
    ]

    snapshot = aggregate_downloads(rows, latest_date=date(2026, 9, 5))

    assert snapshot.total_day == 11
    # 7 + 3 + 4; the 20 August row is outside the trailing week.
    assert snapshot.total_7d == 14
    assert snapshot.by_day == {"2026-08-20": 100, "2026-09-04": 3, "2026-09-05": 11}
    assert snapshot.apps["plain_and_simple"].units_day == 7
    assert snapshot.apps["plain_and_simple"].units_7d == 10
    assert snapshot.apps["studio_lab"].units_day == 4
    assert snapshot.apps["studio_lab"].units_7d == 4


def test_slugify_matches_dashboard_entity_ids() -> None:
    """Entity ids are built from this slug; it has to stay boring."""
    assert slugify_name("Plain and Simple") == "plain_and_simple"
    assert slugify_name("Studio Lab") == "studio_lab"


def test_tf_ahead_compares_version_then_build() -> None:
    """A newer TestFlight is the whole reason the release sensor exists."""
    assert is_tf_ahead_of_live("1.3.0", "1", "1.2.0", "40")
    assert is_tf_ahead_of_live("1.2.0", "41", "1.2.0", "40")
    assert not is_tf_ahead_of_live("1.2.0", "40", "1.2.0", "40")
    assert not is_tf_ahead_of_live("1.1.0", "99", "1.2.0", "40")
    assert not is_tf_ahead_of_live(None, "1", "1.2.0", "40")
