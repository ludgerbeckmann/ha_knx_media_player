"""Controller: verbindet KNX-Gruppenadressen mit einem Media Player.

Setzt auf der offiziellen KNX-Integration auf (Dienste `knx.event_register` und
`knx.send`, Ereignis `knx_event`); es wird keine eigene Busverbindung aufgebaut.
Der Media Player wird nur über die Standarddienste von `media_player` gesteuert,
funktioniert also mit Sonos, Music Assistant und jeder anderen Integration.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_PLAYING, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    ACT_MEDIA,
    ACT_MUTE_SET,
    ACT_NEXT,
    ACT_PAUSE,
    ACT_PLAY,
    ACT_PLAY_PAUSE,
    ACT_PREVIOUS,
    ACT_SOURCE,
    ACT_STOP,
    ACT_VOLUME_DIM,
    ACT_VOLUME_DOWN,
    ACT_VOLUME_SET,
    ACT_VOLUME_UP,
    CONF_ADDR_MUTE,
    CONF_ADDR_NEXT_PREV,
    CONF_ADDR_PLAY_PAUSE,
    CONF_ADDR_SCENE,
    CONF_ADDR_STOP,
    CONF_ADDR_TOGGLE,
    CONF_ADDR_VOLUME,
    CONF_ADDR_VOLUME_DIM,
    CONF_ADDR_VOLUME_STEP,
    CONF_IDLE_TEXT,
    CONF_MAX_VOLUME,
    CONF_PLAYER,
    CONF_START_MEDIA,
    CONF_START_MEDIA_TYPE,
    CONF_START_SOURCE,
    CONF_START_VOLUME,
    CONF_STATUS_ALBUM,
    CONF_STATUS_ARTIST,
    CONF_STATUS_MUTED,
    CONF_STATUS_PAUSED,
    CONF_STATUS_PLAYING,
    CONF_STATUS_SOURCE,
    CONF_STATUS_TITLE,
    CONF_STATUS_VOLUME,
    CONF_STOP_INSTEAD,
    CONF_VOLUME_STEP,
    DEFAULT_MAX_VOLUME,
    DEFAULT_VOLUME_STEP,
    DOMAIN,
    MEDIA_TYPE_AUTO,
    PLAY_MEDIA_AUTO_TYPE,
    DPT_DIMMING,
    DPT_PERCENT,
    DPT_SCENE,
    DPT_SWITCH,
    K_ACTION,
    K_ADDRESS,
    K_DPT,
    K_ID,
    K_IDLE_TEXT,
    K_MEDIA,
    K_MEDIA_TYPE,
    K_SCENE,
    K_SOURCE,
    K_SOURCE_NAME,
    K_VOLUME,
    K_WHEN,
    SCENE_COUNT,
    SRC_ALBUM,
    SRC_ARTIST,
    SRC_MUTED,
    SRC_PAUSED,
    SRC_PLAYING,
    SRC_SOURCE,
    SRC_TITLE,
    SRC_VOLUME,
    TEXT_SOURCES,
    WHEN_ANY,
    WHEN_OFF,
    WHEN_ON,
    scene_key,
    signal_update,
)
from .knx_codec import (
    decode_dimming,
    decode_percent,
    decode_scene,
    decode_switch,
    normalize_ga,
    truncate_text,
)

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
KNX_DOMAIN = "knx"
KNX_EVENT = "knx_event"
KNX_RELOADED_EVENT = "event_knx_reloaded"
REREGISTER_INTERVAL = timedelta(minutes=5)
_UNKNOWN = (STATE_UNAVAILABLE, STATE_UNKNOWN)

# KNX-Datentyp der Rückmeldung je Quelle (Kennung für `knx.send`)
_STATUS_DPT = {
    SRC_PLAYING: "1.001",
    SRC_PAUSED: "1.001",
    SRC_MUTED: "1.001",
    SRC_VOLUME: "5.001",
    SRC_TITLE: "16.001",
    SRC_ARTIST: "16.001",
    SRC_ALBUM: "16.001",
    SRC_SOURCE: "16.001",
}

# Feste Felder -> Befehle: (Feld, Datentyp, [(Aktion, Bedingung)])
_FIELD_COMMANDS: list[tuple[str, str, list[tuple[str, str | None]]]] = [
    (CONF_ADDR_PLAY_PAUSE, DPT_SWITCH, [(ACT_PLAY, WHEN_ON), (ACT_PAUSE, WHEN_OFF)]),
    (CONF_ADDR_NEXT_PREV, DPT_SWITCH, [(ACT_NEXT, WHEN_ON), (ACT_PREVIOUS, WHEN_OFF)]),
    (CONF_ADDR_STOP, DPT_SWITCH, [(ACT_STOP, WHEN_ON)]),
    (CONF_ADDR_TOGGLE, DPT_SWITCH, [(ACT_PLAY_PAUSE, WHEN_ON)]),
    (CONF_ADDR_VOLUME, DPT_PERCENT, [(ACT_VOLUME_SET, None)]),
    (CONF_ADDR_VOLUME_STEP, DPT_SWITCH, [(ACT_VOLUME_UP, WHEN_ON), (ACT_VOLUME_DOWN, WHEN_OFF)]),
    (CONF_ADDR_VOLUME_DIM, DPT_DIMMING, [(ACT_VOLUME_DIM, None)]),
    (CONF_ADDR_MUTE, DPT_SWITCH, [(ACT_MUTE_SET, None)]),
]

# Feste Felder -> Rückmeldungen
_FIELD_STATUS = [
    (CONF_STATUS_PLAYING, SRC_PLAYING),
    (CONF_STATUS_PAUSED, SRC_PAUSED),
    (CONF_STATUS_VOLUME, SRC_VOLUME),
    (CONF_STATUS_MUTED, SRC_MUTED),
    (CONF_STATUS_TITLE, SRC_TITLE),
    (CONF_STATUS_ARTIST, SRC_ARTIST),
    (CONF_STATUS_ALBUM, SRC_ALBUM),
    (CONF_STATUS_SOURCE, SRC_SOURCE),
]

# Attribut des Media Players je Textquelle
_TEXT_ATTRIBUTE = {
    SRC_TITLE: "media_title",
    SRC_ARTIST: "media_artist",
    SRC_ALBUM: "media_album_name",
    SRC_SOURCE: "source",
}


def build_commands(get: Any) -> list[dict[str, Any]]:
    """Befehle aus den Feldern der Konfigurationsseite.

    Jede Adresse ergibt einen oder zwei Befehle (z. B. Play/Pause: 1 = Wiedergabe, 0 = Pause).
    Eine Szene mit Quelle und/oder Lautstärke ergibt Befehle auf der Szenenadresse (17.001)
    und, falls gesetzt, auf der eigenen 1-Bit-Adresse, dort mit „0 = Pause“."""
    commands: list[dict[str, Any]] = []
    for field, dpt, actions in _FIELD_COMMANDS:
        if not get(field):
            continue
        for action, when in actions:
            command: dict[str, Any] = {
                K_ID: f"{field}:{action}",
                K_ADDRESS: get(field),
                K_DPT: dpt,
                K_ACTION: action,
            }
            if when:
                command[K_WHEN] = when
            commands.append(command)
    for number in range(1, SCENE_COUNT + 1):
        source = get(scene_key(number, "source"))
        media = get(scene_key(number, "media"))
        volume = get(scene_key(number, "volume"))
        bit_address = get(scene_key(number, "address"))
        triggers = []
        if get(CONF_ADDR_SCENE):
            triggers.append((get(CONF_ADDR_SCENE), DPT_SCENE))
        if bit_address:
            triggers.append((bit_address, DPT_SWITCH))
        for address, dpt in triggers:
            base: dict[str, Any] = {K_ADDRESS: address, K_DPT: dpt}
            if dpt == DPT_SCENE:
                base[K_SCENE] = number
            else:
                base[K_WHEN] = WHEN_ON
            # Lautstärke zuerst, damit die Quelle nicht kurz mit der alten Lautstärke startet
            if volume is not None:
                commands.append(
                    {**base, K_ID: f"scene_{number}:{dpt}:vol", K_ACTION: ACT_VOLUME_SET,
                     K_VOLUME: float(volume)}
                )
            if source:
                commands.append(
                    {**base, K_ID: f"scene_{number}:{dpt}:src", K_ACTION: ACT_SOURCE,
                     K_SOURCE_NAME: source}
                )
            if media:
                commands.append(
                    {**base, K_ID: f"scene_{number}:{dpt}:media", K_ACTION: ACT_MEDIA,
                     K_MEDIA: media,
                     K_MEDIA_TYPE: get(scene_key(number, "media_type"), MEDIA_TYPE_AUTO)}
                )
        if bit_address:
            commands.append(
                {K_ID: f"scene_{number}:off", K_ADDRESS: bit_address, K_DPT: DPT_SWITCH,
                 K_ACTION: ACT_PAUSE, K_WHEN: WHEN_OFF}
            )
    return commands


def build_status(get: Any) -> list[dict[str, Any]]:
    """Rückmeldungen aus den Feldern der Konfigurationsseite."""
    statuses = []
    for field, source in _FIELD_STATUS:
        if get(field):
            status = {K_ID: field, K_SOURCE: source, K_ADDRESS: get(field)}
            if source in TEXT_SOURCES:
                status[K_IDLE_TEXT] = get(CONF_IDLE_TEXT) or ""
            statuses.append(status)
    return statuses


class KnxMediaPlayerController:
    """Verbindet KNX-Gruppenadressen mit einem Media Player."""

    model = "KNX Media Player"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.enabled = True
        self.last_command: dict[str, Any] | None = None
        self.player: str = entry.data[CONF_PLAYER]
        self._settings: dict[str, Any] = {**entry.data, **entry.options}
        self._store = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._unsubs: list[CALLBACK_TYPE] = []
        self._commands_by_ga: dict[str, list[dict[str, Any]]] = {}
        self._status_by_ga: dict[str, list[dict[str, Any]]] = {}
        self._last_sent: dict[str, Any] = {}
        self._knx_available = False

    # --- Hilfen ------------------------------------------------------------

    def _get(self, key: str, default: Any = None) -> Any:
        value = self._settings.get(key)
        return default if value is None else value

    @property
    def _max_volume(self) -> float:
        return float(self._get(CONF_MAX_VOLUME, DEFAULT_MAX_VOLUME))

    @property
    def _volume_step(self) -> float:
        return float(self._get(CONF_VOLUME_STEP, DEFAULT_VOLUME_STEP))

    def _notify(self) -> None:
        async_dispatcher_send(self.hass, signal_update(self.entry.entry_id))

    async def _async_save(self) -> None:
        await self._store.async_save(
            {"enabled": self.enabled, "last_command": self.last_command}
        )
        self._notify()

    def _player_state(self):
        state = self.hass.states.get(self.player)
        if state is None or state.state in _UNKNOWN:
            return None
        return state

    # --- Lebenszyklus --------------------------------------------------------

    async def async_start(self) -> None:
        stored = await self._store.async_load() or {}
        self.enabled = bool(stored.get("enabled", True))
        self.last_command = stored.get("last_command")

        for command in build_commands(self._get):
            if ga := normalize_ga(command.get(K_ADDRESS)):
                self._commands_by_ga.setdefault(ga, []).append(command)
        for status in build_status(self._get):
            if ga := normalize_ga(status.get(K_ADDRESS)):
                self._status_by_ga.setdefault(ga, []).append(status)

        self._unsubs.append(self.hass.bus.async_listen(KNX_EVENT, self._on_knx_event))
        self._unsubs.append(
            self.hass.bus.async_listen(KNX_RELOADED_EVENT, self._on_knx_reloaded)
        )
        self._unsubs.append(
            async_track_state_change_event(self.hass, [self.player], self._on_player_change)
        )
        self._unsubs.append(
            async_track_time_interval(
                self.hass, self._on_reregister_interval, REREGISTER_INTERVAL
            )
        )
        await self._async_register()

    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    async def async_remove_data(self) -> None:
        await self._store.async_remove()

    async def async_set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        await self._async_save()
        if enabled:
            await self._async_send_status(force=True)

    # --- Dienstaufrufe ---------------------------------------------------------

    async def _async_call(self, domain: str, service: str, data: dict[str, Any]) -> None:
        """Dienst aufrufen; ein Fehler darf die übrige Verarbeitung nicht stoppen."""
        try:
            await self.hass.services.async_call(domain, service, data, blocking=True)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Aufruf von %s.%s fehlgeschlagen", domain, service)

    async def _async_player_call(self, service: str, **data: Any) -> None:
        await self._async_call(
            "media_player", service, {"entity_id": self.player, **data}
        )

    # --- KNX-Anbindung ---------------------------------------------------------

    async def _async_register(self) -> None:
        """Gruppenadressen bei der KNX-Integration anmelden (idempotent).

        Die Anmeldung gilt nur zur Laufzeit und geht beim Neuladen der
        KNX-Integration verloren, daher wird sie regelmäßig wiederholt.
        """
        if not self.hass.services.has_service(KNX_DOMAIN, "event_register"):
            self._knx_available = False
            return
        addresses = sorted({*self._commands_by_ga, *self._status_by_ga})
        if addresses:
            await self._async_call(KNX_DOMAIN, "event_register", {"address": addresses})
        if not self._knx_available:
            self._knx_available = True
            await self._async_send_status(force=True)

    async def _on_knx_reloaded(self, event: Event) -> None:
        self._knx_available = False
        await self._async_register()

    async def _on_reregister_interval(self, _now: datetime) -> None:
        await self._async_register()

    async def _async_knx_send(
        self, address: str, payload: Any, dpt: str, *, response: bool = False
    ) -> None:
        if not self.hass.services.has_service(KNX_DOMAIN, "send"):
            return
        data: dict[str, Any] = {"address": address, "payload": payload, "type": dpt}
        if response:
            data["response"] = True
        await self._async_call(KNX_DOMAIN, "send", data)

    # --- Befehle (KNX -> Media Player) -----------------------------------------

    async def _on_knx_event(self, event: Event) -> None:
        data = event.data
        # Ausgehende Telegramme (auch unsere eigenen Rückmeldungen) nie auswerten
        if data.get("direction") != "Incoming":
            return
        ga = normalize_ga(data.get("destination"))
        if ga is None:
            return
        telegram_type = data.get("telegramtype")
        if telegram_type == "GroupValueRead":
            await self._async_answer_read(ga)
            return
        if telegram_type != "GroupValueWrite" or not self.enabled:
            return
        for command in self._commands_by_ga.get(ga, []):
            await self._async_run_command(command, data.get("data"))

    @staticmethod
    def _decode(command: dict[str, Any], raw: Any) -> tuple[Any, bool] | None:
        """Rohdaten dekodieren und Bedingung prüfen: (Wert, erfüllt) oder None."""
        dpt = command.get(K_DPT)
        if dpt == DPT_SWITCH:
            value = decode_switch(raw)
            if value is None:
                return None
            # "Stumm (Wert)" folgt dem Telegrammwert, hat also keine Bedingung
            when = (
                WHEN_ANY
                if command.get(K_ACTION) == ACT_MUTE_SET
                else command.get(K_WHEN, WHEN_ON)
            )
            ok = (
                when == WHEN_ANY
                or (when == WHEN_ON and value)
                or (when == WHEN_OFF and not value)
            )
            return value, bool(ok)
        if dpt == DPT_PERCENT:
            value = decode_percent(raw)
            return (None, False) if value is None else (value, True)
        if dpt == DPT_SCENE:
            value = decode_scene(raw)
            if value is None:
                return None
            return value, value == int(command.get(K_SCENE, 0))
        if dpt == DPT_DIMMING:
            dim = decode_dimming(raw)
            if dim is None:
                return None
            increase, step = dim
            return increase, step != 0  # Schrittcode 0 = Stopp
        return None

    async def _async_run_command(self, command: dict[str, Any], raw: Any) -> None:
        decoded = self._decode(command, raw)
        if decoded is None or not decoded[1]:
            return
        value = decoded[0]
        state = self._player_state()
        if state is None:
            _LOGGER.debug("%s: Media Player %s nicht verfügbar", self.entry.title, self.player)
            return
        await self._async_do(command.get(K_ACTION), command, value, state)
        self.last_command = {
            "time": dt_util.utcnow().isoformat(),
            "address": command.get(K_ADDRESS),
            "action": command.get(K_ACTION),
            "value": value if isinstance(value, (bool, int, float, str)) else None,
        }
        await self._async_save()

    def _clamp(self, percent: float) -> float:
        return max(0.0, min(float(percent), self._max_volume))

    async def _async_set_volume(self, percent: float) -> None:
        await self._async_player_call(
            "volume_set", volume_level=round(self._clamp(percent) / 100, 2)
        )

    @staticmethod
    def _current_volume_percent(state) -> float | None:
        level = state.attributes.get("volume_level")
        return None if level is None else float(level) * 100

    async def _async_pause(self) -> None:
        stop = bool(self._get(CONF_STOP_INSTEAD, False))
        await self._async_player_call("media_stop" if stop else "media_pause")

    async def _async_play_media(self, media: str, media_type: str | None) -> None:
        """Medium (Name, URI oder Sonos-/MA-Favorit) über `media_player.play_media` abspielen."""
        content_type = (
            PLAY_MEDIA_AUTO_TYPE if media_type in (None, MEDIA_TYPE_AUTO) else media_type
        )
        await self._async_player_call(
            "play_media", media_content_id=media, media_content_type=content_type
        )

    async def _async_start(self, state) -> None:
        """Wiedergabe starten; spielt der Player noch nicht, zuerst Startlautstärke und Startquelle/-medium."""
        if state.state != STATE_PLAYING:
            volume = self._get(CONF_START_VOLUME)
            if volume is not None:
                await self._async_set_volume(float(volume))
            source = self._get(CONF_START_SOURCE)
            if source:
                await self._async_player_call("select_source", source=source)
                return
            if media := self._get(CONF_START_MEDIA):
                await self._async_play_media(media, self._get(CONF_START_MEDIA_TYPE))
                return
        await self._async_player_call("media_play")

    async def _async_do(self, action: str, command: dict[str, Any], value: Any, state) -> None:
        if action == ACT_PLAY:
            await self._async_start(state)
        elif action == ACT_PAUSE:
            await self._async_pause()
        elif action == ACT_PLAY_PAUSE:
            if state.state == STATE_PLAYING:
                await self._async_pause()
            else:
                await self._async_start(state)
        elif action == ACT_STOP:
            await self._async_player_call("media_stop")
        elif action == ACT_NEXT:
            await self._async_player_call("media_next_track")
        elif action == ACT_PREVIOUS:
            await self._async_player_call("media_previous_track")
        elif action == ACT_VOLUME_SET:
            if command.get(K_DPT) == DPT_PERCENT:
                await self._async_set_volume(value)
            elif command.get(K_VOLUME) is not None:
                await self._async_set_volume(float(command[K_VOLUME]))
        elif action in (ACT_VOLUME_UP, ACT_VOLUME_DOWN, ACT_VOLUME_DIM):
            current = self._current_volume_percent(state)
            if current is None:
                return
            up = action == ACT_VOLUME_UP or (action == ACT_VOLUME_DIM and value)
            step = self._volume_step
            await self._async_set_volume(current + step if up else current - step)
        elif action == ACT_MUTE_SET:
            await self._async_player_call("volume_mute", is_volume_muted=bool(value))
        elif action == ACT_SOURCE and command.get(K_SOURCE_NAME):
            await self._async_player_call("select_source", source=command[K_SOURCE_NAME])
        elif action == ACT_MEDIA and command.get(K_MEDIA):
            await self._async_play_media(command[K_MEDIA], command.get(K_MEDIA_TYPE))

    # --- Rückmeldungen (Media Player -> KNX) -----------------------------------

    def _status_value(self, status: dict[str, Any]) -> Any:
        """Aktuellen Wert der Quelle bestimmen (None = nicht senden)."""
        state = self._player_state()
        if state is None:
            return None
        source = status.get(K_SOURCE)
        attrs = state.attributes
        if source == SRC_PLAYING:
            return state.state == STATE_PLAYING
        if source == SRC_PAUSED:
            return state.state == "paused"
        if source == SRC_MUTED:
            return bool(attrs.get("is_volume_muted"))
        if source == SRC_VOLUME:
            level = attrs.get("volume_level")
            return None if level is None else round(float(level) * 100)
        if source in TEXT_SOURCES:
            if state.state != STATE_PLAYING:
                return truncate_text(status.get(K_IDLE_TEXT, ""))
            return truncate_text(attrs.get(_TEXT_ATTRIBUTE[source]))
        return None

    async def _async_send_status(self, force: bool = False) -> None:
        if not self.enabled or not self._knx_available:
            return
        for statuses in self._status_by_ga.values():
            for status in statuses:
                value = self._status_value(status)
                if value is None:
                    continue
                key = status[K_ID]
                if not force and self._last_sent.get(key) == value:
                    continue
                self._last_sent[key] = value
                await self._async_knx_send(
                    status[K_ADDRESS], value, _STATUS_DPT[status[K_SOURCE]]
                )

    async def _async_answer_read(self, ga: str) -> None:
        if not self.enabled:
            return
        for status in self._status_by_ga.get(ga, []):
            value = self._status_value(status)
            if value is None:
                continue
            await self._async_knx_send(
                status[K_ADDRESS], value, _STATUS_DPT[status[K_SOURCE]], response=True
            )

    @callback
    def _on_player_change(self, event: Event) -> None:
        self.hass.async_create_task(self._async_send_status())
