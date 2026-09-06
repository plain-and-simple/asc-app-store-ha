# App Store Connect for Home Assistant

[![HACS: custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![Validate](https://github.com/plain-and-simple/asc-app-store-ha/actions/workflows/validate.yml/badge.svg)](https://github.com/plain-and-simple/asc-app-store-ha/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Put [App Store Connect](https://appstoreconnect.apple.com) App Units and live vs
TestFlight builds into Home Assistant, as real entities you can chart, template
against and automate on.

Paste in an API key and every iOS app in the team arrives with first-time
download totals and a release sensor that compares the live App Store build to
the latest unexpired TestFlight build.

No `configuration.yaml`. No REST templates.

## What you get

Studio-wide:

| Entity ID | What it is |
| --- | --- |
| `sensor.asc_downloads_status` | Whether the last sales-report fetch succeeded. |
| `sensor.asc_downloads_total_day` | First-time App Units for the latest report day. `by_day` holds the lookback. |
| `sensor.asc_downloads_total_7d` | First-time App Units across the trailing seven days. |
| `sensor.asc_app_builds_status` | Whether the last versions / TestFlight fetch succeeded. |

Per app (`{slug}` is the app name, lowercased with underscores):

| Entity ID | What it is |
| --- | --- |
| `sensor.asc_downloads_{slug}_day` | That app's first-time downloads for the latest report day. |
| `sensor.asc_downloads_{slug}_7d` | That app's first-time downloads for the trailing week. |
| `sensor.asc_app_{slug}_release` | Live vs TestFlight. Attributes: `live_version`, `live_build`, `tf_version`, `tf_build`, `tf_ahead_of_live`. |

**App Units only count first-time downloads.** Product type identifiers
`1`, `1F`, `1T`, `F1` and `1-B` are included. Updates (`7`, `7F`, `F7`) are
excluded, so a version bump never looks like a flood of new users.

## Install

### 1. Add the repository to HACS

In Home Assistant, go to **HACS → ⋮ → Custom repositories**, paste

```
https://github.com/plain-and-simple/asc-app-store-ha
```

choose **Integration** as the category, and click **Add**.

### 2. Install and restart

Find **App Store Connect** in HACS, click **Download**, then restart Home
Assistant.

### 3. Create an App Store Connect API key

In App Store Connect, open **Users and Access → Integrations → Keys** and
create a key that can read apps and Sales and Trends (App Manager or Admin).
Download the `.p8` file and note the **Key ID** and **Issuer ID**.

The **vendor number** is under **Agreements, Tax, and Banking**. Enter yours
in the setup form — there is no default. It looks like an 8-digit number
such as `12345678`.

### 4. Add the integration

**Settings → Devices & services → Add integration → App Store Connect**, then
paste the Key ID, Issuer ID, the full `.p8` PEM text, and the vendor number.

The first refresh talks to Apple. A bad key fails setup with a reauth prompt
instead of leaving sensors stuck on unknown.

### 5. Put it on a dashboard

Entity IDs are stable and already match the studio dashboards:

```yaml
type: entities
title: App Store
entities:
  - sensor.asc_downloads_status
  - sensor.asc_downloads_total_day
  - sensor.asc_downloads_total_7d
  - sensor.asc_app_builds_status
```

`sensor.asc_downloads_total_day` carries a `by_day` attribute — a map of
`YYYY-MM-DD` to first-time units — for a custom chart of the lookback window.

## Options

**Settings → Devices & services → App Store Connect → Configure**

- **Update interval** — default 360 minutes (6 hours), minimum 60, maximum
  1440. Daily sales reports only land once a day, so checking more often than
  every few hours rarely shows you anything new.

## About the API

Authentication is an ES256 JWT (`aud`: `appstoreconnect-v1`, about 20 minutes
life) signed with Home Assistant's bundled `cryptography`. There is no PyJWT
dependency and no `requirements` in the manifest.

Sales reports are Apple's **DAILY SUMMARY SALES** files — gzipped TSV — over
a ~10-day lookback. A 404 for a given day is normal; Apple simply has not
published that report yet.

Live iOS version and build come from `appStoreVersions`. The request **never**
sends `sort`: Apple returns `PARAMETER_ERROR.ILLEGAL` if it is present. The
latest unexpired TestFlight build comes from `builds`.

The integration only ever *reads*. Your `.p8` is stored in Home Assistant and
sent only to `api.appstoreconnect.apple.com`. Diagnostics downloads have the
private key and issuer ID redacted.

## Development

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest -q
```

## Reporting a bug

**Settings → Devices & services → App Store Connect → ⋮ → Download
diagnostics** gives you a file with most of what a bug report needs. Read it
before you attach it anywhere — a GitHub issue is public.

**Removed** — the `.p8` private key and the Issuer ID.

**Kept, on purpose** — vendor number, Key ID, app names, download counts and
version numbers. "The number is wrong" is not diagnosable without the numbers.

## Licence

MIT. Not affiliated with or endorsed by Apple.
