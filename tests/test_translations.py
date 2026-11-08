"""Übersetzungen: gleiche Struktur in de/en und für jedes Formularfeld ein Text."""

import json
from pathlib import Path

from custom_components.knx_media_player.config_flow import _options_schema

TRANSLATIONS = Path(__file__).parent.parent / "custom_components" / "knx_media_player" / "translations"


def _flat(data, prefix=""):
    out = set()
    for key, value in data.items():
        out |= _flat(value, f"{prefix}{key}/") if isinstance(value, dict) else {f"{prefix}{key}"}
    return out


def test_same_structure() -> None:
    de = json.loads((TRANSLATIONS / "de.json").read_text(encoding="utf-8"))
    en = json.loads((TRANSLATIONS / "en.json").read_text(encoding="utf-8"))
    assert _flat(de) == _flat(en)


def test_every_field_is_translated() -> None:
    for language in ("de", "en"):
        step = json.loads((TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8"))[
            "options"]["step"]["init"]
        schema = _options_schema({}, [], [])
        for section_key, section_marker in schema.schema.items():
            translated = step["sections"][str(section_key)]
            assert translated["name"]
            for field in section_marker.schema.schema:
                assert str(field) in translated["data"], (language, section_key, field)
