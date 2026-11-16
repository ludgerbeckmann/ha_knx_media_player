"""Hilfen zum gewählten Media Player: Typ (Sonos, Music Assistant) und Bereich."""

from __future__ import annotations

import asyncio
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
    """Playlists und Radiosender der Music-Assistant-Bibliothek als Auswahl: [{value, label}].

    Die Adresse (z. B. `library://playlist/399`) wird gespeichert, der Titel angezeigt.
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
                    options.append({"value": uri, "label": f"{de if german else en} · {item.title}"})
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
    """Kurzbeschreibung für Dialoge: „Büro · Music Assistant · Bereich Arbeitszimmer · media_player.buero“."""
    german = (hass.config.language or "").startswith("de")
    state = hass.states.get(entity_id)
    parts = [state.name if state else entity_id]
    if integration := await player_integration_name(hass, entity_id):
        parts.append(integration)
    if area := player_area_name(hass, entity_id):
        parts.append(f"{'Bereich' if german else 'Area'} {area}")
    if state:
        parts.append(entity_id)
    return " · ".join(parts)


# --- Senderliste: feste Sender und Radio Browser ------------------------------------------

RADIO_BROWSER = "radio_browser"
RADIO_BROWSER_TIMEOUT = 10  # Sekunden für beide Abfragen zusammen
RADIO_BROWSER_TTL = 3600  # Sekunden, die eine Abfrage im Speicher bleibt
_RADIO_BROWSER_CACHE = f"{DOMAIN}_radio_browser"


def fixed_station_options(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Feste Sender: gespeichert wird der Name, angezeigt „Radiosender · Name“."""
    prefix = "Radiosender" if (hass.config.language or "").startswith("de") else "Radio station"
    return [{"value": name, "label": f"{prefix} · {name}"} for name in STATIONS]


def _radio_browser_loaded(hass: HomeAssistant) -> bool:
    """Ist die Integration Radio Browser eingerichtet und geladen?"""
    return any(
        entry.state is ConfigEntryState.LOADED
        for entry in hass.config_entries.async_entries(RADIO_BROWSER)
    )


async def async_radio_browser_options(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Sender der Integration Radio Browser: lokale (bis 100 km) und beliebte (Top 250).

    Gespeichert wird die `media-source://radio_browser/…`-Adresse. Nur lesend; die Antwort bleibt
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
                        {"value": uri, "label": f"Radio Browser · {de if german else en} · {item.title}"}
                    )
    except Exception:  # noqa: BLE001 - Lesefehler dürfen den Dialog nie verhindern
        _LOGGER.debug("Radio Browser nicht lesbar", exc_info=True)
        return []
    hass.data[_RADIO_BROWSER_CACHE] = (time.monotonic(), options)
    return options


async def async_station_options(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Auswahl „Sender“: feste Sender, dann Radio Browser (falls vorhanden)."""
    return [*fixed_station_options(hass), *await async_radio_browser_options(hass)]


def selected_media_summary(
    hass: HomeAssistant, settings: dict[str, Any], options: list[dict[str, Any]]
) -> str:
    """Zeile „Wiedergabeoption: Radiosender · WDR 4 · Szene 1: Playlist · …“ mit den gewählten Titeln.

    `options` übersetzt gespeicherte Werte (Name, Adresse) in den angezeigten Titel; unbekannte
    Werte (z. B. frei eingegeben) erscheinen unverändert."""
    german = (hass.config.language or "").startswith("de")
    labels = {item["value"]: item["label"] for item in options}
    parts: list[str] = []
    places = [
        (
            "Wiedergabeoption" if german else "Playback option",
            CONF_START_STATION, CONF_START_SOURCE, CONF_START_MEDIA,
        )
    ]
    places += [
        (
            f"{'Szene' if german else 'Scene'} {n}",
            scene_key(n, "station"), scene_key(n, "source"), scene_key(n, "media"),
        )
        for n in range(1, SCENE_COUNT + 1)
    ]
    for place, station_key, source_key, media_key in places:
        # Vorrang wie beim Abspielen: Sender, dann Quelle (zeigt das Feld selbst an), dann Medium
        value = settings.get(station_key) or (
            None if settings.get(source_key) else settings.get(media_key)
        )
        if value:
            parts.append(f"{place}: {labels.get(value, value)}")
    return " · ".join(parts) if parts else ("noch nichts gewählt" if german else "nothing selected yet")
