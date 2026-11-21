"""Tests für Controller, Entitäten und Dialoge."""

from datetime import timedelta

import pytest
from homeassistant.data_entry_flow import InvalidData

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.knx_media_player.const import DOMAIN
from custom_components.knx_media_player.controller import build_commands, build_status

PLAYER = "media_player.living_room"
SERVICES = (
    "media_play", "media_pause", "media_stop", "media_next_track",
    "media_previous_track", "volume_set", "volume_mute", "select_source", "play_media",
)


async def _setup(hass: HomeAssistant, state="paused", attrs=None, **options):
    mocks = {n: async_mock_service(hass, "media_player", n) for n in SERVICES}
    mocks["register"] = async_mock_service(hass, "knx", "event_register")
    mocks["send"] = async_mock_service(hass, "knx", "send")
    hass.states.async_set(
        PLAYER, state,
        {"volume_level": 0.3, "is_volume_muted": False, "source_list": ["Radio", "Jazz"],
         "media_title": "Song", "media_artist": "Artist", "media_album_name": "Album",
         "source": "Radio", "media_duration": 200, **(attrs or {})},
    )
    entry = MockConfigEntry(
        domain=DOMAIN, title="Wohnzimmer", data={"player": PLAYER}, options=options,
        unique_id=PLAYER,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, mocks


async def _telegram(hass, destination, data, *, direction="Incoming", telegramtype="GroupValueWrite"):
    hass.bus.async_fire("knx_event", {
        "data": data, "destination": destination, "direction": direction,
        "telegramtype": telegramtype, "value": None, "source": "1.1.1"})
    await hass.async_block_till_done()


# --- Befehle und Rückmeldungen aus den Feldern ---------------------------------


def test_build_commands_and_status() -> None:
    values = {"addr_play_pause": "1/0/1", "addr_volume_dim": "1/0/2", "addr_scene": "2/0/1",
              "scene_2_source": "Radio", "scene_2_volume": 20, "scene_2_address": "2/1/2",
              "status_title": "5/0/4", "status_playing": "5/0/1", "idle_text": "Pause"}
    get = lambda key, default=None: values.get(key, default)  # noqa: E731
    by = {(c["address"], c["action"], c.get("when"), c.get("scene")) for c in build_commands(get)}
    assert ("1/0/1", "play", "on", None) in by and ("1/0/1", "pause", "off", None) in by
    assert ("1/0/2", "volume_dim", None, None) in by
    assert ("2/0/1", "source", None, 2) in by and ("2/0/1", "volume_set", None, 2) in by
    assert ("2/1/2", "source", "on", None) in by and ("2/1/2", "pause", "off", None) in by
    statuses = {s["address"]: s for s in build_status(get)}
    assert statuses["5/0/4"]["idle_text"] == "Pause" and "idle_text" not in statuses["5/0/1"]
    assert build_commands(lambda key, default=None: default) == []


# --- KNX -> Media Player ---------------------------------------------------------


async def test_playback_commands(hass: HomeAssistant) -> None:
    _, m = await _setup(
        hass, addr_play_pause="1/0/1", addr_next_prev="1/0/2", addr_stop="1/0/3",
        addr_toggle="1/0/4",
    )
    await _telegram(hass, "1/0/1", 1)
    assert len(m["media_play"]) == 1
    await _telegram(hass, "1/0/1", 0)
    assert len(m["media_pause"]) == 1
    await _telegram(hass, "1/0/2", 1)
    await _telegram(hass, "1/0/2", 0)
    assert len(m["media_next_track"]) == 1 and len(m["media_previous_track"]) == 1
    await _telegram(hass, "1/0/3", 1)
    await _telegram(hass, "1/0/3", 0)  # 0 stoppt nicht
    assert len(m["media_stop"]) == 1
    await _telegram(hass, "1/0/4", 1)  # pausiert -> Wiedergabe
    assert len(m["media_play"]) == 2
    hass.states.async_set(PLAYER, "playing", {"volume_level": 0.3, "media_duration": 200})
    await _telegram(hass, "1/0/4", 1)  # spielt -> Pause
    assert len(m["media_pause"]) == 2
    assert m["media_play"][0].data["entity_id"] == PLAYER


async def test_ignores_outgoing_unregistered_and_disabled(hass: HomeAssistant) -> None:
    entry, m = await _setup(hass, addr_stop="1/0/3")
    await _telegram(hass, "1/0/3", 1, direction="Outgoing")
    await _telegram(hass, "9/9/9", 1)
    await _telegram(hass, "1/0/3", 1, telegramtype="GroupValueResponse")
    assert not m["media_stop"]
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.wohnzimmer_knx_control_active"}, blocking=True
    )
    await _telegram(hass, "1/0/3", 1)
    assert not m["media_stop"]
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.wohnzimmer_knx_control_active"}, blocking=True
    )
    await _telegram(hass, "1/0/3", 1)
    assert len(m["media_stop"]) == 1


async def test_unavailable_player_is_skipped(hass: HomeAssistant) -> None:
    _, m = await _setup(hass, state="unavailable", addr_stop="1/0/3")
    await _telegram(hass, "1/0/3", 1)
    assert not m["media_stop"]


async def test_volume_commands(hass: HomeAssistant) -> None:
    _, m = await _setup(
        hass, max_volume=50, volume_step=10, addr_volume="2/0/1", addr_volume_step="2/0/2",
        addr_volume_dim="2/0/3", addr_mute="2/0/4",
    )
    await _telegram(hass, "2/0/1", (255,))  # 100 % wird auf 50 % begrenzt
    assert m["volume_set"][-1].data["volume_level"] == 0.5
    await _telegram(hass, "2/0/1", (51,))  # 20 %
    assert m["volume_set"][-1].data["volume_level"] == 0.2
    await _telegram(hass, "2/0/2", 1)  # 30 % + 10
    assert m["volume_set"][-1].data["volume_level"] == 0.4
    await _telegram(hass, "2/0/2", 0)  # 30 % - 10
    assert m["volume_set"][-1].data["volume_level"] == 0.2
    await _telegram(hass, "2/0/3", 0b1001)  # heller, Schritt 1
    assert m["volume_set"][-1].data["volume_level"] == 0.4
    await _telegram(hass, "2/0/3", 0b0001)  # dunkler
    assert m["volume_set"][-1].data["volume_level"] == 0.2
    count = len(m["volume_set"])
    await _telegram(hass, "2/0/3", 0b1000)  # Schrittcode 0 = Stopp
    assert len(m["volume_set"]) == count
    await _telegram(hass, "2/0/4", 1)
    assert m["volume_mute"][-1].data["is_volume_muted"] is True
    await _telegram(hass, "2/0/4", 0)
    assert m["volume_mute"][-1].data["is_volume_muted"] is False


async def test_legacy_stop_instead_of_pause(hass: HomeAssistant) -> None:
    """Ältere Einstellung (Haken): True stoppt, False pausiert, jeweils unabhängig vom Inhalt."""
    _, m = await _setup(hass, stop_instead_of_pause=True, addr_play_pause="1/0/1")
    await _telegram(hass, "1/0/1", 0)
    assert len(m["media_stop"]) == 1 and not m["media_pause"]


async def test_legacy_pause_flag_false_always_pauses(hass: HomeAssistant) -> None:
    _, m = await _setup(
        hass, attrs={"media_duration": None}, stop_instead_of_pause=False, addr_play_pause="1/0/1"
    )
    await _telegram(hass, "1/0/1", 0)  # Livestream, aber der Haken war bewusst aus
    assert len(m["media_pause"]) == 1 and not m["media_stop"]


async def test_pause_mode_auto(hass: HomeAssistant) -> None:
    """Automatisch: Livestream (keine Dauer) stoppt, ein Titel mit Dauer pausiert."""
    _, m = await _setup(hass, attrs={"media_duration": None}, addr_play_pause="1/0/1")
    await _telegram(hass, "1/0/1", 0)
    assert len(m["media_stop"]) == 1 and not m["media_pause"]
    hass.states.async_set(PLAYER, "playing", {"volume_level": 0.3, "media_duration": 180})
    await _telegram(hass, "1/0/1", 0)
    assert len(m["media_pause"]) == 1 and len(m["media_stop"]) == 1


async def test_pause_mode_auto_is_the_default(hass: HomeAssistant) -> None:
    # weder pause_mode noch der ältere Haken gespeichert
    _, m = await _setup(hass, attrs={"media_duration": None}, addr_play_pause="1/0/1")
    await _telegram(hass, "1/0/1", 0)
    assert len(m["media_stop"]) == 1


async def test_pause_mode_fixed(hass: HomeAssistant) -> None:
    _, m = await _setup(hass, attrs={"media_duration": None}, pause_mode="pause", addr_play_pause="1/0/1")
    await _telegram(hass, "1/0/1", 0)
    assert len(m["media_pause"]) == 1 and not m["media_stop"]


async def test_pause_mode_stop_even_for_tracks(hass: HomeAssistant) -> None:
    _, m = await _setup(hass, pause_mode="stop", addr_play_pause="1/0/1", addr_toggle="1/0/4")
    await _telegram(hass, "1/0/1", 0)
    assert len(m["media_stop"]) == 1 and not m["media_pause"]
    hass.states.async_set(PLAYER, "playing", {"volume_level": 0.3, "media_duration": 200})
    await _telegram(hass, "1/0/4", 1)  # Taster bei laufender Wiedergabe
    assert len(m["media_stop"]) == 2


async def test_stop_command_always_stops(hass: HomeAssistant) -> None:
    _, m = await _setup(hass, pause_mode="pause", addr_stop="1/0/3")
    await _telegram(hass, "1/0/3", 1)
    assert len(m["media_stop"]) == 1 and not m["media_pause"]


def test_pause_mode_form_default() -> None:
    from custom_components.knx_media_player.config_flow import _pause_mode_default

    assert _pause_mode_default({}) == "auto"
    assert _pause_mode_default({"pause_mode": "stop"}) == "stop"
    assert _pause_mode_default({"stop_instead_of_pause": True}) == "stop"
    assert _pause_mode_default({"stop_instead_of_pause": False}) == "pause"
    assert _pause_mode_default({"pause_mode": "stop", "stop_instead_of_pause": False}) == "stop"
    assert _pause_mode_default({"pause_mode": "kaputt"}) == "auto"


async def test_start_volume_and_source(hass: HomeAssistant) -> None:
    _, m = await _setup(
        hass, max_volume=40, start_volume=60, start_source="Jazz", addr_toggle="1/0/4"
    )
    await _telegram(hass, "1/0/4", 1)
    assert m["volume_set"][-1].data["volume_level"] == 0.4  # durch die Grenze gekappt
    assert m["select_source"][-1].data["source"] == "Jazz"
    assert not m["media_play"]
    # läuft schon: keine Änderung von Lautstärke und Quelle, nur Pause
    hass.states.async_set(PLAYER, "playing", {"volume_level": 0.3, "media_duration": 200})
    await _telegram(hass, "1/0/4", 1)
    assert len(m["volume_set"]) == 1 and len(m["media_pause"]) == 1


async def test_scenes(hass: HomeAssistant) -> None:
    _, m = await _setup(
        hass, addr_scene="3/0/1", scene_2_source="Jazz", scene_2_volume=25,
        scene_3_address="3/0/3", scene_3_source="Radio",
    )
    await _telegram(hass, "3/0/1", (1,))  # DPT 17.001: 1 = Szene 2
    assert m["volume_set"][-1].data["volume_level"] == 0.25
    assert m["select_source"][-1].data["source"] == "Jazz"
    await _telegram(hass, "3/0/1", (0,))  # Szene 1 ist nicht belegt
    assert len(m["select_source"]) == 1
    await _telegram(hass, "3/0/3", 1)
    assert m["select_source"][-1].data["source"] == "Radio"
    await _telegram(hass, "3/0/3", 0)
    assert len(m["media_pause"]) == 1


async def test_scene_media_for_music_assistant(hass: HomeAssistant) -> None:
    _, m = await _setup(
        hass, addr_scene="3/0/1", scene_1_media="library://playlist/7", scene_1_media_type="playlist",
        scene_1_volume=20, scene_2_media="Radio Paradise", scene_2_address="3/0/2",
    )
    await _telegram(hass, "3/0/1", (0,))  # Szene 1
    assert m["volume_set"][-1].data["volume_level"] == 0.2
    assert m["play_media"][-1].data == {
        "entity_id": PLAYER, "media_content_id": "library://playlist/7",
        "media_content_type": "playlist",
    }
    assert not m["select_source"]
    await _telegram(hass, "3/0/2", 1)  # Szene 2 ohne Typ: automatisch
    assert m["play_media"][-1].data["media_content_id"] == "Radio Paradise"
    assert m["play_media"][-1].data["media_content_type"] == "music"


async def test_start_media(hass: HomeAssistant) -> None:
    _, m = await _setup(
        hass, start_volume=10, start_media="library://album/3", start_media_type="album",
        addr_toggle="1/0/4",
    )
    await _telegram(hass, "1/0/4", 1)
    assert m["volume_set"][-1].data["volume_level"] == 0.1
    assert m["play_media"][-1].data["media_content_type"] == "album"
    assert not m["media_play"]
    # eine gesetzte Startquelle hat Vorrang vor dem Medium
    _, m2 = await _setup(hass, start_source="Jazz", start_media="x", addr_toggle="1/0/5")
    await _telegram(hass, "1/0/5", 1)
    assert m2["select_source"][-1].data["source"] == "Jazz"


# --- Media Player -> KNX -----------------------------------------------------------


async def test_registers_addresses_and_sends_status(hass: HomeAssistant) -> None:
    _, m = await _setup(
        hass, state="playing", addr_stop="1/0/3", status_playing="5/0/1",
        status_paused="5/0/2", status_volume="5/0/3", status_title="5/0/4",
        status_source="5/0/5", status_muted="5/0/6", idle_text="Pause",
    )
    assert m["register"][0].data["address"] == [
        "1/0/3", "5/0/1", "5/0/2", "5/0/3", "5/0/4", "5/0/5", "5/0/6"
    ]
    sent = {c.data["address"]: c.data for c in m["send"]}
    assert sent["5/0/1"]["payload"] is True and sent["5/0/1"]["type"] == "1.001"
    assert sent["5/0/2"]["payload"] is False
    assert sent["5/0/3"]["payload"] == 30 and sent["5/0/3"]["type"] == "5.001"
    assert sent["5/0/4"]["payload"] == "Song" and sent["5/0/4"]["type"] == "16.001"
    assert sent["5/0/5"]["payload"] == "Radio"
    assert sent["5/0/6"]["payload"] is False

    m["send"].clear()
    hass.states.async_set(PLAYER, "paused", {"volume_level": 0.3, "is_volume_muted": False})
    await hass.async_block_till_done()
    changed = {c.data["address"]: c.data["payload"] for c in m["send"]}
    # nur geänderte Werte; Text fällt auf den Ruhetext zurück
    assert changed == {"5/0/1": False, "5/0/2": True, "5/0/4": "Pause", "5/0/5": "Pause"}


async def test_answers_read_telegrams(hass: HomeAssistant) -> None:
    _, m = await _setup(hass, state="playing", status_volume="5/0/3")
    m["send"].clear()
    await _telegram(hass, "5/0/3", None, telegramtype="GroupValueRead")
    assert m["send"][0].data == {
        "address": "5/0/3", "payload": 30, "type": "5.001", "response": True
    }


async def test_reregisters_periodically(hass: HomeAssistant) -> None:
    _, m = await _setup(hass, addr_stop="1/0/3")
    assert len(m["register"]) == 1
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=6))
    await hass.async_block_till_done()
    assert len(m["register"]) == 2


async def test_last_command_sensor(hass: HomeAssistant) -> None:
    _, m = await _setup(hass, addr_stop="1/0/3")
    sensor = "sensor.wohnzimmer_last_knx_command"
    assert hass.states.get(sensor).state == "unknown"
    await _telegram(hass, "1/0/3", 1)
    state = hass.states.get(sensor)
    assert state.state != "unknown" and state.attributes["action"] == "stop"
    assert state.attributes["address"] == "1/0/3"


async def test_unload_and_reload(hass: HomeAssistant) -> None:
    entry, m = await _setup(hass, addr_stop="1/0/3")
    assert await hass.config_entries.async_unload(entry.entry_id)
    await _telegram(hass, "1/0/3", 1)
    assert not m["media_stop"]
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await _telegram(hass, "1/0/3", 1)
    assert len(m["media_stop"]) == 1


# --- Dialoge -----------------------------------------------------------------------


def page(**fields):
    """Eingaben der Optionsseite: flache Felder auf die Abschnitte verteilen."""
    sections = {name: {} for name in (
        "player_settings", "playback", "start", "volume", "scenes",
        *(f"scene_{n}" for n in range(1, 6)), "status_play", "status_level", "status_text")}
    for key, value in fields.items():
        if key in ("max_volume", "volume_step", "pause_mode"):
            sections["player_settings"][key] = value
        elif key.startswith("scene_"):
            sections[f"scene_{key.split('_')[1]}"][key] = value
        elif key in ("addr_play_pause", "addr_next_prev", "addr_stop", "addr_toggle"):
            sections["playback"][key] = value
        elif key in ("addr_volume", "addr_volume_step", "addr_volume_dim", "addr_mute"):
            sections["volume"][key] = value
        elif key in ("start_volume", "start_source", "start_media", "start_media_type", "start_station"):
            sections["start"][key] = value
        elif key == "addr_scene":
            sections["scenes"][key] = value
        elif key in ("status_playing", "status_paused"):
            sections["status_play"][key] = value
        elif key in ("status_volume", "status_muted"):
            sections["status_level"][key] = value
        else:
            sections["status_text"][key] = value
    sections["player_settings"].setdefault("max_volume", 100)
    sections["player_settings"].setdefault("volume_step", 5)
    sections["player_settings"].setdefault("pause_mode", "auto")
    return sections


def _player_selector(result):
    return next(v for k, v in result["data_schema"].schema.items() if str(k) == "player")


async def test_config_flow(hass: HomeAssistant) -> None:
    hass.states.async_set(PLAYER, "idle", {"friendly_name": "Wohnzimmer"})
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    # ein Fenster mit der Entitätsauswahl: kein Bereichsschritt, kein Namensfeld
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"
    assert [str(f) for f in result["data_schema"].schema] == ["player"]
    confirm = await hass.config_entries.flow.async_configure(result["flow_id"], {"player": PLAYER})
    # Bestätigung zeigt, was gewählt wurde; angelegt ist noch nichts
    assert confirm["type"] is FlowResultType.FORM and confirm["step_id"] == "confirm"
    assert "Wohnzimmer" in confirm["description_placeholders"]["player_info"]
    assert not hass.config_entries.async_entries(DOMAIN)
    created = await hass.config_entries.flow.async_configure(confirm["flow_id"], {})
    assert created["type"] is FlowResultType.CREATE_ENTRY
    assert created["title"] == "Wohnzimmer" and created["data"] == {"player": PLAYER}


async def test_config_flow_excludes_configured_players(hass: HomeAssistant) -> None:
    hass.states.async_set(PLAYER, "idle", {"friendly_name": "Wohnzimmer"})
    first = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert _player_selector(first).config.get("exclude_entities") is None
    confirm = await hass.config_entries.flow.async_configure(first["flow_id"], {"player": PLAYER})
    await hass.config_entries.flow.async_configure(confirm["flow_id"], {})

    # zweites Gerät: der erste Player fehlt in der Liste und wird auch nicht angenommen
    again = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert _player_selector(again).config["exclude_entities"] == [PLAYER]
    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(again["flow_id"], {"player": PLAYER})


async def test_config_flow_two_open_dialogs(hass: HomeAssistant) -> None:
    """Zwei gleichzeitig offene Dialoge: der zweite bricht beim selben Player ab."""
    first = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    second = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    confirm = await hass.config_entries.flow.async_configure(first["flow_id"], {"player": PLAYER})
    await hass.config_entries.flow.async_configure(confirm["flow_id"], {})
    dup = await hass.config_entries.flow.async_configure(second["flow_id"], {"player": PLAYER})
    assert dup["type"] is FlowResultType.ABORT and dup["reason"] == "already_configured"


async def test_config_flow_title_without_state(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    confirm = await hass.config_entries.flow.async_configure(result["flow_id"], {"player": PLAYER})
    created = await hass.config_entries.flow.async_configure(confirm["flow_id"], {})
    assert created["title"] == PLAYER  # ohne Zustand: Entity-ID


async def test_describe_player(hass: HomeAssistant) -> None:
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import entity_registry as er

    from custom_components.knx_media_player.helpers import describe_player, player_integration_name

    assert await describe_player(hass, "media_player.gibtsnicht") == "- **Name:** media_player.gibtsnicht"
    assert await player_integration_name(hass, "media_player.gibtsnicht") is None

    sonos = _register_player(hass, "sonos", "buero")
    ma = _register_player(hass, "music_assistant", "kueche")
    hass.states.async_set(sonos.entity_id, "idle", {"friendly_name": "Büro"})
    hass.states.async_set(ma.entity_id, "idle", {"friendly_name": "Küche"})
    area = ar.async_get(hass).async_create("Arbeitszimmer")
    er.async_get(hass).async_update_entity(sonos.entity_id, area_id=area.id)

    hass.config.language = "de"
    assert await player_integration_name(hass, sonos.entity_id) == "Sonos"
    assert await player_integration_name(hass, ma.entity_id) == "Music Assistant"
    assert await describe_player(hass, sonos.entity_id) == (
        "- **Name:** Büro\n- **Integration:** Sonos\n- **Bereich:** Arbeitszimmer\n"
        "- **Entität:** media_player.buero"
    )
    # ohne Bereich entfällt die Zeile
    assert await describe_player(hass, ma.entity_id) == (
        "- **Name:** Küche\n- **Integration:** Music Assistant\n- **Entität:** media_player.kueche"
    )
    hass.config.language = "en"
    assert "- **Area:** Arbeitszimmer" in await describe_player(hass, sonos.entity_id)


async def test_integration_shown_in_dialogs(hass: HomeAssistant) -> None:
    _register_player(hass, "music_assistant")
    entry, _ = await _setup(hass)
    hass.states.async_set(PLAYER, "idle", {"friendly_name": "Büro"})
    options = await hass.config_entries.options.async_init(entry.entry_id)
    assert "Music Assistant" in options["description_placeholders"]["player_info"]
    assert set(options["description_placeholders"]) == {"player_info"}
    reconf = await entry.start_reconfigure_flow(hass)
    assert "Music Assistant" in reconf["description_placeholders"]["player_info"]


async def test_options_flow(hass: HomeAssistant) -> None:
    entry, _ = await _setup(hass, addr_stop="1/0/3", status_title="5/0/4")
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "init"

    bad = await hass.config_entries.options.async_configure(
        result["flow_id"], page(addr_play_pause="x/y", scene_2_address="bad"))
    assert bad["errors"] == {"base": "invalid_address"}
    lonely = await hass.config_entries.options.async_configure(
        result["flow_id"], page(scene_3_source="Jazz"))
    assert lonely["errors"] == {"base": "scene_no_trigger"}

    media_only = await hass.config_entries.options.async_configure(
        result["flow_id"], page(scene_4_media="Radio Paradise"))
    assert media_only["errors"] == {"base": "scene_no_trigger"}

    ok = await hass.config_entries.options.async_configure(
        result["flow_id"],
        page(addr_play_pause=" 1/0/1 ", addr_scene="1/0/9", scene_3_source="Jazz",
             scene_3_volume=30.0, status_title="5/0/4", idle_text="Pause", max_volume=80.0),
    )
    assert ok["type"] is FlowResultType.CREATE_ENTRY
    data = ok["data"]
    assert data["addr_play_pause"] == "1/0/1" and data["max_volume"] == 80
    assert data["scene_3_source"] == "Jazz" and data["scene_3_volume"] == 30
    assert "addr_stop" not in data  # geleertes Feld entfällt
    await hass.async_block_till_done()
    assert entry.options == data


async def test_playback_field_order(hass: HomeAssistant) -> None:
    from custom_components.knx_media_player.config_flow import _options_schema

    schema = _options_schema({}, [], [])
    playback = next(m for k, m in schema.schema.items() if str(k) == "playback")
    assert [str(f) for f in playback.schema.schema] == [
        "addr_play_pause", "addr_toggle", "addr_next_prev", "addr_stop"
    ]


async def test_reconfigure_changes_player_and_keeps_options(hass: HomeAssistant) -> None:
    entry, m = await _setup(hass, addr_stop="1/0/3", max_volume=60)
    other = "media_player.kitchen"
    hass.states.async_set(other, "paused", {"volume_level": 0.5, "friendly_name": "Küche"})

    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "reconfigure"
    done = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"player": other, "name": ""}
    )
    assert done["type"] is FlowResultType.ABORT and done["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()

    assert entry.data == {"player": other} and entry.unique_id == other
    assert entry.title == "Küche"  # leerer Name: Name des Media Players
    assert entry.options == {"addr_stop": "1/0/3", "max_volume": 60}
    # der Eintrag steuert jetzt den neuen Player
    await _telegram(hass, "1/0/3", 1)
    assert m["media_stop"][-1].data["entity_id"] == other


async def test_reconfigure_rejects_player_of_other_entry(hass: HomeAssistant) -> None:
    entry, _ = await _setup(hass)
    other = "media_player.kitchen"
    MockConfigEntry(domain=DOMAIN, title="Küche", data={"player": other}, unique_id=other).add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    done = await hass.config_entries.flow.async_configure(result["flow_id"], {"player": other})
    assert done["type"] is FlowResultType.ABORT and done["reason"] == "already_configured"
    assert entry.data == {"player": PLAYER}


async def test_reconfigure_rename_only(hass: HomeAssistant) -> None:
    entry, _ = await _setup(hass, addr_stop="1/0/3")
    result = await entry.start_reconfigure_flow(hass)
    await hass.config_entries.flow.async_configure(
        result["flow_id"], {"player": PLAYER, "name": " Wohnzimmer neu "}
    )
    await hass.async_block_till_done()
    assert entry.title == "Wohnzimmer neu" and entry.data == {"player": PLAYER}


# --- Felder je Player-Typ, Bereich ----------------------------------------------------


def _register_player(hass, platform, object_id="living_room"):
    from homeassistant.helpers import entity_registry as er

    return er.async_get(hass).async_get_or_create(
        "media_player", platform, f"{platform}-{object_id}", suggested_object_id=object_id
    )


def _device_of(hass, entry):
    """Das Gerät des Eintrags (ohne das in neuem Home Assistant fehlerhafte `async_get_device`)."""
    from homeassistant.helpers import device_registry as dr

    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    return devices[0] if devices else None


def _fields(schema):
    return {
        str(sec): {str(f) for f in marker.schema.schema}
        for sec, marker in schema.schema.items()
    }


async def test_fields_follow_player_kind(hass: HomeAssistant) -> None:
    from custom_components.knx_media_player.config_flow import _options_schema

    sonos = _fields(_options_schema({}, [], [], "sonos"))
    assert "start_source" in sonos["start"] and "start_media" not in sonos["start"]
    assert "start_media_type" not in sonos["start"]
    assert "scene_1_source" in sonos["scene_1"] and "scene_1_media" not in sonos["scene_1"]

    ma = _fields(_options_schema({}, [], [], "music_assistant"))
    assert "start_source" not in ma["start"] and {"start_media", "start_media_type"} <= ma["start"]
    assert "scene_2_source" not in ma["scene_2"] and "scene_2_media" in ma["scene_2"]

    other = _fields(_options_schema({}, [], [], None))
    assert {"start_source", "start_media"} <= other["start"]
    assert {"scene_3_source", "scene_3_media"} <= other["scene_3"]


async def test_options_flow_hides_fields_for_sonos(hass: HomeAssistant) -> None:
    _register_player(hass, "sonos")
    entry, _ = await _setup(hass, addr_scene="3/0/1", scene_1_source="Jazz")
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert "start_media" not in _fields(result["data_schema"])["start"]
    assert "scene_1_media" not in _fields(result["data_schema"])["scene_1"]
    done = await hass.config_entries.options.async_configure(
        result["flow_id"], page(addr_scene="3/0/1", scene_1_source="Jazz", start_source="Radio")
    )
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert done["data"]["start_source"] == "Radio"


async def test_reconfigure_drops_unfitting_fields(hass: HomeAssistant) -> None:
    _register_player(hass, "sonos")
    entry, _ = await _setup(
        hass, addr_scene="3/0/1", start_source="Jazz", scene_1_source="Radio",
        scene_2_media="library://playlist/7", start_media="x", max_volume=70,
    )
    _register_player(hass, "music_assistant", "kitchen")
    hass.states.async_set("media_player.kitchen", "idle", {})

    result = await entry.start_reconfigure_flow(hass)
    await hass.config_entries.flow.async_configure(
        result["flow_id"], {"player": "media_player.kitchen"}
    )
    await hass.async_block_till_done()
    # Music Assistant: Quellen entfallen, Medien und alles andere bleibt
    assert "start_source" not in entry.options and "scene_1_source" not in entry.options
    assert entry.options["scene_2_media"] == "library://playlist/7"
    assert entry.options["start_media"] == "x" and entry.options["max_volume"] == 70


async def test_device_gets_area_of_player(hass: HomeAssistant) -> None:
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    area = ar.async_get(hass).async_create("Wohnzimmer")
    player = _register_player(hass, "sonos")
    er.async_get(hass).async_update_entity(player.entity_id, area_id=area.id)
    entry, _ = await _setup(hass)
    device = _device_of(hass, entry)
    assert device.area_id == area.id

    # später selbst geändert: bleibt nach dem Neuladen unverändert
    other = ar.async_get(hass).async_create("Küche")
    dr.async_get(hass).async_update_device(device.id, area_id=other.id)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert dr.async_get(hass).async_get(device.id).area_id == other.id


async def test_device_area_from_player_device(hass: HomeAssistant) -> None:
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.common import MockConfigEntry as MCE

    area = ar.async_get(hass).async_create("Büro")
    host = MCE(domain="sonos", title="Sonos")
    host.add_to_hass(hass)
    sonos_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=host.entry_id, identifiers={("sonos", "x")}
    )
    dr.async_get(hass).async_update_device(sonos_device.id, area_id=area.id)
    player = er.async_get(hass).async_get_or_create(
        "media_player", "sonos", "u1", suggested_object_id="living_room",
        device_id=sonos_device.id, config_entry=host,
    )
    assert player.area_id is None  # Bereich nur am Gerät
    entry, _ = await _setup(hass)
    device = _device_of(hass, entry)
    assert device.area_id == area.id


async def test_device_without_player_area_has_none(hass: HomeAssistant) -> None:
    from homeassistant.helpers import device_registry as dr

    entry, _ = await _setup(hass)
    device = _device_of(hass, entry)
    assert device.area_id is None


# --- Music-Assistant-Bibliothek als Auswahl --------------------------------------------


def _browse(title, uri, can_play=True):
    from homeassistant.components.media_player import BrowseMedia

    return BrowseMedia(
        media_class="playlist", media_content_id=uri, media_content_type="music",
        title=title, can_play=can_play, can_expand=False,
    )


def _listing(*children):
    from homeassistant.components.media_player import BrowseMedia

    return BrowseMedia(
        media_class="directory", media_content_id="x", media_content_type="music_assistant",
        title="x", can_play=False, can_expand=True, children=list(children),
    )


async def _add_fake_player(hass, entity_id, browse):
    from homeassistant.components.media_player import DATA_COMPONENT, MediaPlayerEntity
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "media_player", {})

    class Fake(MediaPlayerEntity):
        _attr_should_poll = False

        async def async_browse_media(self, media_content_type=None, media_content_id=None):
            return await browse(media_content_type, media_content_id)

    player = Fake()
    player.hass = hass
    player.entity_id = entity_id
    await hass.data[DATA_COMPONENT].async_add_entities([player])
    return player


async def test_library_options_from_player(hass: HomeAssistant) -> None:
    from custom_components.knx_media_player.helpers import async_library_options

    calls = []

    async def browse(content_type, content_id):
        calls.append((content_type, content_id))
        if content_id == "playlists":
            return _listing(
                _browse("Pop Rock Radio", "library://playlist/399"),
                _browse("Gesperrt", "library://playlist/5", can_play=False),
            )
        return _listing(_browse("ffn", "library://radio/9"), _browse("Doppelt", "library://playlist/399"))

    await _add_fake_player(hass, "media_player.buero", browse)
    hass.config.language = "de"
    options = await async_library_options(hass, "media_player.buero")
    assert options == [
        {"value": "library://playlist/399", "prefix": "Playlist", "title": "Pop Rock Radio"},
        {"value": "library://radio/9", "prefix": "Radiosender", "title": "ffn"},
    ]
    assert calls == [("music_assistant", "playlists"), ("music_assistant", "radio")]
    hass.config.language = "en"
    assert (await async_library_options(hass, "media_player.buero"))[1]["prefix"] == "Radio station"


async def test_library_options_fall_back_to_empty(hass: HomeAssistant) -> None:
    from unittest.mock import patch

    from custom_components.knx_media_player import helpers

    # unbekannter Player, Media-Player-Komponente nicht geladen
    assert await helpers.async_library_options(hass, "media_player.gibtsnicht") == []

    async def broken(content_type, content_id):
        raise RuntimeError("Music Assistant nicht erreichbar")

    await _add_fake_player(hass, "media_player.kaputt", broken)
    assert await helpers.async_library_options(hass, "media_player.kaputt") == []

    async def slow(content_type, content_id):
        import asyncio

        await asyncio.sleep(5)

    await _add_fake_player(hass, "media_player.langsam", slow)
    with patch.object(helpers, "LIBRARY_TIMEOUT", 0.05):
        assert await helpers.async_library_options(hass, "media_player.langsam") == []


def _suggested(result, section, field):
    """Vorbelegung eines Felds der Optionsseite."""
    marker = next(m for k, m in result["data_schema"].schema.items() if str(k) == section)
    key = next(k for k in marker.schema.schema if str(k) == field)
    return key.description["suggested_value"]


def _media_selector(result, section, field):
    marker = next(m for k, m in result["data_schema"].schema.items() if str(k) == section)
    return next(v for k, v in marker.schema.schema.items() if str(k) == field)


async def test_options_flow_offers_library_for_music_assistant(hass: HomeAssistant) -> None:
    from unittest.mock import patch

    _register_player(hass, "music_assistant")
    entry, _ = await _setup(hass, addr_scene="3/0/1")
    library = [{"value": "library://playlist/399", "prefix": "Playlist", "title": "Pop Rock Radio"}]
    with patch(
        "custom_components.knx_media_player.config_flow.async_library_options",
        return_value=library,
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
    for section, field in (("start", "start_media"), ("scene_2", "scene_2_media")):
        selector_ = _media_selector(result, section, field)
        config = selector_.config
        # Wert ist der Titel (das Feld zeigt ihn), die Beschriftung hat den Vorsatz
        assert config["options"] == [{"value": "Pop Rock Radio", "label": "Playlist · Pop Rock Radio"}]
        assert config["custom_value"] is True
    # Auswahl und freie Eingabe lassen sich speichern; zur Auswahl merkt sich der Eintrag die Adresse
    done = await hass.config_entries.options.async_configure(
        result["flow_id"],
        page(addr_scene="3/0/1", start_media="Pop Rock Radio",
             scene_2_media="spotify--x://album/1", scene_2_media_type="album"),
    )
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert done["data"]["start_media"] == "Pop Rock Radio"
    assert done["data"]["media_uris"] == {"Pop Rock Radio": "library://playlist/399"}
    assert done["data"]["scene_2_media"] == "spotify--x://album/1"  # frei: ohne Zuordnung


async def test_options_flow_text_field_without_library(hass: HomeAssistant) -> None:
    from unittest.mock import patch

    _register_player(hass, "music_assistant")
    entry, _ = await _setup(hass)
    with patch(
        "custom_components.knx_media_player.config_flow.async_library_options", return_value=[]
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
    assert _media_selector(result, "start", "start_media") is str


async def test_library_is_only_read_for_music_assistant(hass: HomeAssistant) -> None:
    from unittest.mock import patch

    from homeassistant.helpers import entity_registry as er

    for platform in ("sonos", None):
        registered = er.async_get(hass).async_get(PLAYER)
        if platform:
            _register_player(hass, platform)
        elif registered:  # zweiter Durchlauf: Player ohne bekannte Integration
            er.async_get(hass).async_remove(PLAYER)
        entry, _ = await _setup(hass)
        with patch(
            "custom_components.knx_media_player.config_flow.async_library_options"
        ) as mocked:
            await hass.config_entries.options.async_init(entry.entry_id)
        mocked.assert_not_called()
        await hass.config_entries.async_remove(entry.entry_id)


# --- Senderliste und Radio Browser -----------------------------------------------------

WDR4 = "https://wdr-wdr4-live.icecastssl.wdr.de/wdr/wdr4/live/mp3/128/stream.mp3"
RB_URI = "media-source://radio_browser/abc-123"


def test_station_list_is_complete() -> None:
    from custom_components.knx_media_player.stations import STATIONS

    assert list(STATIONS) == [
        "WDR 2 Münsterland", "WDR 4", "1LIVE", "Radio WMW", "Energy NRW", "Energy Digital",
        "Radio Bob", "Radio Bob NRW",
    ]
    assert STATIONS["WDR 4"] == WDR4
    assert all(url.startswith("https://") for url in STATIONS.values())


def test_scene_precedence_station_source_media() -> None:
    values = {
        "addr_scene": "3/0/1",
        "scene_1_station": "WDR 4", "scene_1_source": "Jazz", "scene_1_media": "library://x",
        "scene_2_source": "Jazz", "scene_2_media": "library://x",
        "scene_3_media": "library://x",
    }
    get = lambda key, default=None: values.get(key, default)  # noqa: E731
    actions = {}
    for command in build_commands(get):
        if command.get("scene"):
            actions.setdefault(command["scene"], []).append(command["action"])
    # es läuft immer nur eines: Sender vor Quelle vor Medium
    assert actions == {1: ["station"], 2: ["source"], 3: ["media"]}


async def test_fixed_station_scene_and_start(hass: HomeAssistant) -> None:
    _, m = await _setup(
        hass, addr_scene="3/0/1", scene_1_station="WDR 4", scene_1_volume=20,
        start_station="Radio Bob", start_volume=10, addr_toggle="1/0/4",
    )
    await _telegram(hass, "3/0/1", (0,))
    assert m["volume_set"][-1].data["volume_level"] == 0.2
    assert m["play_media"][-1].data == {
        "entity_id": PLAYER, "media_content_id": WDR4, "media_content_type": "music",
    }
    await _telegram(hass, "1/0/4", 1)  # Player pausiert: Startlautstärke, dann Startsender
    assert m["volume_set"][-1].data["volume_level"] == 0.1
    assert m["play_media"][-1].data["media_content_id"].startswith("https://streams.radiobob.de/bob-national/")
    assert not m["media_play"]


async def test_station_beats_source_and_media_at_start(hass: HomeAssistant) -> None:
    _, m = await _setup(
        hass, start_station="WDR 4", start_source="Jazz", start_media="x", addr_toggle="1/0/4"
    )
    await _telegram(hass, "1/0/4", 1)
    assert m["play_media"][-1].data["media_content_id"] == WDR4
    assert not m["select_source"]


@pytest.mark.parametrize("platform", ["sonos", "music_assistant"])
async def test_radio_browser_station_sonos_and_music_assistant_resolve_themselves(
    hass: HomeAssistant, platform: str
) -> None:
    _register_player(hass, platform)
    _, m = await _setup(hass, addr_scene="3/0/1", scene_1_station=RB_URI)
    await _telegram(hass, "3/0/1", (0,))
    # die Adresse geht unverändert an den Player (Sonos behandelt sie als Radio)
    assert m["play_media"][-1].data["media_content_id"] == RB_URI
    assert m["play_media"][-1].data["media_content_type"] == "music"


async def test_radio_browser_station_resolved_for_other_players(hass: HomeAssistant) -> None:
    from unittest.mock import AsyncMock, patch

    from homeassistant.components.media_source import PlayMedia

    _, m = await _setup(hass, addr_scene="3/0/1", scene_1_station=RB_URI)
    resolve = AsyncMock(return_value=PlayMedia("https://radio.example/stream.mp3", "audio/mpeg"))
    with patch("custom_components.knx_media_player.controller.media_source.async_resolve_media", resolve):
        await _telegram(hass, "3/0/1", (0,))
    resolve.assert_awaited_once_with(hass, RB_URI, PLAYER)
    assert m["play_media"][-1].data["media_content_id"] == "https://radio.example/stream.mp3"
    assert m["play_media"][-1].data["media_content_type"] == "audio/mpeg"

    # Sender nicht mehr verfügbar: nichts spielt, nichts bricht ab
    m["play_media"].clear()
    boom = AsyncMock(side_effect=RuntimeError("weg"))
    with patch("custom_components.knx_media_player.controller.media_source.async_resolve_media", boom):
        await _telegram(hass, "3/0/1", (0,))
    assert not m["play_media"]


async def test_free_url_and_unknown_station(hass: HomeAssistant) -> None:
    _, m = await _setup(
        hass, addr_scene="3/0/1", scene_1_station="https://example.org/live.mp3",
        scene_2_station="Gibt es nicht",
    )
    await _telegram(hass, "3/0/1", (0,))
    assert m["play_media"][-1].data["media_content_id"] == "https://example.org/live.mp3"
    count = len(m["play_media"])
    await _telegram(hass, "3/0/1", (1,))  # Szene 2: Name nicht in der Liste
    assert len(m["play_media"]) == count


def _rb_loaded():
    """Radio Browser gilt als eingerichtet (ohne echten Eintrag, dessen Paket hier fehlt)."""
    from unittest.mock import patch

    return patch(
        "custom_components.knx_media_player.helpers._radio_browser_loaded", return_value=True
    )


async def test_radio_browser_options(hass: HomeAssistant) -> None:
    from unittest.mock import patch

    from custom_components.knx_media_player import helpers

    # Integration nicht eingerichtet: leer
    assert await helpers.async_radio_browser_options(hass) == []
    hass.config.language = "de"
    calls = []

    async def browse(hass_, uri, **kwargs):
        calls.append(uri)
        if uri.endswith("/local"):
            return _listing(_browse("WDR 2 Münsterland", "media-source://radio_browser/u1"))
        return _listing(
            _browse("WDR 2 Münsterland", "media-source://radio_browser/u1"),
            _browse("Hit Radio FFH", "media-source://radio_browser/u2"),
            _browse("Nur Ordner", "media-source://radio_browser/u3", can_play=False),
        )

    with _rb_loaded(), patch.object(helpers.media_source, "async_browse_media", browse):
        options = await helpers.async_radio_browser_options(hass)
        assert options == [
            {"value": "media-source://radio_browser/u1", "prefix": "Radio Browser · Lokal", "title": "WDR 2 Münsterland"},
            {"value": "media-source://radio_browser/u2", "prefix": "Radio Browser · Beliebt", "title": "Hit Radio FFH"},
        ]
        assert calls == [
            "media-source://radio_browser/local", "media-source://radio_browser/popular",
        ]
        await helpers.async_radio_browser_options(hass)  # aus dem Speicher
        assert len(calls) == 2


async def test_radio_browser_options_failures(hass: HomeAssistant) -> None:
    from unittest.mock import patch

    from custom_components.knx_media_player import helpers

    async def broken(*args, **kwargs):
        raise RuntimeError("nicht erreichbar")

    async def slow(*args, **kwargs):
        import asyncio

        await asyncio.sleep(5)

    with _rb_loaded(), patch.object(helpers.media_source, "async_browse_media", broken):
        assert await helpers.async_radio_browser_options(hass) == []
    with _rb_loaded(), patch.object(helpers.media_source, "async_browse_media", slow), patch.object(
        helpers, "RADIO_BROWSER_TIMEOUT", 0.05
    ):
        assert await helpers.async_radio_browser_options(hass) == []
    # Fehler werden nicht gemerkt: der nächste Versuch fragt wieder
    async def fine(hass_, uri, **kwargs):
        return _listing(_browse("A", "media-source://radio_browser/a"))

    with _rb_loaded(), patch.object(helpers.media_source, "async_browse_media", fine):
        assert len(await helpers.async_radio_browser_options(hass)) == 1


async def test_options_flow_station_field_and_summary(hass: HomeAssistant) -> None:
    from unittest.mock import patch

    _register_player(hass, "sonos")
    entry, _ = await _setup(
        hass, addr_scene="3/0/1", start_station="WDR 4", scene_1_station=RB_URI,
        scene_2_source="Jazz", scene_3_station="https://example.org/live.mp3",
    )
    # Titel gleich einem festen Sender: bekommt eine Nummer
    rb = [{"value": RB_URI, "prefix": "Radio Browser · Lokal", "title": "WDR 2 Münsterland"}]
    hass.config.language = "de"
    with patch(
        "custom_components.knx_media_player.helpers.async_radio_browser_options", return_value=rb
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
    # „Sender“ steht bei jedem Player, hier Sonos: feste Liste, dann Radio Browser; Wert = Titel
    stations = _media_selector(result, "start", "start_station").config["options"]
    values = [o["value"] for o in stations]
    assert values == [
        "WDR 2 Münsterland", "WDR 4", "1LIVE", "Radio WMW", "Energy NRW", "Energy Digital",
        "Radio Bob", "Radio Bob NRW", "WDR 2 Münsterland (2)",
    ]
    assert stations[-1]["label"] == "Radio Browser · Lokal · WDR 2 Münsterland (2)"
    assert _media_selector(result, "scene_4", "scene_4_station").config["custom_value"] is True
    assert "media_info" not in result["description_placeholders"]
    # ältere Einstellung mit Adresse: das Feld zeigt gleich den Titel (nummeriert, weil schon vergeben)
    assert _suggested(result, "scene_1", "scene_1_station") == "WDR 2 Münsterland (2)"
    # feste Sender und freie Eingaben bleiben unverändert
    assert _suggested(result, "start", "start_station") == "WDR 4"
    assert _suggested(result, "scene_3", "scene_3_station") == "https://example.org/live.mp3"


async def test_legacy_address_is_saved_as_title(hass: HomeAssistant) -> None:
    from unittest.mock import patch

    _register_player(hass, "sonos")
    entry, _ = await _setup(hass, addr_scene="3/0/1", scene_1_station=RB_URI)
    rb = [{"value": RB_URI, "prefix": "Radio Browser · Lokal", "title": "Hit Radio FFH"}]
    with patch("custom_components.knx_media_player.helpers.async_radio_browser_options", return_value=rb):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert _suggested(result, "scene_1", "scene_1_station") == "Hit Radio FFH"
        # unverändert speichern: aus der Adresse wird Titel plus Zuordnung
        done = await hass.config_entries.options.async_configure(
            result["flow_id"], page(addr_scene="3/0/1", scene_1_station="Hit Radio FFH")
        )
    assert done["data"]["scene_1_station"] == "Hit Radio FFH"
    assert done["data"]["station_uris"] == {"Hit Radio FFH": RB_URI}


async def test_station_titles_are_stored_with_their_address(hass: HomeAssistant) -> None:
    from unittest.mock import patch

    _register_player(hass, "sonos")
    entry, _ = await _setup(hass, addr_scene="3/0/1")
    rb = [
        {"value": RB_URI, "prefix": "Radio Browser · Lokal", "title": "Hit Radio FFH"},
        {"value": "media-source://radio_browser/zzz", "prefix": "Radio Browser · Beliebt", "title": "Hit Radio FFH"},
    ]
    with patch("custom_components.knx_media_player.helpers.async_radio_browser_options", return_value=rb):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        done = await hass.config_entries.options.async_configure(
            result["flow_id"],
            page(addr_scene="3/0/1", start_station="Hit Radio FFH (2)", scene_1_station="Hit Radio FFH",
                 scene_2_station="WDR 4"),
        )
    data = done["data"]
    assert data["start_station"] == "Hit Radio FFH (2)" and data["scene_1_station"] == "Hit Radio FFH"
    # gleiche Titel: der zweite ist nummeriert; feste Sender brauchen keine Zuordnung
    assert data["station_uris"] == {
        "Hit Radio FFH (2)": "media-source://radio_browser/zzz",
        "Hit Radio FFH": RB_URI,
    }
    assert "media_uris" not in data


async def test_stored_mapping_survives_unreachable_directory(hass: HomeAssistant) -> None:
    from unittest.mock import patch

    _register_player(hass, "sonos")
    entry, _ = await _setup(
        hass, addr_scene="3/0/1", scene_1_station="Hit Radio FFH",
        station_uris={"Hit Radio FFH": RB_URI, "Nicht mehr genutzt": "media-source://radio_browser/old"},
    )
    # Radio Browser nicht erreichbar: die Liste ist leer, die gewählte Zuordnung bleibt, Unbenutztes entfällt
    with patch("custom_components.knx_media_player.helpers.async_radio_browser_options", return_value=[]):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        done = await hass.config_entries.options.async_configure(
            result["flow_id"], page(addr_scene="3/0/1", scene_1_station="Hit Radio FFH"),
        )
    assert done["data"]["station_uris"] == {"Hit Radio FFH": RB_URI}


async def test_make_choices() -> None:
    from custom_components.knx_media_player.helpers import make_choices

    choices = make_choices(
        [
            {"value": "u1", "prefix": "Playlist", "title": "Rock"},
            {"value": "u2", "prefix": "Radiosender", "title": "Rock"},
            {"value": "u3", "prefix": "Radiosender", "title": "Rock"},
            {"value": "u4", "prefix": "Radiosender", "title": "WDR 4"},
        ],
        reserved={"WDR 4"},
    )
    assert [o["value"] for o in choices.options] == ["Rock", "Rock (2)", "Rock (3)", "WDR 4 (2)"]
    assert choices.options[1]["label"] == "Radiosender · Rock (2)"
    assert choices.uris == {"Rock": "u1", "Rock (2)": "u2", "Rock (3)": "u3", "WDR 4 (2)": "u4"}
    # ältere Einstellungen mit der Adresse zeigen ebenfalls die Beschriftung
    assert choices.labels["u2"] == "Radiosender · Rock (2)" and choices.labels["Rock (3)"] == "Radiosender · Rock (3)"


async def test_titles_are_played_via_stored_address(hass: HomeAssistant) -> None:
    from unittest.mock import AsyncMock, patch

    from homeassistant.components.media_source import PlayMedia

    # Medium (Music Assistant): Titel -> Adresse, mit Typ
    _register_player(hass, "music_assistant")
    _, m = await _setup(
        hass, addr_scene="3/0/1", scene_1_media="Pop Rock Radio", scene_1_media_type="playlist",
        media_uris={"Pop Rock Radio": "library://playlist/399"},
        scene_2_station="Hit Radio FFH", station_uris={"Hit Radio FFH": RB_URI},
    )
    await _telegram(hass, "3/0/1", (0,))
    assert m["play_media"][-1].data["media_content_id"] == "library://playlist/399"
    assert m["play_media"][-1].data["media_content_type"] == "playlist"
    # Sender (Radio Browser) bei Music Assistant: Adresse unverändert an den Player
    await _telegram(hass, "3/0/1", (1,))
    assert m["play_media"][-1].data["media_content_id"] == RB_URI


async def test_station_title_resolved_for_other_players(hass: HomeAssistant) -> None:
    from unittest.mock import AsyncMock, patch

    from homeassistant.components.media_source import PlayMedia

    _, m = await _setup(
        hass, addr_scene="3/0/1", scene_1_station="Hit Radio FFH", station_uris={"Hit Radio FFH": RB_URI}
    )
    resolve = AsyncMock(return_value=PlayMedia("https://radio.example/ffh.mp3", "audio/mpeg"))
    with patch("custom_components.knx_media_player.controller.media_source.async_resolve_media", resolve):
        await _telegram(hass, "3/0/1", (0,))
    resolve.assert_awaited_once_with(hass, RB_URI, PLAYER)
    assert m["play_media"][-1].data["media_content_id"] == "https://radio.example/ffh.mp3"


async def test_unmapped_media_text_is_used_as_typed(hass: HomeAssistant) -> None:
    _, m = await _setup(hass, addr_scene="3/0/1", scene_1_media="Radio Paradise")
    await _telegram(hass, "3/0/1", (0,))
    assert m["play_media"][-1].data["media_content_id"] == "Radio Paradise"


async def test_scene_with_station_needs_trigger(hass: HomeAssistant) -> None:
    entry, _ = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    bad = await hass.config_entries.options.async_configure(
        result["flow_id"], page(scene_4_station="WDR 4")
    )
    assert bad["errors"] == {"base": "scene_no_trigger"}
