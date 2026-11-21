"""Hilfen zum gewählten Media Player: Typ (Sonos, Music Assistant) und Bereich."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
import time
from typing import Any

from homeassistant.components import media_source
from homeassistant.components.media_player import DATA_COMPONENT
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import IntegrationNotFound, async_get_integration

from .const import (
    CONF_START_MEDIA,
    CONF_START_MEDIA_TYPE,
    CONF_START_SOURCE,
    CONF_MEDIA_URIS,
    CONF_START_STATION,
    DOMAIN,
    SCENE_COUNT,
    scene_key,
)
from .stations import STATIONS

_LOGGER = logging.getLogger(__name__)

KIND_SONOS = "sonos"
KIND_MUSIC_ASSISTANT = "music_assistant"

# Felder für „Quelle“ (z. B. Sonos-Favorit) und „Medium“ (z. B. Music-Assistant-Playlist)
SOURCE_KEYS = [
    CONF_START_SOURCE,
    *(scene_key(n, "source") for n in range(1, SCENE_COUNT + 1)),
]
MEDIA_KEYS = [
    CONF_MEDIA_URIS,
    CONF_START_MEDIA,
    CONF_START_MEDIA_TYPE,
    *(scene_key(n, field) for n in range(1, SCENE_COUNT + 1) for field in ("media", "media_type")),
]


def player_kind(hass: HomeAssistant, entity_id: str) -> str | None:
    """`sonos` oder `music_assistant`, wenn die Entität von dieser Integration stammt, sonst None."""
    entry = er.async_get(hass).async_get(entity_id)
    if entry is not None and entry.platform in (KIND_SONOS, KIND_MUSIC_ASSISTANT):
        return entry.platform
    return None


def player_area_name(hass: HomeAssistant, entity_id: str) -> str | None:
    """Name des Bereichs der Entität, ersatzweise ihres Geräts (None, wenn keiner gesetzt ist)."""
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None:
        return None
    area_id = entry.area_id
    if area_id is None and entry.device_id:
        device = dr.async_get(hass).async_get(entry.device_id)
        area_id = device.area_id if device else None
    if area_id is None:
        return None
    area = ar.async_get(hass).async_get_area(area_id)
    return area.name if area else None


def drop_unused_fields(options: dict, kind: str | None) -> dict:
    """Entfernt Felder, die zum Player-Typ nicht passen (Sonos: Medium, Music Assistant: Quelle)."""
    unused = MEDIA_KEYS if kind == KIND_SONOS else SOURCE_KEYS if kind == KIND_MUSIC_ASSISTANT else []
    return {key: value for key, value in options.items() if key not in unused}


# Bibliothek des Music-Assistant-Players: (Kennung für den Medienbrowser, Vorsatz deutsch, englisch)
LIBRARIES = [
    ("playlists", "Playlist", "Playlist"),
    ("radio", "Radiosender", "Radio station"),
]
LIBRARY_BROWSE_TYPE = "music_assistant"
LIBRARY_TIMEOUT = 10  # Sekunden für beide Abfragen zusammen


async def _async_browse(hass: HomeAssistant, entity_id: str, content_type: str, content_id: str):
    """Medienbrowser des Players (wie der Medienbrowser von Home Assistant); None, wenn es ihn nicht gibt."""
    component = hass.data.get(DATA_COMPONENT)
    player = component.get_entity(entity_id) if component else None
    if player is None:
        return None
    return await player.async_browse_media(content_type, content_id)


async def async_library_options(hass: HomeAssistant, entity_id: str) -> list[dict[str, Any]]:
    """Playlists und Radiosender der Music-Assistant-Bibliothek: [{value: Adresse, prefix, title}].

    Aus den Rohdaten macht `make_choices` die Auswahl (Titel als Wert, Adresse dahinter).
    Bei jedem Fehler, Zeitüberschreitung oder fehlendem Player ist die Liste leer; der Dialog
    fällt dann auf freie Eingabe zurück."""
    german = (hass.config.language or "").startswith("de")
    options: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        async with asyncio.timeout(LIBRARY_TIMEOUT):
            for content_id, de, en in LIBRARIES:
                listing = await _async_browse(hass, entity_id, LIBRARY_BROWSE_TYPE, content_id)
                for item in (listing.children or []) if listing else []:
                    uri = item.media_content_id
                    if not uri or not item.can_play or uri in seen:
                        continue
                    seen.add(uri)
                    options.append(
                        {"value": uri, "prefix": de if german else en, "title": item.title}
                    )
    except Exception:  # noqa: BLE001 - Lesefehler dürfen den Dialog nie verhindern
        _LOGGER.debug("Bibliothek von %s nicht lesbar", entity_id, exc_info=True)
        return []
    return options


async def player_integration_name(hass: HomeAssistant, entity_id: str) -> str | None:
    """Anzeigename der Integration, die den Media Player bereitstellt (z. B. „Sonos“, „Music Assistant“)."""
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None or not entry.platform:
        return None
    try:
        return (await async_get_integration(hass, entry.platform)).name
    except IntegrationNotFound:
        return entry.platform


async def describe_player(hass: HomeAssistant, entity_id: str) -> str:
    """Kopf der Dialoge als Liste mit Vorsätzen (Name, Integration, Bereich, Entität)."""
    german = (hass.config.language or "").startswith("de")
    state = hass.states.get(entity_id)
    lines = [f"- **Name:** {state.name if state else entity_id}"]
    if integration := await player_integration_name(hass, entity_id):
        lines.append(f"- **Integration:** {integration}")
    if area := player_area_name(hass, entity_id):
        lines.append(f"- **{'Bereich' if german else 'Area'}:** {area}")
    if state:
        lines.append(f"- **{'Entität' if german else 'Entity'}:** {entity_id}")
    return "\n".join(lines)


# --- Senderliste: feste Sender und Radio Browser ------------------------------------------

RADIO_BROWSER = "radio_browser"
RADIO_BROWSER_TIMEOUT = 10  # Sekunden für beide Abfragen zusammen
RADIO_BROWSER_TTL = 3600  # Sekunden, die eine Abfrage im Speicher bleibt
_RADIO_BROWSER_CACHE = f"{DOMAIN}_radio_browser"


@dataclass
class Choices:
    """Auswahl für ein Feld mit Anzeigenamen als Wert.

    `options`: Auswahlliste (Wert = eindeutiger Titel, Beschriftung mit Vorsatz),
    `uris`: Titel -> Adresse, `labels`: Wert (Titel und Adresse) -> Beschriftung."""

    options: list[dict[str, Any]] = field(default_factory=list)
    uris: dict[str, str] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)


def make_choices(
    entries: list[dict[str, Any]], reserved: set[str] | frozenset[str] = frozenset()
) -> Choices:
    """Rohdaten [{value: Adresse, prefix, title}] in eine Auswahl umwandeln.

    Der Titel ist der gespeicherte Wert, damit das Feld nach der Auswahl den Anzeigenamen zeigt.
    Gleiche Titel (auch mit `reserved`) bekommen eine Nummer: „Radio XY“, „Radio XY (2)“."""
    choices = Choices()
    used = set(reserved)
    for entry in entries:
        title = base = entry["title"]
        number = 2
        while title in used:
            title = f"{base} ({number})"
            number += 1
        used.add(title)
        label = f"{entry['prefix']} · {title}"
        choices.options.append({"value": title, "label": label})
        choices.uris[title] = entry["value"]
        choices.labels[title] = label
        choices.labels.setdefault(entry["value"], label)  # ältere Einstellungen mit Adresse
    return choices


def chosen_uris(
    flat: dict[str, Any], keys: list[str], current: dict[str, str], stored: dict[str, str]
) -> dict[str, str]:
    """Zuordnung Titel -> Adresse für die gewählten Werte: aus der aktuellen Liste, sonst die gespeicherte."""
    result: dict[str, str] = {}
    for key in keys:
        value = flat.get(key)
        if not value:
            continue
        if value in current:
            result[value] = current[value]
        elif value in stored:
            result[value] = stored[value]
    return result


def fixed_station_choices(hass: HomeAssistant) -> Choices:
    """Feste Sender: gespeichert wird der Name, angezeigt „Radiosender · Name“ (Adresse siehe `STATIONS`)."""
    prefix = "Radiosender" if (hass.config.language or "").startswith("de") else "Radio station"
    choices = Choices()
    for name in STATIONS:
        label = f"{prefix} · {name}"
        choices.options.append({"value": name, "label": label})
        choices.labels[name] = label
    return choices


def _radio_browser_loaded(hass: HomeAssistant) -> bool:
    """Ist die Integration Radio Browser eingerichtet und geladen?"""
    return any(
        entry.state is ConfigEntryState.LOADED
        for entry in hass.config_entries.async_entries(RADIO_BROWSER)
    )


async def async_radio_browser_options(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Sender der Integration Radio Browser: lokale (bis 100 km) und beliebte (Top 250).

    Rohdaten [{value: `media-source://radio_browser/…`, prefix, title}]. Nur lesend; die Antwort bleibt
    eine Stunde im Speicher. Ohne die Integration, bei Fehlern oder Zeitüberschreitung ist die Liste leer."""
    if not _radio_browser_loaded(hass):
        return []
    cached = hass.data.get(_RADIO_BROWSER_CACHE)
    if cached and time.monotonic() - cached[0] < RADIO_BROWSER_TTL:
        return cached[1]
    german = (hass.config.language or "").startswith("de")
    options: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        async with asyncio.timeout(RADIO_BROWSER_TIMEOUT):
            for identifier, de, en in (("local", "Lokal", "Local"), ("popular", "Beliebt", "Popular")):
                listing = await media_source.async_browse_media(
                    hass, f"media-source://{RADIO_BROWSER}/{identifier}"
                )
                for item in listing.children or []:
                    uri = item.media_content_id
                    if not uri or not item.can_play or uri in seen:
                        continue
                    seen.add(uri)
                    options.append(
                        {"value": uri, "prefix": f"Radio Browser · {de if german else en}", "title": item.title}
                    )
    except Exception:  # noqa: BLE001 - Lesefehler dürfen den Dialog nie verhindern
        _LOGGER.debug("Radio Browser nicht lesbar", exc_info=True)
        return []
    hass.data[_RADIO_BROWSER_CACHE] = (time.monotonic(), options)
    return options


async def async_station_choices(hass: HomeAssistant) -> Choices:
    """Auswahl „Sender“: feste Sender, dann Radio Browser (falls vorhanden).

    Titel aus Radio Browser, die einem festen Sender oder einander gleichen, bekommen eine Nummer."""
    fixed = fixed_station_choices(hass)
    radio = make_choices(await async_radio_browser_options(hass), reserved=set(STATIONS))
    return Choices(
        options=[*fixed.options, *radio.options],
        uris=radio.uris,
        labels={**radio.labels, **fixed.labels},
    )
