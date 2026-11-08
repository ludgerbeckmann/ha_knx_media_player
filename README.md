# KNX Media Player

Home-Assistant-Integration, mit der sich **Media Player über KNX steuern** lassen: Play, Pause, Stopp, Vor, Zurück, Lautstärke und mehr – und der aktuelle Zustand wird zurück auf den Bus gemeldet.

Die Integration spricht nur die Standarddienste von `media_player` an. Sie funktioniert daher mit **Sonos**, **Music Assistant** und jeder anderen Integration, die einen Media Player bereitstellt. Sie baut keine eigene Busverbindung auf, sondern nutzt die offizielle **KNX-Integration** von Home Assistant (`knx.event_register`, `knx.send`, Ereignis `knx_event`).

Das Prinzip stammt aus dem „KNX/Sonos-Connector“ von [ha_housekeeper](https://github.com/ludgerbeckmann/ha_housekeeper), ist hier aber eigenständig, schlank und nicht auf Sonos beschränkt.

## Voraussetzungen

- Home Assistant 2025.3 oder neuer
- eingerichtete [KNX-Integration](https://www.home-assistant.io/integrations/knx/)
- ein Media Player in Home Assistant

## Installation

**HACS:** Repository als benutzerdefiniertes Repository (Kategorie *Integration*) hinzufügen, „KNX Media Player“ installieren, Home Assistant neu starten.

**Manuell:** `custom_components/knx_media_player` nach `config/custom_components/` kopieren und neu starten.

## Einrichtung

1. *Einstellungen → Geräte & Dienste → Integration hinzufügen → KNX Media Player*.
2. Media Player auswählen (optional einen Namen vergeben). **Pro Media Player gibt es einen Eintrag**; für weitere Lautsprecher den Vorgang wiederholen.
3. Beim Eintrag auf *Konfigurieren* klicken und die Gruppenadressen eintragen. Leere Felder werden nicht verwendet. Ist in der KNX-Integration ein ETS-Projekt importiert, bieten die Felder die passenden Adressen zur Auswahl an.

## Befehle (KNX → Media Player)

| Feld | Datentyp | Wirkung |
|---|---|---|
| Play/Pause Schalter | 1 Bit | 1 = Wiedergabe, 0 = Pause |
| Nächster/Vorheriger Titel | 1 Bit | 1 = nächster, 0 = vorheriger Titel |
| Stopp | 1 Bit | 1 = Stopp |
| Play/Pause Taster | 1 Bit | 1 = zwischen Wiedergabe und Pause umschalten |
| Lautstärke absolut | 5.001 | 0–100 %, begrenzt durch die Lautstärkegrenze |
| Lauter/Leiser | 1 Bit | 1 = ein Schritt lauter, 0 = ein Schritt leiser |
| Relatives Dimmen | 3.007 | ein Schritt je Telegramm, Schrittcode 0 = Stopp |
| Stumm | 1 Bit | 1 = stumm, 0 = Stumm aus |
| Szenenadresse | 17.001 | startet Szene 1–5 |

**Einstellungen des Players:** *Lautstärkegrenze* (Maximum über KNX), *Lautstärkeschritt* (für Lauter/Leiser und Dimmen) und *Stoppen statt Pause* (z. B. für Radiosender).

**Start der Wiedergabe:** Startet ein Play-Befehl einen Player, der gerade nicht spielt, kann vorher eine *Startlautstärke* gesetzt und eine *Startquelle* (z. B. ein Sonos-Favorit) gewählt werden. So wird nie eine alte, hohe Lautstärke übernommen.

**Szenen 1–5:** Jede Szene kann eine Quelle (`media_player.select_source`, z. B. ein Sonos-Favorit) und/oder eine Lautstärke setzen. Ausgelöst wird sie über die Szenennummer auf der Szenenadresse oder über eine eigene 1-Bit-Adresse (1 = starten, 0 = Pause).

## Rückmeldungen (Media Player → KNX)

Änderungen werden automatisch gesendet; Lesetelegramme (`GroupValueRead`) werden beantwortet.

| Feld | Datentyp |
|---|---|
| Spielt / Pausiert | 1 Bit |
| Lautstärke | 5.001 |
| Stumm | 1 Bit |
| Titel, Interpret, Album, Quelle | 16.001 (14 Zeichen) |

Spielt der Player nicht, senden die Textadressen den *Text, wenn nichts spielt* (leer, wenn nicht gesetzt).

## Entitäten

Je Eintrag entstehen ein Gerät mit

- **Schalter „KNX-Steuerung aktiv“**: pausiert alle Befehle und Rückmeldungen,
- **Sensor „Letzter KNX-Befehl“**: Zeitpunkt, Adresse, Aktion und Wert des zuletzt ausgeführten Befehls.

## Hinweise

- Die Anmeldung der Adressen bei der KNX-Integration gilt nur zur Laufzeit und wird alle 5 Minuten sowie nach einem Neuladen der KNX-Integration wiederholt.
- Ausgehende Telegramme (auch die eigenen Rückmeldungen) werden nie als Befehl ausgewertet.
- Ist der Media Player `unavailable`/`unknown`, werden Befehle ignoriert.

## Entwicklung

```bash
pip install pytest-homeassistant-custom-component
pytest
```

Lizenz: siehe [LICENSE](LICENSE).
