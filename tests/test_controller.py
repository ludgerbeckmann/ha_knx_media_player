"""Tests für Controller, Entitäten und Dialoge."""

from datetime import timedelta

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
         "source": "Radio", **(attrs or {})},
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
    hass.states.async_set(PLAYER, "playing", {"volume_level": 0.3})
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


async def test_stop_instead_of_pause(hass: HomeAssistant) -> None:
    _, m = await _setup(hass, stop_instead_of_pause=True, addr_play_pause="1/0/1")
    await _telegram(hass, "1/0/1", 0)
    assert len(m["media_stop"]) == 1 and not m["media_pause"]


async def test_start_volume_and_source(hass: HomeAssistant) -> None:
    _, m = await _setup(
        hass, max_volume=40, start_volume=60, start_source="Jazz", addr_toggle="1/0/4"
    )
    await _telegram(hass, "1/0/4", 1)
    assert m["volume_set"][-1].data["volume_level"] == 0.4  # durch die Grenze gekappt
    assert m["select_source"][-1].data["source"] == "Jazz"
    assert not m["media_play"]
    # läuft schon: keine Änderung von Lautstärke und Quelle, nur Pause
    hass.states.async_set(PLAYER, "playing", {"volume_level": 0.3})
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
        if key in ("max_volume", "volume_step", "stop_instead_of_pause"):
            sections["player_settings"][key] = value
        elif key.startswith("scene_"):
            sections[f"scene_{key.split('_')[1]}"][key] = value
        elif key in ("addr_play_pause", "addr_next_prev", "addr_stop", "addr_toggle"):
            sections["playback"][key] = value
        elif key in ("addr_volume", "addr_volume_step", "addr_volume_dim", "addr_mute"):
            sections["volume"][key] = value
        elif key in ("start_volume", "start_source", "start_media", "start_media_type"):
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
    sections["player_settings"].setdefault("stop_instead_of_pause", False)
    return sections


async def test_config_flow(hass: HomeAssistant) -> None:
    hass.states.async_set(PLAYER, "idle", {"friendly_name": "Wohnzimmer"})
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"
    created = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"player": PLAYER}
    )
    assert created["type"] is FlowResultType.CREATE_ENTRY
    assert created["title"] == "Wohnzimmer" and created["data"] == {"player": PLAYER}

    # derselbe Player ein zweites Mal
    again = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    dup = await hass.config_entries.flow.async_configure(again["flow_id"], {"player": PLAYER})
    assert dup["type"] is FlowResultType.ABORT and dup["reason"] == "already_configured"


async def test_config_flow_custom_name(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    created = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"player": PLAYER, "name": " Küche "}
    )
    assert created["title"] == "Küche"


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
