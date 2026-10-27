"""Weekly overview: where money moved across major economies and asset classes.

Usage: uv run geldfluss.py  -> prints Markdown, writes berichte/<date>.md and .json
"""

import io
import json
import logging
import math
import sys
import time
import urllib.request
import warnings
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).parent
CACHE = ROOT / "cache"
REPORTS = ROOT / "berichte"
CACHE_MAX_DAYS = 30
CACHE_MAX_MB = 50
REPORTS_KEEP = 52  # one year of weekly reports
MARKET_MAX_AGE_H = 6
SLOW_MAX_AGE_H = 24
NEW_WITHIN_DAYS = 6  # slow data counts as new this long after we first saw it
FLAG_Z = 2.0

UA = "Mozilla/5.0 (X11; Linux x86_64) geldfluss"

# code, name, equity index (Yahoo), FX (Yahoo ticker, quoted as USD per unit?), 10y yield (CNBC)
COUNTRIES = [
    ("US", "USA", "^GSPC", None, "US10Y"),
    ("EZ", "Eurozone", "^STOXX50E", ("EURUSD=X", True), None),
    ("DE", "Deutschland", "^GDAXI", ("EURUSD=X", True), "DE10Y-DE"),
    ("FR", "Frankreich", "^FCHI", ("EURUSD=X", True), "FR10Y-FR"),
    ("IT", "Italien", "FTSEMIB.MI", ("EURUSD=X", True), "IT10Y-IT"),
    ("UK", "UK", "^FTSE", ("GBPUSD=X", True), "GB10Y-GB"),
    ("CH", "Schweiz", "^SSMI", ("CHF=X", False), "CH10Y-CH"),
    ("JP", "Japan", "^N225", ("JPY=X", False), "JP10Y-JP"),
    ("CN", "China", "000001.SS", ("CNY=X", False), "CN10Y-CN"),
    ("IN", "Indien", "^NSEI", ("INR=X", False), None),
    ("KR", "Südkorea", "^KS11", ("KRW=X", False), "KR10Y-KR"),
    ("AU", "Australien", "^AXJO", ("AUDUSD=X", True), "AU10Y-AU"),
    ("CA", "Kanada", "^GSPTSE", ("CAD=X", False), "CA10Y-CA"),
    ("BR", "Brasilien", "^BVSP", ("BRL=X", False), "BR10Y-BR"),
    ("MX", "Mexiko", "^MXX", ("MXN=X", False), "MX10Y-MX"),
    ("TR", "Türkei", "XU100.IS", ("TRY=X", False), "TR10Y-TR"),
    ("RU", "Russland", None, ("RUB=X", False), None),
]
CURRENCY = {"EURUSD=X": "EUR", "GBPUSD=X": "GBP", "CHF=X": "CHF", "JPY=X": "JPY", "CNY=X": "CNY",
            "INR=X": "INR", "KRW=X": "KRW", "AUDUSD=X": "AUD", "CAD=X": "CAD", "BRL=X": "BRL",
            "MXN=X": "MXN", "TRY=X": "TRY", "RUB=X": "RUB"}
EXTRA_YAHOO = {"DX-Y.NYB": "US-Dollar-Index (DXY)", "GC=F": "Gold", "BZ=F": "Öl (Brent)",
               "BTC-USD": "Bitcoin", "^VIX": "VIX (Aktien-Vola)", "^MOVE": "MOVE (Anleihen-Vola)",
               "^IRX": "USA 3M"}
EXTRA_CNBC = {"US2Y": "USA 2J", "DE2Y-DE": "Deutschland 2J"}
SPREADS = [("IT10Y-IT", "DE10Y-DE", "Italien − Deutschland"), ("FR10Y-FR", "DE10Y-DE", "Frankreich − Deutschland"),
           ("US10Y", "DE10Y-DE", "USA − Deutschland"), ("US10Y", "US2Y", "USA 10J − 2J")]
COFER_CCY = ["USD", "EUR", "JPY", "GBP", "CNY", "CHF", "AUD", "CAD"]
GPR_COUNTRIES = {"USA": "USA", "DEU": "Deutschland", "FRA": "Frankreich", "ITA": "Italien", "GBR": "UK",
                 "CHE": "Schweiz", "JPN": "Japan", "CHN": "China", "IND": "Indien", "KOR": "Südkorea",
                 "AUS": "Australien", "CAN": "Kanada", "BRA": "Brasilien", "MEX": "Mexiko", "TUR": "Türkei",
                 "RUS": "Russland", "UKR": "Ukraine", "ISR": "Israel", "TWN": "Taiwan", "SAU": "Saudi-Arabien"}


# --- cache -----------------------------------------------------------------

def prune():
    CACHE.mkdir(exist_ok=True)
    REPORTS.mkdir(exist_ok=True)
    now = time.time()
    files = sorted((p for p in CACHE.iterdir() if p.is_file()), key=lambda p: p.stat().st_mtime)
    for p in files:
        if now - p.stat().st_mtime > CACHE_MAX_DAYS * 86400:
            p.unlink()
    files = [p for p in files if p.exists()]
    while files and sum(p.stat().st_size for p in files) > CACHE_MAX_MB * 2**20:
        files.pop(0).unlink()
    for pattern in ("*.md", "*.json"):
        for p in sorted(REPORTS.glob(pattern))[:-REPORTS_KEEP]:
            p.unlink()


def cached(name, max_age_h, fetch):
    p = CACHE / name
    if p.exists() and time.time() - p.stat().st_mtime < max_age_h * 3600:
        return p.read_bytes()
    data = fetch()
    p.write_bytes(data)
    return data


def http(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


# --- sources ---------------------------------------------------------------

def yahoo_tickers():
    t = {c[2] for c in COUNTRIES if c[2]} | {c[3][0] for c in COUNTRIES if c[3]} | set(EXTRA_YAHOO)
    return sorted(t)


def load_yahoo():
    def fetch():
        df = yf.download(yahoo_tickers(), period="2y", interval="1d", auto_adjust=True,
                         progress=False, threads=True)["Close"]
        return df.to_csv().encode()
    df = pd.read_csv(io.BytesIO(cached("yahoo.csv", MARKET_MAX_AGE_H, fetch)), index_col=0, parse_dates=True)
    return {c: df[c].dropna() for c in df.columns if df[c].notna().any()}


def load_cnbc(symbol):
    url = f"https://ts-api.cnbc.com/harmony/app/charts/1Y.json?symbol={symbol}"  # 1Y returns ~2 years of daily bars
    bars = json.loads(cached(f"cnbc-{symbol}.json", MARKET_MAX_AGE_H, lambda: http(url)))["barData"]["priceBars"] or []
    s = pd.Series({pd.Timestamp(b["tradeTime"][:8]): float(b["close"]) for b in bars}, dtype=float)
    return s[~s.index.duplicated(keep="last")].sort_index()


def load_tic():
    url = "https://ticdata.treasury.gov/resource-center/data-chart-center/tic/Documents/slt_table5.txt"
    lines = cached("tic-table5.txt", SLOW_MAX_AGE_H, lambda: http(url)).decode("latin-1").splitlines()
    head = next(i for i, l in enumerate(lines) if l.startswith("Country\t"))
    rows = {}
    for l in lines[head + 1:]:
        parts = [x.strip() for x in l.split("\t")]
        if not parts[0]:
            break
        rows[parts[0]] = [float(x) for x in parts[1:] if x]
    periods = [x.strip() for x in lines[head].split("\t")[1:] if x.strip()]
    return pd.DataFrame(rows, index=periods).T  # rows: holders, columns: months (newest first)


def load_cofer():
    start = date.today().year - 4
    url = ("https://api.imf.org/external/sdmx/3.0/data/dataflow/IMF.STA/COFER/+/G001.AFXRA.*.SHRO_PT.Q"
           f"?c%5BTIME_PERIOD%5D=ge:{start}-Q1")
    accept = "application/vnd.sdmx.data+csv;version=2.0.0;labels=id;timeFormat=original"
    df = pd.read_csv(io.BytesIO(cached("cofer.csv", SLOW_MAX_AGE_H, lambda: http(url, {"Accept": accept}))))
    df = df.dropna(subset=["TIME_PERIOD", "OBS_VALUE"])
    df["ccy"] = df["FXR_CURRENCY"].str.removeprefix("CI_")
    return df.pivot(index="TIME_PERIOD", columns="ccy", values="OBS_VALUE").sort_index()


def load_gpr(name):
    url = f"https://www.matteoiacoviello.com/gpr_files/{name}"
    return pd.read_excel(io.BytesIO(cached(name, SLOW_MAX_AGE_H, lambda: http(url))))


# --- analysis --------------------------------------------------------------

def transform(s, kind):
    return (np.log(s) * 100) if kind == "pct" else s * 100  # pct: log %, bp: yield % -> bp


def move(s, days, kind, today):
    """Change over `days` calendar days and its z-score against the prior year's daily volatility."""
    s = s[s.index <= today].dropna()
    base_date = today - pd.Timedelta(days=days)
    before = s[s.index <= base_date]
    hist = transform(before[before.index > base_date - pd.Timedelta(days=365)], kind).diff().dropna()
    if len(hist) < 120:
        return None, None
    t = transform(s, kind)
    n = int((s.index > before.index[-1]).sum())
    change = t.iloc[-1] - t.loc[before.index[-1]]
    sigma = hist.std() * math.sqrt(max(n, 1))
    return round(change, 2), (round(change / sigma, 1) if sigma else None)


def row(group, name, s, kind, today):
    w, wz = move(s, 7, kind, today)
    m, mz = move(s, 30, kind, today)
    return {"group": group, "name": name, "kind": kind, "last": round(float(s.iloc[-1]), 4),
            "last_date": s.index[-1].date().isoformat(), "w": w, "wz": wz, "m": m, "mz": mz}


def markets(today, errors):
    try:
        y = load_yahoo()
    except Exception as e:  # network or Yahoo format change: report without these rows
        errors.append(f"Yahoo Finance: {e}")
        y = {}
    c = {}
    for sym in [x[4] for x in COUNTRIES if x[4]] + list(EXTRA_CNBC):
        try:
            c[sym] = load_cnbc(sym)
        except Exception as e:
            errors.append(f"CNBC {sym}: {e}")
    rows = []

    def usd_per_unit(fx):
        s = y.get(fx[0])
        return None if s is None else (s if fx[1] else 1 / s)

    for code, name, eq, fx, _ in COUNTRIES:
        if eq in y:
            rows.append(row("Aktien (Landeswährung)", f"{name} ({eq})", y[eq], "pct", today))
    for code, name, eq, fx, _ in COUNTRIES:
        if eq in y and (not fx or fx[0] in y):
            usd = y[eq] if not fx else (y[eq] * usd_per_unit(fx).reindex(y[eq].index).ffill()).dropna()
            rows.append(row("Aktien in USD", name, usd, "pct", today))
    seen = set()
    for code, name, eq, fx, _ in COUNTRIES:
        if fx and fx[0] not in seen and fx[0] in y:
            seen.add(fx[0])
            rows.append(row("Währungen (Wert in USD, + = stärker)", CURRENCY[fx[0]], usd_per_unit(fx), "pct", today))
    for code, name, eq, fx, ysym in COUNTRIES:
        if ysym in c and len(c[ysym]):
            rows.append(row("Staatsanleihen 10J (Rendite)", name, c[ysym], "bp", today))
    for sym, name in EXTRA_CNBC.items():
        if sym in c and len(c[sym]):
            rows.append(row("Staatsanleihen kurz (Rendite)", name, c[sym], "bp", today))
    if "^IRX" in y:
        rows.append(row("Staatsanleihen kurz (Rendite)", EXTRA_YAHOO["^IRX"], y["^IRX"], "bp", today))
    for a, b, name in SPREADS:
        if a in c and b in c:
            s = (c[a] - c[b].reindex(c[a].index).ffill()).dropna()
            rows.append(row("Spreads (Prozentpunkte)", name, s, "bp", today))
    for sym in ["GC=F", "BZ=F", "BTC-USD", "DX-Y.NYB"]:
        if sym in y:
            rows.append(row("Gold, Öl, Bitcoin, Dollar", EXTRA_YAHOO[sym], y[sym], "pct", today))
    for sym in ["^VIX", "^MOVE"]:
        if sym in y:
            rows.append(row("Risiko / Volatilität", EXTRA_YAHOO[sym], y[sym], "pct", today))
    return rows


def seen_new(state, key, period, today):
    """Remember when we first saw a period; it counts as new for NEW_WITHIN_DAYS."""
    if state.get(key, {}).get("period") != period:
        state[key] = {"period": period, "first_seen": today.isoformat()}
    return date.fromisoformat(state[key]["first_seen"]) >= today - timedelta(days=NEW_WITHIN_DAYS)


def tic(state, today):
    df = load_tic()
    latest, prev = df.columns[0], df.columns[1]
    changes = df.diff(axis=1, periods=-1).iloc[:, :-1]  # month-over-month change, newest first
    out = []
    for holder in df.index:
        ch = changes.loc[holder]
        sd = ch.iloc[1:].std()
        out.append({"holder": holder, "latest": df.loc[holder, latest], "change": round(ch.iloc[0], 1),
                    "change_12m": round(df.loc[holder, latest] - df.loc[holder].iloc[-1], 1),
                    "z": round(ch.iloc[0] / sd, 1) if sd else None})
    return {"period": latest, "previous": prev, "new": seen_new(state, "tic", latest, today), "rows": out}


def cofer(state, today):
    df = load_cofer()
    latest = df.index[-1]
    rows = [{"ccy": c, "share": round(df[c].iloc[-1], 2), "qoq": round(df[c].iloc[-1] - df[c].iloc[-2], 2),
             "yoy": round(df[c].iloc[-1] - df[c].iloc[-5], 2)} for c in COFER_CCY if c in df]
    return {"period": latest, "new": seen_new(state, "cofer", latest, today), "rows": rows}


def gpr_daily(today):
    df = load_gpr("data_gpr_daily_recent.xls")
    s = df.set_index(pd.to_datetime(df["DAY"].astype(str)))["GPRD"].dropna()
    out = {"last_date": s.index[-1].date().isoformat()}
    for label, days in (("7d", 7), ("30d", 30)):
        roll = s.rolling(f"{days}D").mean()
        hist = roll[(roll.index <= s.index[-1] - pd.Timedelta(days=days)) &
                    (roll.index > s.index[-1] - pd.Timedelta(days=365 + days))]
        out[label] = round(roll.iloc[-1], 1)
        out[f"{label}_z"] = round((roll.iloc[-1] - hist.mean()) / hist.std(), 1)
    out["year_avg"] = round(s[s.index > s.index[-1] - pd.Timedelta(days=365)].mean(), 1)
    return out


def gpr_monthly(state, today):
    df = load_gpr("data_gpr_export.xls").dropna(subset=["GPR"])
    df = df.set_index(pd.to_datetime(df["month"])).sort_index()
    latest = df.index[-1].strftime("%Y-%m")
    rows = []
    for iso, name in [("", "Welt")] + list(GPR_COUNTRIES.items()):
        col = f"GPRC_{iso}" if iso else "GPR"
        if col not in df:
            continue
        s = df[col].dropna()
        hist = s.iloc[-37:-1]
        rows.append({"name": name, "latest": round(s.iloc[-1], 2), "avg_12m": round(s.iloc[-13:-1].mean(), 2),
                     "z": round((s.iloc[-1] - hist.mean()) / hist.std(), 1)})
    return {"period": latest, "new": seen_new(state, "gpr_monthly", latest, today), "rows": rows}


# --- output ----------------------------------------------------------------

def fmt_change(v, kind):
    if v is None:
        return "–"
    return f"{v:+.1f} %" if kind == "pct" else f"{v:+.0f} bp"


def fmt_z(z):
    if z is None:
        return "–"
    return f"**{z:+.1f}**" if abs(z) >= FLAG_Z else f"{z:+.1f}"


def fmt_last(r):
    if r["kind"] == "bp" and "Spreads" not in r["group"]:
        return f"{r['last']:.2f} %"
    return f"{r['last']:,.2f}" if abs(r["last"]) >= 1 else f"{r['last']:.4g}"


def render(rep):
    today = date.fromisoformat(rep["date"])
    out = [f"# Geldfluss {rep['date']}", "",
           "1W/1M = Veränderung seit 7/30 Kalendertagen, z = in Einheiten der normalen Schwankung "
           f"(Tagesschwankung des Vorjahres), fett ab |z| ≥ {FLAG_Z:g}.", ""]
    flags = sorted((r for r in rep["markets"] if any(z is not None and abs(z) >= FLAG_Z for z in (r["wz"], r["mz"]))),
                   key=lambda r: -max(abs(r["wz"] or 0), abs(r["mz"] or 0)))
    out += ["## Über der normalen Schwankung", ""]
    out += [f"- {r['group']}: {r['name']} 1W {fmt_change(r['w'], r['kind'])} (z {fmt_z(r['wz'])}), "
            f"1M {fmt_change(r['m'], r['kind'])} (z {fmt_z(r['mz'])})" for r in flags] or ["- nichts"]
    g = rep.get("gpr_daily")
    if g:
        out += ["", f"## Geopolitisches Risiko (GPR, Caldara/Iacoviello, Stand {g['last_date']})", "",
                f"- Tagesindex Ø 7 Tage {g['7d']} (z {fmt_z(g['7d_z'])}), Ø 30 Tage {g['30d']} (z {fmt_z(g['30d_z'])}), "
                f"Ø Vorjahr {g['year_avg']}"]
    group = None
    for r in rep["markets"]:
        if r["group"] != group:
            group = r["group"]
            out += ["", f"## {group}", "", "| | Stand | 1W | z | 1M | z |", "|---|---:|---:|---:|---:|---:|"]
        stale = f" (Stand {r['last_date']})" if date.fromisoformat(r["last_date"]) < today - timedelta(days=5) else ""
        out.append(f"| {r['name']}{stale} | {fmt_last(r)} | {fmt_change(r['w'], r['kind'])} | {fmt_z(r['wz'])} "
                   f"| {fmt_change(r['m'], r['kind'])} | {fmt_z(r['mz'])} |")

    out += ["", "## Langsame Flussdaten", ""]
    t = rep.get("tic")
    if t and t["new"]:
        out += [f"### US-TIC: ausländische Halter von US-Staatsanleihen, NEU: {t['period']} (Mrd. USD)", "",
                "| Halter | Bestand | ggü. Vormonat | z (12 M.) | ggü. Vorjahr |", "|---|---:|---:|---:|---:|"]
        out += [f"| {x['holder']} | {x['latest']:,.1f} | {x['change']:+.1f} | {fmt_z(x['z'])} | {x['change_12m']:+.1f} |"
                for x in t["rows"]]
        out.append("")
    elif t:
        out.append(f"- US-TIC: nichts Neues (zuletzt {t['period']})")
    c = rep.get("cofer")
    if c and c["new"]:
        out += [f"### IMF COFER: Anteile an den Weltwährungsreserven, NEU: {c['period']}", "",
                "| Währung | Anteil | ggü. Vorquartal | ggü. Vorjahr |", "|---|---:|---:|---:|"]
        out += [f"| {x['ccy']} | {x['share']:.2f} % | {x['qoq']:+.2f} pp | {x['yoy']:+.2f} pp |" for x in c["rows"]]
        out.append("")
    elif c:
        out.append(f"- IMF COFER: nichts Neues (zuletzt {c['period']})")
    m = rep.get("gpr_monthly")
    if m and m["new"]:
        out += [f"### GPR nach Ländern (Monat), NEU: {m['period']}", "",
                "| Land | Wert | Ø 12 M. | z (36 M.) |", "|---|---:|---:|---:|"]
        out += [f"| {x['name']} | {x['latest']:.2f} | {x['avg_12m']:.2f} | {fmt_z(x['z'])} |" for x in m["rows"]]
        out.append("")
    elif m:
        out.append(f"- GPR nach Ländern: nichts Neues (zuletzt {m['period']})")
    if rep["errors"]:
        out += ["", "## Quellen mit Fehlern", ""] + [f"- {e}" for e in rep["errors"]]
    out += ["", "Quellen: Yahoo Finance (yfinance), CNBC (Renditen), US Treasury TIC, IMF COFER, "
            "Caldara/Iacoviello GPR. Keine Anlageempfehlung."]
    return "\n".join(out) + "\n"


def main():
    warnings.filterwarnings("ignore")
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    prune()
    today = date.today()
    state_file = CACHE / "state.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    errors = []
    rep = {"date": today.isoformat(), "markets": markets(pd.Timestamp(today), errors), "errors": errors}
    for key, fn in (("tic", lambda: tic(state, today)), ("cofer", lambda: cofer(state, today)),
                    ("gpr_daily", lambda: gpr_daily(today)), ("gpr_monthly", lambda: gpr_monthly(state, today))):
        try:
            rep[key] = fn()
        except Exception as e:  # one unreachable source must not stop the weekly report
            errors.append(f"{key}: {e}")
    state_file.write_text(json.dumps(state, indent=1))
    md = render(rep)
    (REPORTS / f"{today}.md").write_text(md)
    (REPORTS / f"{today}.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False, default=float))
    sys.stdout.write(md)


if __name__ == "__main__":
    main()
