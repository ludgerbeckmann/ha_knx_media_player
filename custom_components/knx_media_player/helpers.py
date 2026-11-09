"""Hilfen zum gewählten Media Player: Typ (Sonos, Music Assistant) und Bereich."""

from __future__ import annotations

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
