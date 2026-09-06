"""Constants for the App Store Connect integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "asc_app_store"

# Config entry data keys.
CONF_KEY_ID: Final = "key_id"
CONF_ISSUER_ID: Final = "issuer_id"
CONF_PRIVATE_KEY: Final = "private_key"
CONF_VENDOR_NUMBER: Final = "vendor_number"

# Options keys.
CONF_SCAN_INTERVAL: Final = "scan_interval"

# Sales reports land a day or two late and are only kept briefly. Ten calendar
# days is enough for a 7-day total plus a couple of missing-report holes
# without hammering Apple on every refresh.
SALES_LOOKBACK_DAYS: Final = 10

DEFAULT_SCAN_INTERVAL_MINUTES: Final = 360
MIN_SCAN_INTERVAL_MINUTES: Final = 60
MAX_SCAN_INTERVAL_MINUTES: Final = 1440

API_BASE: Final = "https://api.appstoreconnect.apple.com"

# First-time App Units (downloads). Updates are a different product type and
# must not land in these sensors — dashboards already treat the numbers as
# new-user downloads.
FIRST_TIME_APP_UNITS: Final = frozenset({"1", "1F", "1T", "F1", "1-B"})
UPDATE_PRODUCT_TYPES: Final = frozenset({"7", "7F", "F7"})

ASC_KEYS_URL: Final = "https://appstoreconnect.apple.com/access/integrations/api"
ASC_ANALYTICS_URL: Final = "https://appstoreconnect.apple.com/analytics"
