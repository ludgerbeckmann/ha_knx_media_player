# Sicherheitsrichtlinie

## Unterstützte Versionen

Gepflegt wird nur die jeweils neueste Version.

## Sicherheitslücke melden

Bitte **nicht** als öffentliches Issue melden, sondern privat über
<https://github.com/ludgerbeckmann/ha_knx_media_player/security/advisories/new>.

## Geltungsbereich

Die Integration steuert Media Player in Home Assistant über die KNX-Integration und die
Standarddienste von `media_player`. Sie speichert ihre Einstellungen in Home-Assistant-Config-Einträgen
und den zuletzt empfangenen Befehl in einem kleinen Store. Zugangsdaten verwaltet sie nicht. Sender- und
Bibliothekslisten liest sie über Home Assistant (Radio Browser, Music Assistant); Stream-Adressen werden
an den jeweiligen Player übergeben. Lücken in Home Assistant, KNX, Sonos oder Music Assistant selbst
gehören zu den jeweiligen Projekten.
