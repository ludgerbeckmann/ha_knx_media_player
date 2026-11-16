"""Feste Senderliste (Name -> Stream-Adresse), unabhängig von der Integration des Media Players.

Gespeichert wird in den Einstellungen der **Name**; die Adresse wird erst beim Abspielen nachgeschlagen.
Ändert sich eine Adresse, genügt eine Korrektur hier, gespeicherte Szenen folgen automatisch.
Neue Sender einfach ergänzen (Name, Adresse) und die Version im Manifest anheben.

Quellen: WDR-Sender laut offizieller Streamliste des WDR, Radio Bob (Hauptsender) laut offizieller
Seite von Radio Bob; Radio Bob NRW, Radio WMW, Energy NRW und Energy Digital vom Nutzer genannt
(Servernummern wie `edge68` können sich beim Dienstleister ändern).
"""

from __future__ import annotations

STATIONS: dict[str, str] = {
    "WDR 2 Münsterland": "https://wdr-wdr2-muensterland.icecastssl.wdr.de/wdr/wdr2/muensterland/mp3/128/stream.mp3",
    "WDR 4": "https://wdr-wdr4-live.icecastssl.wdr.de/wdr/wdr4/live/mp3/128/stream.mp3",
    "1LIVE": "https://wdr-1live-live.icecastssl.wdr.de/wdr/1live/live/mp3/128/stream.mp3",
    "Radio WMW": "https://edge68.streamonkey.net/mms-radiowmw/stream/mp3?aggregator=Hoerer",
    "Energy NRW": "https://edge62.streamonkey.net/energy-nrw/stream/mp3?aggregator=shorty",
    "Energy Digital": "https://edge82.streamonkey.net/energy-digital/stream/mp3?aggregator=Shorty",
    "Radio Bob": "https://streams.radiobob.de/bob-national/mp3-192/streams.radiobob.de/",
    "Radio Bob NRW": "https://streams.radiobob.de/live-nrw-mitte/mp3-192/streams.radiobob.de/",
}
