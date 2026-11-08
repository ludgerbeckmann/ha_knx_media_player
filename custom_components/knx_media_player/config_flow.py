"""Dialoge: Media Player auswählen (Einrichtung) und KNX-Adressen festlegen (Optionen)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector

from .const import (
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
    CONF_NAME,
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
    MEDIA_TYPES,
    SCENE_COUNT,
    scene_key,
)
from .knx_codec import is_valid_ga
from .knx_project import address_label, async_project_addresses

_PLAYER_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="media_player")
)

# Abschnitte der Optionsseite
SECTION_PLAYER = "player_settings"
SECTION_PLAYBACK = "playback"
SECTION_START = "start"
SECTION_VOLUME = "volume"
SECTION_STATUS_PLAY = "status_play"
SECTION_STATUS_LEVEL = "status_level"
SECTION_STATUS_TEXT = "status_text"
SECTION_SCENES = "scenes"

_PLAYBACK_FIELDS = [CONF_ADDR_PLAY_PAUSE, CONF_ADDR_NEXT_PREV, CONF_ADDR_STOP, CONF_ADDR_TOGGLE]
_VOLUME_FIELDS = [CONF_ADDR_VOLUME, CONF_ADDR_VOLUME_STEP, CONF_ADDR_VOLUME_DIM, CONF_ADDR_MUTE]
_STATUS_PLAY_FIELDS = [CONF_STATUS_PLAYING, CONF_STATUS_PAUSED]
_STATUS_LEVEL_FIELDS = [CONF_STATUS_VOLUME, CONF_STATUS_MUTED]
_STATUS_TEXT_FIELDS = [
    CONF_STATUS_TITLE, CONF_STATUS_ARTIST, CONF_STATUS_ALBUM, CONF_STATUS_SOURCE
]
_SCENE_ADDRESSES = [scene_key(n, "address") for n in range(1, SCENE_COUNT + 1)]
_SCENE_SOURCES = [scene_key(n, "source") for n in range(1, SCENE_COUNT + 1)]
_SCENE_VOLUMES = [scene_key(n, "volume") for n in range(1, SCENE_COUNT + 1)]

# alle Felder mit einer Gruppenadresse (leer = nicht verwendet)
ADDRESS_FIELDS = [
    *_PLAYBACK_FIELDS,
    *_VOLUME_FIELDS,
    CONF_ADDR_SCENE,
    *_SCENE_ADDRESSES,
    *_STATUS_PLAY_FIELDS,
    *_STATUS_LEVEL_FIELDS,
    *_STATUS_TEXT_FIELDS,
]

# Haupt-Datentyp je Adressfeld (für den Filter der Projektadressen)
_FIELD_DPT: dict[str, int] = {
    **{key: 1 for key in (*_PLAYBACK_FIELDS, CONF_ADDR_VOLUME_STEP, CONF_ADDR_MUTE, *_SCENE_ADDRESSES)},
    CONF_ADDR_VOLUME: 5,
    CONF_ADDR_VOLUME_DIM: 3,
    CONF_ADDR_SCENE: 17,
    CONF_STATUS_PLAYING: 1,
    CONF_STATUS_PAUSED: 1,
    CONF_STATUS_MUTED: 1,
    CONF_STATUS_VOLUME: 5,
    **{key: 16 for key in _STATUS_TEXT_FIELDS},
}


def _suggest(key: str, defaults: dict[str, Any]) -> dict[str, Any]:
    value = defaults.get(key)
    return {} if value is None else {"suggested_value": value}


def _number(minimum: float, maximum: float, unit: str = "%") -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=1,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement=unit,
        )
    )


def _address(
    key: str, defaults: dict[str, Any], project: list[dict[str, Any]]
) -> tuple[Any, Any]:
    """Adressfeld: Dropdown mit den passenden Adressen des ETS-Projekts (frei beschreibbar),
    ohne Projekt ein Textfeld. Adressen ohne Datentyp im Projekt passen zu jedem Feld."""
    wanted = _FIELD_DPT.get(key)
    options = [
        selector.SelectOptionDict(value=item["address"], label=address_label(item))
        for item in project
        if item["main"] is None or item["main"] == wanted
    ]
    field = vol.Optional(key, description=_suggest(key, defaults))
    if not options:
        return field, str
    return field, selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options, custom_value=True, mode=selector.SelectSelectorMode.DROPDOWN
        )
    )


def _options_schema(
    defaults: dict[str, Any], sources: list[str], project: list[dict[str, Any]]
) -> vol.Schema:
    """Die Optionsseite: Abschnitte Grenzen, Wiedergabe, Start, Lautstärke, Rückmeldungen, Szenen."""

    def _section(fields: dict[Any, Any], collapsed: bool = True) -> Any:
        return section(vol.Schema(fields), {"collapsed": collapsed})

    def _addresses(keys: list[str]) -> dict[Any, Any]:
        return dict(_address(key, defaults, project) for key in keys)

    source = selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=sources, custom_value=True, mode=selector.SelectSelectorMode.DROPDOWN
        )
    )
    media_type = selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=MEDIA_TYPES,
            translation_key="media_type",
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )
    sections: dict[Any, Any] = {
        # nur der erste Abschnitt ist aufgeklappt
        vol.Required(SECTION_PLAYER): _section(
            {
                vol.Required(
                    CONF_MAX_VOLUME, default=defaults.get(CONF_MAX_VOLUME, DEFAULT_MAX_VOLUME)
                ): _number(0, 100),
                vol.Required(
                    CONF_VOLUME_STEP, default=defaults.get(CONF_VOLUME_STEP, DEFAULT_VOLUME_STEP)
                ): _number(1, 50),
                vol.Required(
                    CONF_STOP_INSTEAD, default=bool(defaults.get(CONF_STOP_INSTEAD, False))
                ): bool,
            },
            collapsed=False,
        ),
        vol.Required(SECTION_PLAYBACK): _section(_addresses(_PLAYBACK_FIELDS)),
        vol.Required(SECTION_START): _section(
            {
                vol.Optional(
                    CONF_START_VOLUME, description=_suggest(CONF_START_VOLUME, defaults)
                ): _number(0, 100),
                vol.Optional(
                    CONF_START_SOURCE, description=_suggest(CONF_START_SOURCE, defaults)
                ): source,
                vol.Optional(
                    CONF_START_MEDIA, description=_suggest(CONF_START_MEDIA, defaults)
                ): str,
                vol.Optional(
                    CONF_START_MEDIA_TYPE, description=_suggest(CONF_START_MEDIA_TYPE, defaults)
                ): media_type,
            }
        ),
        vol.Required(SECTION_VOLUME): _section(_addresses(_VOLUME_FIELDS)),
        vol.Required(SECTION_STATUS_PLAY): _section(_addresses(_STATUS_PLAY_FIELDS)),
        vol.Required(SECTION_STATUS_LEVEL): _section(_addresses(_STATUS_LEVEL_FIELDS)),
        vol.Required(SECTION_STATUS_TEXT): _section(
            {
                **_addresses(_STATUS_TEXT_FIELDS),
                vol.Optional(CONF_IDLE_TEXT, description=_suggest(CONF_IDLE_TEXT, defaults)): str,
            }
        ),
        vol.Required(SECTION_SCENES): _section(_addresses([CONF_ADDR_SCENE])),
    }
    for number in range(1, SCENE_COUNT + 1):
        src_key, vol_key, addr_key, media_key, type_key = (
            scene_key(number, f) for f in ("source", "volume", "address", "media", "media_type")
        )
        sections[vol.Required(f"scene_{number}")] = _section(
            {
                vol.Optional(src_key, description=_suggest(src_key, defaults)): source,
                vol.Optional(media_key, description=_suggest(media_key, defaults)): str,
                vol.Optional(type_key, description=_suggest(type_key, defaults)): media_type,
                vol.Optional(vol_key, description=_suggest(vol_key, defaults)): _number(0, 100),
                **_addresses([addr_key]),
            }
        )
    return vol.Schema(sections)


def _flatten_sections(user_input: dict[str, Any]) -> dict[str, Any]:
    """Abschnitte des Formulars zu den flachen Schlüsseln der Einstellungen auflösen."""
    flat: dict[str, Any] = {}
    for key, value in user_input.items():
        if isinstance(value, dict):
            flat.update(value)
        else:
            flat[key] = value
    return flat


def _validate(flat: dict[str, Any]) -> dict[str, str]:
    """Prüfung der Seite: Fehler mit Schlüssel `base`."""
    if any(flat.get(key) and not is_valid_ga(flat[key]) for key in ADDRESS_FIELDS):
        return {"base": "invalid_address"}
    for number in range(1, SCENE_COUNT + 1):
        has_action = (
            flat.get(scene_key(number, "source"))
            or flat.get(scene_key(number, "media"))
            or flat.get(scene_key(number, "volume")) is not None
        )
        if has_action and not flat.get(CONF_ADDR_SCENE) and not flat.get(scene_key(number, "address")):
            return {"base": "scene_no_trigger"}
    return {}


def clean_options(flat: dict[str, Any]) -> dict[str, Any]:
    """Eingaben speichern: leere Felder entfallen, Leerraum wird entfernt, Zahlen werden ganzzahlig."""
    options: dict[str, Any] = {}
    for key, value in flat.items():
        if isinstance(value, str):
            value = value.strip()
        if value in ("", None):
            continue
        options[key] = value
    for key in (CONF_MAX_VOLUME, CONF_VOLUME_STEP, CONF_START_VOLUME, *_SCENE_VOLUMES):
        if key in options:
            options[key] = int(options[key])
    return options


class KnxMediaPlayerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Einrichtung: ein Eintrag je Media Player."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            player = user_input[CONF_PLAYER]
            await self.async_set_unique_id(player)
            self._abort_if_unique_id_configured()
            state = self.hass.states.get(player)
            name = (user_input.get(CONF_NAME) or "").strip() or (
                state.name if state else player
            )
            return self.async_create_entry(title=name, data={CONF_PLAYER: player})
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PLAYER): _PLAYER_SELECTOR,
                    vol.Optional(CONF_NAME): str,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> KnxMediaPlayerOptionsFlow:
        return KnxMediaPlayerOptionsFlow()


class KnxMediaPlayerOptionsFlow(OptionsFlow):
    """Konfigurationsseite mit allen Einstellungen und Gruppenadressen."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self.config_entry
        errors: dict[str, str] = {}
        defaults: dict[str, Any] = dict(entry.options)
        if user_input is not None:
            flat = _flatten_sections(user_input)
            errors = _validate(flat)
            if not errors:
                return self.async_create_entry(data=clean_options(flat))
            defaults = flat
        state = self.hass.states.get(entry.data[CONF_PLAYER])
        sources = sorted((state.attributes.get("source_list") or []) if state else [])
        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(
                defaults, sources, await async_project_addresses(self.hass)
            ),
            errors=errors,
            description_placeholders={"player": entry.data[CONF_PLAYER]},
        )
