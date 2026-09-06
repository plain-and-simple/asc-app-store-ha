"""Checks that every user-visible string actually exists."""

from __future__ import annotations

import json
from pathlib import Path
import re

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.asc_app_store.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

COMPONENT_DIR = Path(__file__).parent.parent / "custom_components" / "asc_app_store"
STRINGS_PATH = COMPONENT_DIR / "strings.json"
EN_PATH = COMPONENT_DIR / "translations" / "en.json"
STRINGS = json.loads(STRINGS_PATH.read_text(encoding="utf-8"))


def test_english_translations_are_byte_identical_to_strings() -> None:
    """The two files must not drift apart, even by a trailing newline.

    Home Assistant reads strings.json for the config flow and
    translations/en.json for entities, so a change made in only one place
    is invisible until exactly the wrong moment.
    """
    assert EN_PATH.read_bytes() == STRINGS_PATH.read_bytes()
    assert json.loads(EN_PATH.read_text(encoding="utf-8")) == STRINGS


def test_manifest_agrees_with_the_code() -> None:
    """A domain mismatch stops the integration loading at all."""
    manifest = json.loads((COMPONENT_DIR / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["domain"] == DOMAIN
    assert manifest["config_flow"] is True
    assert manifest["documentation"].endswith("/asc-app-store-ha")
    assert manifest["issue_tracker"].endswith("/asc-app-store-ha/issues")
    assert "requirements" not in manifest
    assert re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"])


def test_every_config_flow_message_exists() -> None:
    """An unlisted error key shows the user the raw key instead of a sentence."""
    source = (COMPONENT_DIR / "config_flow.py").read_text(encoding="utf-8")

    for key in re.findall(r'errors\[[^\]]+\] = "([a-z_]+)"', source):
        assert key in STRINGS["config"]["error"], f"missing config.error.{key}"


def test_translation_keys_are_slugs() -> None:
    """Home Assistant requires [a-z0-9-_]+ and rejects the whole file otherwise."""

    def walk(node: object, path: str) -> None:
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            if path.endswith((".state", "entity.sensor", "entity.button")) or ".options" in path:
                assert re.fullmatch(r"[a-z0-9_-]+", key), f"{path}.{key} is not a slug"
            walk(value, f"{path}.{key}")

    walk(STRINGS, "")


async def test_every_static_entity_has_a_name(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Hub sensors must have a translation; per-app sensors set a name."""
    registry = er.async_get(hass)
    entities = [
        entry
        for entry in registry.entities.values()
        if entry.config_entry_id == setup_integration.entry_id
    ]
    assert entities, "the integration created no entities to check"

    platform_strings = STRINGS["entity"]["sensor"]
    for entry in entities:
        if entry.translation_key:
            assert entry.translation_key in platform_strings, (
                f"missing entity.sensor.{entry.translation_key}.name"
            )
            assert platform_strings[entry.translation_key].get("name")
