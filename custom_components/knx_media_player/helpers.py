"""Hilfen zum gewählten Media Player: Typ (Sonos, Music Assistant) und Bereich."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.media_player import DATA_COMPONENT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_START_MEDIA,
    CONF_START_MEDIA_TYPE,
    CONF_START_SOURCE,
    SCENE_COUNT,
    scene_key,
)

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
