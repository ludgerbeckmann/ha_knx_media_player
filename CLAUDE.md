# CLAUDE.md – Projektkontext

Home-Assistant Custom Integration `knx_media_player` („KNX Media Player“): steuert beliebige
`media_player`-Entitäten (Sonos, Music Assistant, …) über KNX-Gruppenadressen und meldet den Zustand zurück.
Vorbild ist der „KNX/Sonos-Connector“ in `ludgerbeckmann/ha_housekeeper` (`knx_sonos.py`), hier eigenständig
und ohne Hub/Untereinträge, Profile oder ältere Listen.

## Architektur

- **Ein Config-Entry je Media Player** (`data = {"player": <entity_id>}`, `unique_id` = Entity-ID). Alle Einstellungen
  liegen flach in `entry.options` (Options-Flow, eine Seite mit Abschnitten); der Controller liest `{**data, **options}`.
  Änderungen an den Optionen laden den Eintrag neu (Update-Listener in `__init__.py`).
- `controller.py`: `KnxMediaPlayerController` – nutzt nur `knx.event_register`, `knx.send`, Ereignis `knx_event`
  und die Dienste von `media_player`. `build_commands()` / `build_status()` bilden aus den Feldern Befehle und
  Rückmeldungen. Eigene Rückmeldungen (`direction != "Incoming"`) werden nie als Befehl gewertet. Die Adressanmeldung wird
  alle 5 Minuten und nach `event_knx_reloaded` wiederholt. Zustand (`enabled`, `last_command`) liegt in einem `Store`.
- `knx_codec.py`: reine Funktionen (Gruppenadressen normalisieren, DPT 1/3/5/16/17 dekodieren) – ohne HA-Abhängigkeit.
- `knx_project.py`: liest die Gruppenadressen des importierten ETS-Projekts nur zur Auswahl im Dialog.
- `config_flow.py`: Einrichtung (Player + Name), Options-Flow mit Abschnitten (`section()`), Prüfung
  (`invalid_address`, `scene_no_trigger`), `clean_options()` entfernt leere Felder.
- Entitäten: `switch.py` (KNX-Steuerung aktiv), `sensor.py` (letzter Befehl), Basis in `entity.py`
  (Spiegel des Controllers über ein Dispatcher-Signal).
- Übersetzungen `translations/de.json` und `en.json` müssen dieselbe Struktur haben.

## Arbeitsweise

- `manifest.json` `version` bei **jeder** Änderung anheben (SemVer); `auto-release.yml` erstellt daraus Tag + Release.
- Tests: `pip install pytest-homeassistant-custom-component && pytest`. CI: hassfest, HACS, pytest.
- Icon: `brand/` und `custom_components/knx_media_player/brand/` (gleiche Dateien). Farben aus dem KNX-Logo (Grün `#0CB14B`, Grau `#8E979D`, Blau `#006BB6`), aber bewusst kein KNX-Logo oder -Schriftzug (Marke der KNX Association).
