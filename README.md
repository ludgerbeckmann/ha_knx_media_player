[![Validate](https://github.com/ludgerbeckmann/ha_knx_media_player/actions/workflows/validate.yml/badge.svg)](https://github.com/ludgerbeckmann/ha_knx_media_player/actions/workflows/validate.yml)
[![Tests](https://github.com/ludgerbeckmann/ha_knx_media_player/actions/workflows/tests.yml/badge.svg)](https://github.com/ludgerbeckmann/ha_knx_media_player/actions/workflows/tests.yml)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)

Eine Custom Integration, mit der sich **Media Player über KNX steuern** lassen: Play, Pause, Stopp, Vor, Zurück,
Lautstärke und mehr. Der aktuelle Zustand wird zurück auf den Bus gemeldet. Jeder Media Player ist ein **eigener
Eintrag** mit eigenem Gerät und eigenen Einstellungen. Alle Einstellungen sind Formulare in Home Assistant, es ist
kein YAML nötig.

Die Integration spricht nur die Standarddienste von `media_player` an. Sie funktioniert daher mit **Sonos**,
**Music Assistant** und jeder anderen Integration, die einen Media Player bereitstellt. Sie baut keine eigene
Busverbindung auf, sondern nutzt die offizielle **KNX-Integration** von Home Assistant (`knx.event_register`,
`knx.send`, Ereignis `knx_event`).

Das Prinzip stammt aus dem „KNX/Sonos-Connector“ von
[ha_housekeeper](https://github.com/ludgerbeckmann/ha_housekeeper), ist hier aber eigenständig, schlank und nicht
auf Sonos beschränkt.

## Funktionen

| Funktion | Beschreibung |
| --- | --- |
| [Befehle](#befehle-knx--media-player) | Play/Pause, Vor/Zurück, Stopp, Umschalten, Lautstärke absolut, Lauter/Leiser, Dimmen, Stumm |
| [Szenen](#szenen-und-start-der-wiedergabe) | Szenen 1–5 setzen Lautstärke und starten einen Sender, eine Quelle (z. B. Sonos-Favorit) oder ein Medium (z. B. Music-Assistant-Playlist) |
| [Sender](#sender) | Feste Senderliste (WDR 2 Münsterland, WDR 4, 1LIVE, Radio WMW, Energy NRW und Digital, Radio Bob und NRW) und Radio Browser, für jeden Player |
| [Wiedergabeoption](#szenen-und-start-der-wiedergabe) | Startlautstärke und Startsender/-quelle/-medium, damit nie eine alte hohe Lautstärke übernommen wird |
| [Rückmeldungen](#rückmeldungen-media-player--knx) | Spielt/Pause, Lautstärke, Stumm, Titel, Interpret, Album und Quelle, auch als Antwort auf Lesetelegramme |
| [Grenzen](#einstellungen-des-players) | Lautstärkegrenze, Lautstärkeschritt, „Stoppen statt Pause“ |

## Installation

**Schnellstart:**

1. Per HACS oder manuell installieren (siehe unten) und Home Assistant neu starten.
2. *Einstellungen → Geräte & Dienste → Integration hinzufügen → KNX Media Player*, den **Media Player** wählen (die
   Suche in der Auswahl findet auch Bereiche und Gerätenamen) und im nächsten Fenster mit **OK** bestätigen.
3. Beim Eintrag über **Konfigurieren** die Gruppenadressen eintragen, danach jederzeit ändern.

**HACS:** Menü (⋮) → *Benutzerdefinierte Repositories* → diese Repository-URL,
Kategorie *Integration* → „KNX Media Player“ installieren → Home Assistant neu starten.

**Manuell:** `custom_components/knx_media_player` nach `<config>/custom_components/`
kopieren und neu starten.

Voraussetzungen sind Home Assistant 2025.3 oder neuer, die eingerichtete
[KNX-Integration](https://www.home-assistant.io/integrations/knx/) und ein Media Player in Home Assistant.

**Pro Media Player gibt es einen Eintrag**; für weitere Lautsprecher den Vorgang wiederholen. Der Eintrag heißt wie
der Media Player; den Namen änderst du über *Neu konfigurieren*. Player, für die es schon einen Eintrag gibt, fehlen in
der Auswahl. Vor dem Anlegen zeigt ein Bestätigungsfenster, was du gewählt hast: Name, **Integration** (z. B. Sonos
oder Music Assistant), Bereich und Entity-ID; dieselbe Zeile steht oben in den Optionen und bei *Neu konfigurieren*.
Das neue Gerät bekommt beim Anlegen den **Bereich** des Media Players
(der Entität, sonst ihres Geräts); später änderst du ihn wie bei jedem Gerät selbst, die Integration setzt ihn nicht
wieder zurück.

**Media Player wechseln:** Am Eintrag über das Menü (⋮) *Neu konfigurieren* einen anderen Media Player (z. B. von
Sonos zu Music Assistant) oder einen anderen Namen wählen. Alle Gruppenadressen und Einstellungen bleiben erhalten;
Quellen und Medien, die nur auf dem alten Player existieren, danach in den Optionen prüfen. Ein Media Player kann
nur zu einem Eintrag gehören.

## Bedienung der Einstellungen

**Konfigurieren** am Eintrag öffnet **eine Seite** mit Abschnitten; nur „Media Player“ ist aufgeklappt, die übrigen
sind eingeklappt. Leere Gruppenadressen werden nicht verwendet. Ist in der KNX-Integration ein ETS-Projekt
importiert, bieten die Adressfelder die passenden Gruppenadressen (nach Datentyp gefiltert) zur Auswahl an; freie
Eingabe ist weiter möglich.

Nach dem Speichern wird der Eintrag neu geladen und die Adressen werden bei der KNX-Integration neu angemeldet.
Die Seite prüft die Eingaben (ungültige Gruppenadresse, Szene ohne Auslöser).

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

### Einstellungen des Players

*Lautstärkegrenze* (Maximum über KNX), *Lautstärkeschritt* (für Lauter/Leiser und Dimmen) und
*Stoppen statt Pause* (z. B. für Radiosender).

## Szenen und Start der Wiedergabe

**Wiedergabeoption** (Abschnitt im Dialog): Startet ein Play-Befehl einen Player, der gerade nicht spielt, kann vorher eine
*Startlautstärke* gesetzt und eine *Startquelle* (z. B. ein Sonos-Favorit) oder ein *Startmedium*
(z. B. eine Music-Assistant-Playlist) gewählt werden. So wird nie eine alte, hohe Lautstärke übernommen.
Pausieren und bereits laufende Wiedergabe bleiben unberührt.

**Szenen 1–5:** Jede Szene kann eine Lautstärke setzen und einen Sender, eine Quelle oder ein Medium starten. Ausgelöst wird sie über
die Szenennummer auf der Szenenadresse oder über eine eigene 1-Bit-Adresse (1 = starten, 0 = Pause). Eine Szene
mit Quelle, Medium oder Lautstärke braucht die Szenenadresse oder eine eigene 1-Bit-Adresse.

- **Sender** (`media_player.play_media`): bei jedem Player, siehe [Sender](#sender).
- **Quelle** (`media_player.select_source`): z. B. ein Sonos-Favorit.
- **Medium** (`media_player.play_media`): Name oder URI einer Playlist, eines Albums, Interpreten, Titels oder
  Radiosenders, z. B. `library://playlist/7` oder `Radio Paradise`. Das ist der Weg für **Music Assistant**,
  dessen Player keine Favoriten als Quellen anbieten. Der Typ (Playlist, Album, Interpret, Titel, Radio) ist
  optional; leer = automatisch.
- **Auswahlliste bei Music Assistant:** „Medium“ bietet die **Playlists und Radiosender** deiner Music-Assistant-Bibliothek
  zur Auswahl an („Playlist · Name“, „Radiosender · Name“); das Feld zeigt nach der Auswahl den **Titel**, dahinter merkt sich der Eintrag die Adresse (z. B. `library://playlist/399`).
  Eigene Eingaben (Alben, Interpreten, Podcasts, Adressen von Spotify) sind weiter möglich. Die Liste wird beim Öffnen
  des Dialogs nur gelesen, höchstens 500 Einträge je Art. Ist der Player nicht erreichbar oder dauert die Abfrage
  länger als etwa 10 Sekunden, bleibt „Medium“ ein Textfeld.
- **Vorrang:** Sind mehrere gesetzt, läuft nur eines: Sender, dann Quelle, dann Medium.
- **Der Dialog zeigt nur die passenden Felder:** Bei einem **Sonos**-Player gibt es nur die *Quelle* (Favoriten und
  Playlists aus der Quellenliste des Players), bei **Music Assistant** nur *Medium* und *Typ*. Bei jedem anderen Player
  stehen beide zur Wahl. Erkannt wird das an der Integration, die den Media Player bereitstellt. Beim Wechsel des
  Players über *Neu konfigurieren* werden gespeicherte Felder entfernt, die zum neuen Typ nicht passen.

## Sender

Das Feld **Sender** (Wiedergabeoption und Szenen) gibt es bei **jedem** Player, unabhängig von der Integration. Die Liste ist durchsuchbar:

- **Radiosender (fest):** WDR 2 Münsterland, WDR 4, 1LIVE, Radio WMW, Energy NRW, Energy Digital, Radio Bob, Radio Bob NRW. Es wird der **Name** gespeichert; die Stream-Adresse steht in der Integration (`stations.py`). Ändert sie sich, gilt die Korrektur für alle gespeicherten Szenen. Die Liste lässt sich dort erweitern.
- **Radio Browser:** Ist die Home-Assistant-Integration *Radio Browser* eingerichtet, kommen ihre **lokalen** Sender (höchstens 100 km um dein Zuhause) und die 250 **beliebtesten** Sender dazu. Die Liste wird beim Öffnen des Dialogs nur gelesen, eine Stunde im Speicher gehalten und bleibt leer, wenn sie nicht erreichbar ist.
- Sonos und Music Assistant bekommen Radio-Browser-Sender als `media-source://radio_browser/…`-Adresse und lösen sie selbst auf (Sonos behandelt sie als Radio); bei anderen Playern löst die Integration die Adresse selbst auf.
- Eine frei getippte Adresse (`https://…`) wird direkt abgespielt.

Nach der Auswahl zeigt das Feld den **Titel** (z. B. „WDR 2 Münsterland“), nicht die Adresse. Beim Speichern merkt sich der
Eintrag zu jedem gewählten Titel aus Radio Browser oder Music Assistant die Adresse und schlägt sie beim Abspielen dort nach; gespeicherte
Szenen laufen daher auch ohne Abfrage des Verzeichnisses. Gleiche Titel mit verschiedener Adresse bekommen eine Nummer („Radio XY (2)“).
Ältere Einstellungen mit einer Adresse im Feld laufen weiter und zeigen die Adresse, bis du neu auswählst. Die **Titel** der gewählten Sender
und Medien stehen außerdem oben im Dialog („Gewählte Sender und Medien“).

Ob Titel, Interpret und Cover ankommen, hängt vom Stream und vom Player ab. Direkte Stream-Adressen liefern Titel und Interpret meist aus den Metadaten des Streams; ein Sendersymbol als Cover gibt es dabei oft nicht. Die Adressen großer Anbieter (z. B. `edge68.streamonkey.net`) können sich ändern.

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

- Die Anmeldung der Adressen bei der KNX-Integration gilt nur zur Laufzeit und wird alle 5 Minuten sowie nach
  einem Neuladen der KNX-Integration wiederholt.
- Ausgehende Telegramme (auch die eigenen Rückmeldungen) werden nie als Befehl ausgewertet.
- Ist der Media Player `unavailable`/`unknown`, werden Befehle ignoriert.
- Die Farben des Icons stammen aus dem KNX-Logo. „KNX“ ist eine Marke der KNX Association; diese Integration ist
  ein unabhängiges Projekt.

## Entwicklung

```bash
pip install pytest-homeassistant-custom-component
pytest
```

Der Workflow `auto-release.yml` erstellt aus der Version in `manifest.json` bei jeder Änderung auf `main` Tag und
Release. Lizenz: siehe [LICENSE](LICENSE).
