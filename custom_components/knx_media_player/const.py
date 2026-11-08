"""Konstanten der Integration "KNX Media Player"."""

from __future__ import annotations

DOMAIN = "knx_media_player"

# --- Eintrag (ein Eintrag je Media Player) ---
CONF_NAME = "name"
CONF_PLAYER = "player"
CONF_MAX_VOLUME = "max_volume"
CONF_VOLUME_STEP = "volume_step"
CONF_STOP_INSTEAD = "stop_instead_of_pause"
CONF_START_VOLUME = "start_volume"
CONF_START_SOURCE = "start_source"
CONF_IDLE_TEXT = "idle_text"

DEFAULT_MAX_VOLUME = 100
DEFAULT_VOLUME_STEP = 5

# --- Gruppenadressen: Befehle (KNX -> Media Player) ---
CONF_ADDR_PLAY_PAUSE = "addr_play_pause"      # 1 Bit: 1 = Wiedergabe, 0 = Pause
CONF_ADDR_NEXT_PREV = "addr_next_prev"        # 1 Bit: 1 = nächster, 0 = vorheriger Titel
CONF_ADDR_STOP = "addr_stop"                  # 1 Bit: 1 = Stopp
CONF_ADDR_TOGGLE = "addr_toggle"              # 1 Bit: 1 = Wiedergabe/Pause umschalten
CONF_ADDR_VOLUME = "addr_volume"              # 5.001: Lautstärke absolut
CONF_ADDR_VOLUME_STEP = "addr_volume_step"    # 1 Bit: 1 = lauter, 0 = leiser (ein Schritt)
CONF_ADDR_VOLUME_DIM = "addr_volume_dim"      # 3.007: relatives Dimmen
CONF_ADDR_MUTE = "addr_mute"                  # 1 Bit: folgt dem Wert
CONF_ADDR_SCENE = "addr_scene"                # 17.001: Szenennummer
SCENE_COUNT = 5

# --- Gruppenadressen: Rückmeldungen (Media Player -> KNX) ---
CONF_STATUS_PLAYING = "status_playing"
CONF_STATUS_PAUSED = "status_paused"
CONF_STATUS_VOLUME = "status_volume"
CONF_STATUS_MUTED = "status_muted"
CONF_STATUS_TITLE = "status_title"
CONF_STATUS_ARTIST = "status_artist"
CONF_STATUS_ALBUM = "status_album"
CONF_STATUS_SOURCE = "status_source"


def scene_key(number: int, field: str) -> str:
    """Schlüssel eines Szenenfelds: `scene_3_source`, `scene_3_volume`, `scene_3_address`."""
    return f"scene_{number}_{field}"


# Befehl und Rückmeldung als Wörterbuch: Schlüssel
K_ID = "id"
K_ADDRESS = "address"
K_DPT = "dpt"
K_ACTION = "action"
K_WHEN = "when"
K_SCENE = "scene"
K_VOLUME = "volume"
K_SOURCE_NAME = "source_name"
K_SOURCE = "source"
K_IDLE_TEXT = "idle_text"

# Datentypen der Befehle
DPT_SWITCH = "switch"  # 1.001
DPT_PERCENT = "percent"  # 5.001
DPT_SCENE = "scene"  # 17.001
DPT_DIMMING = "dimming"  # 3.007

# Bedingung eines 1-Bit-Befehls
WHEN_ON = "on"
WHEN_OFF = "off"
WHEN_ANY = "any"

# Aktionen
ACT_PLAY = "play"
ACT_PAUSE = "pause"
ACT_PLAY_PAUSE = "play_pause"
ACT_STOP = "stop"
ACT_NEXT = "next"
ACT_PREVIOUS = "previous"
ACT_VOLUME_SET = "volume_set"
ACT_VOLUME_UP = "volume_up"
ACT_VOLUME_DOWN = "volume_down"
ACT_VOLUME_DIM = "volume_dim"
ACT_MUTE_SET = "mute_set"
ACT_SOURCE = "source"

# Quellen der Rückmeldungen
SRC_PLAYING = "playing"
SRC_PAUSED = "paused"
SRC_VOLUME = "volume"
SRC_MUTED = "muted"
SRC_TITLE = "title"
SRC_ARTIST = "artist"
SRC_ALBUM = "album"
SRC_SOURCE = "source"
TEXT_SOURCES = [SRC_TITLE, SRC_ARTIST, SRC_ALBUM, SRC_SOURCE]


def signal_update(entry_id: str) -> str:
    """Dispatcher-Signal, mit dem der Controller seine Entitäten aktualisiert."""
    return f"{DOMAIN}_update_{entry_id}"
