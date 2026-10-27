# Geldfluss

Persönliches Werkzeug: Wohin ist in der letzten Woche und im letzten Monat Geld zwischen den großen Volkswirtschaften und den Assetklassen geflossen, und was davon geht über die normale Schwankung hinaus? Kein Produkt, keine Oberfläche, keine Anlageempfehlung.

## Nutzung

```sh
uv run geldfluss.py
```

Gibt den Bericht als Markdown aus und legt ihn als `berichte/<datum>.md` und `.json` ab. Der Savor-Workflow „Geldfluss-Wochenbericht“ ruft das montags um 8:00 auf und fasst es auf Deutsch zusammen.

## Was drinsteht

- **Aktien** von 16 Volkswirtschaften (USA, Eurozone, DE, FR, IT, UK, CH, JP, CN, IN, KR, AU, CA, BR, MX, TR), in Landeswährung und in USD.
- **Währungen** als Wert in USD (+ = stärker), dazu der Dollar-Index.
- **Staatsanleihen**: 10-jährige Renditen von 14 Ländern, USA 3M/2J, Deutschland 2J, Spreads Italien/Frankreich/USA gegen Deutschland und die US-Zinskurve 10J−2J.
- **Gold, Öl (Brent), Bitcoin**, **VIX** und **MOVE**.
- **Geopolitisches Risiko**: GPR-Tagesindex von Caldara/Iacoviello, monatlich auch nach Ländern.
- **Langsame Flussdaten**, nur wenn neu erschienen: US-TIC (ausländische Halter von US-Staatsanleihen, monatlich) und IMF COFER (Währungsanteile an den Weltreserven, vierteljährlich).

Einordnung: Veränderung über 7 und 30 Kalendertage, geteilt durch die normale Schwankung, also die Standardabweichung der Tagesveränderungen im Jahr davor, hochgerechnet auf die Zahl der Handelstage im Fenster (z-Score). Ab |z| ≥ 2 steht eine Bewegung oben unter „Über der normalen Schwankung“. Kurse als Log-Rendite in Prozent, Renditen und Spreads in Basispunkten.

## Quellen

Alle frei und ohne API-Key:

| Quelle | Daten | Host |
|---|---|---|
| Yahoo Finance über [yfinance](https://github.com/ranaroussi/yfinance) | Aktien, Währungen, Gold, Öl, Bitcoin, VIX, MOVE, US 3M | `query1/query2.finance.yahoo.com`, `fc.yahoo.com`, `www.yahoo.com` |
| CNBC-Chartdaten (inoffiziell) | Staatsanleihen-Renditen | `ts-api.cnbc.com` |
| US Treasury TIC, Tabelle 5 | ausländische Halter von US-Staatsanleihen | `ticdata.treasury.gov` |
| IMF SDMX, COFER | Währungszusammensetzung der Reserven | `api.imf.org` |
| Caldara/Iacoviello | GPR-Index täglich und nach Ländern | `www.matteoiacoviello.com` |

Warum nicht OpenBB: Geprüft am 27.10.2026. Die Installation ist 893 MB groß (457 Pakete), bringt in der Grundinstallation kein yfinance mit und deckt weder TIC noch GPR ab. COFER ginge nur über den allgemeinen IMF-Zugang. Für ein Skript dieser Größe sind die Quellen direkt schlanker.

Lücken: Für Indien und Russland gibt es keine freie Tagesquelle für 10-jährige Renditen, für Russland auch keinen Aktienindex (Yahoo führt IMOEX nicht mehr). Die BIS-Bankenstatistik ist nicht dabei. FRED bräuchte einen Key und brächte für die anderen Länder nur Monatswerte.

## Speicher

- `cache/`: Rohdaten, Marktdaten 6 Stunden, langsame Daten 24 Stunden gültig. Dateien älter als 30 Tage werden gelöscht, insgesamt höchstens 50 MB (älteste zuerst). `cache/state.json` merkt sich, wann eine Monats- oder Quartalszahl zuerst gesehen wurde; sie gilt 6 Tage lang als neu.
- `berichte/`: die letzten 52 Berichte.
- Beides ist gitignoriert.
