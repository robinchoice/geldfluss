# Geldfluss

## Zweck & Links

- Persönliches Werkzeug für Robin: Bewegungen von Aktien, Anleihen, Währungen, Gold, Öl und Bitcoin in ~16 großen Volkswirtschaften, eingeordnet als z-Score, dazu langsame Flussdaten (TIC, COFER) und der GPR-Index. Details in der README.
- Repo `robinchoice/geldfluss` (öffentlich). Keine Daten, Berichte oder Secrets einchecken.
- Savor-Workflow „Geldfluss-Wochenbericht“ (montags 8:00 Europe/Berlin) führt das Skript aus und schreibt Robin die Zusammenfassung.

## Checks

`uv run python -m py_compile geldfluss.py && uv run geldfluss.py > /dev/null`

## Deploy

Keins. Läuft nur lokal auf dem Laptop.

## Fallen

- Die Sandbox braucht Netz zu: `query1.finance.yahoo.com`, `query2.finance.yahoo.com`, `fc.yahoo.com`, `www.yahoo.com`, `ts-api.cnbc.com`, `ticdata.treasury.gov`, `api.imf.org`, `www.matteoiacoviello.com`, für `uv sync` zusätzlich `pypi.org` und `files.pythonhosted.org`.
- `uv` läuft mit `no-cache` (in `pyproject.toml`), weil `~/.cache/uv` in der Sandbox nur lesbar ist.
- Eine nicht erreichbare Quelle bricht den Bericht nicht ab, sie steht unter „Quellen mit Fehlern“. Der Cache spart nur wiederholte Läufe am selben Tag (6 bzw. 24 Stunden gültig), ohne Netz springt er nicht mit älteren Daten ein.
- CNBC ist eine inoffizielle Schnittstelle (`1Y.json` liefert rund zwei Jahre Tageswerte). Bricht sie, die Renditen einzeln prüfen, nicht das ganze Skript umbauen.
- Keine Anlageempfehlungen und keine Kriegsprognosen im Bericht.
