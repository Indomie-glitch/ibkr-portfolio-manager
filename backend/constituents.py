"""Members of six stock indexes (Milestone 9, #109), kept in indices.sqlite and refreshed weekly.

Members and weights come from the daily holdings files of ETFs that hold every stock in their
index (State Street SPDR and iShares; free, no key). Weights are the fund's, rescaled so the
stocks add up to 100% (cash and futures left out); they track the index's own within a few
hundredths of a percentage point. Market cap, trailing P/E and 1-year price change: Yahoo's
screener, daily (#111). Sector and industry: each company's Yahoo profile (the same names as the
About section and the Risk page), looked up one at a time in the background and kept; until then
the fund's GICS sector, where its file has one.

A download that fails, or brings too few members, keeps the last good copy: GET /indices shows
its date and that it's stale. A fresh install starts from seed/indices.json (members, sectors and
industries filled in when the app was built), so it only tops up.
"""
import asyncio
import csv
import io
import json
import re
import sqlite3
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

import config
import yahoo
from names import display_name
from secrets_guard import mask_secrets

DB_PATH = config.DATA_DIR / "indices.sqlite"
REFRESH_AFTER = timedelta(days=7)
STATS_AFTER = timedelta(days=1)  # market cap, P/E and 1-year change move every day
RETRY_AFTER = timedelta(hours=6)
PROFILE_MAX_AGE = timedelta(days=90)  # sector and industry rarely change
PROFILE_PAUSE_S = 1.0  # between Yahoo profile lookups, to stay well under Yahoo's limits
PROFILE_FAILURES_TO_STOP = 3  # in a row: Yahoo is down or limiting us; try again next check
REQUEST_TIMEOUT_S = 30
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"

SSGA_US = "https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/holdings-daily-us-en-{}.xlsx"
SSGA_AU = "https://www.ssga.com/au/en_gb/intermediary/library-content/products/fund-data/etfs/apac/holdings-daily-au-en-{}.xlsx"
# min_count: fewer members than this means the file is broken or partial, so it isn't used
INDEXES = {
    "sp500": {"name": "S&P 500", "market": "US", "format": "ssga", "min_count": 490, "fund": "SPY",
              "url": SSGA_US.format("spy")},
    "nasdaq100": {"name": "Nasdaq 100", "market": "US", "format": "ishares", "min_count": 98, "fund": "CNDX",
                  "url": "https://www.blackrock.com/uk/individual/products/253741/x/1472631233320.ajax?fileType=csv&dataType=fund"},
    "dow": {"name": "Dow Jones Industrial Average", "market": "US", "format": "ssga", "min_count": 30, "fund": "DIA",
            "url": SSGA_US.format("dia")},
    "asx20": {"name": "S&P/ASX 20", "market": "ASX", "format": "ishares", "min_count": 20, "fund": "ILC",
              "url": "https://www.blackrock.com/au/products/251921/x/1478358644060.ajax?fileType=csv&dataType=fund"},
    "asx50": {"name": "S&P/ASX 50", "market": "ASX", "format": "ssga", "min_count": 48, "fund": "SFY",
              "url": SSGA_AU.format("sfy")},
    "asx200": {"name": "S&P/ASX 200", "market": "ASX", "format": "ssga", "min_count": 195, "fund": "STW",
               "url": SSGA_AU.format("stw")},
}
# Built with `python constituents.py --seed` and bundled with the Mac app (portfolio-backend.spec)
SEED_PATH = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "seed" / "indices.json"


class SourceError(Exception):
    """A source answered with something we can't use."""


# ---------- Reading the files ----------

def clean_symbol(raw):
    """A fund's ticker in IB's form, or None for cash and other non-stock rows:
    "BRK.B" / "BRK/B" -> "BRK B", "BHP-AU" -> "BHP", "-" / "954FAV004" (a suspended stock's code) -> None."""
    symbol = str(raw or "").strip().upper().removesuffix("-AU")
    match = re.fullmatch(r"([A-Z0-9]{1,6})(?:[./ ]([A-Z]))?", symbol)  # ASX tickers can start with a digit: "360"
    if not match:
        return None
    return f"{match[1]} {match[2]}" if match[2] else match[1]


def _as_of(text):
    """"As of 21-Oct-2026", "21-Oct-2026" or "21/Oct/2026" -> "2026-10-21"."""
    found = re.search(r"(\d{1,2})[-/ ]([A-Za-z]{3})[-/ ](\d{4})", str(text))
    if not found:
        raise SourceError("The holdings file has no date")
    return datetime.strptime(" ".join(found.groups()), "%d %b %Y").date().isoformat()


def _number(text):
    try:
        return float(str(text).replace(",", ""))
    except ValueError:
        return None


def parse_ssga(content):
    """A State Street daily holdings .xlsx -> (as_of, rows). The header row is the one with
    "Ticker"; US files have no sector ("-"), Australian ones have GICS sector and industry."""
    sheet = pd.read_excel(io.BytesIO(content), header=None, dtype=str).fillna("")
    header_rows = [i for i, row in sheet.iterrows() if "Ticker" in row.values]
    if not header_rows:
        raise SourceError("The holdings file has no Ticker column")
    top = sheet.iloc[: header_rows[0]].to_numpy().ravel()
    as_of = _as_of(next((cell for cell in top if "As of" in cell), ""))
    columns = list(sheet.iloc[header_rows[0]])

    def col(*names):  # US and Australian files name some columns differently
        return next((columns.index(n) for n in names if n in columns), None)
    ticker, name, weight = col("Ticker"), col("Name"), col("Weight", "Weight (%)")
    sector, industry = col("Sector", "Sector Classification"), col("Industry Classification")
    rows = []
    for _, row in sheet.iloc[header_rows[0] + 1:].iterrows():
        rows.append({
            "symbol": row.iloc[ticker], "name": row.iloc[name], "weight": _number(row.iloc[weight]),
            "fund_sector": row.iloc[sector] if sector is not None else None,
            "fund_industry": row.iloc[industry] if industry is not None else None,
        })
    return as_of, rows


def parse_ishares(text):
    """An iShares holdings CSV -> (as_of, rows). The first line holds the date; only "Equity"
    rows are stocks (the rest are cash, futures and collateral)."""
    lines = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    if not lines or "as of" not in lines[0][0].lower():
        raise SourceError("Not an iShares holdings file")
    as_of = _as_of(lines[0][1])
    header = next((i for i, line in enumerate(lines) if line[:2] == ["Ticker", "Name"]), None)
    if header is None:
        raise SourceError("The holdings file has no Ticker column")
    columns = lines[header]
    rows = []
    for line in lines[header + 1:]:
        if len(line) != len(columns):
            continue  # the disclaimer under the table
        item = dict(zip(columns, line))
        if item.get("Asset Class") != "Equity":
            continue
        rows.append({"symbol": item["Ticker"], "name": item["Name"], "weight": _number(item["Weight (%)"]),
                     "fund_sector": item.get("Sector"), "fund_industry": None})
    return as_of, rows


def members_from(rows):
    """Stock rows only, in IB's ticker form, weights rescaled to add up to 100, ranked largest first."""
    members = {}
    for row in rows:
        symbol = clean_symbol(row["symbol"])
        if not symbol or not row["weight"] or row["weight"] <= 0 or row["name"] == "Unassigned":
            continue
        if symbol in members:  # one company listed twice: add the lines
            members[symbol]["weight"] += row["weight"]
            continue
        sector = row["fund_sector"] if row["fund_sector"] not in (None, "", "-") else None
        members[symbol] = {**row, "symbol": symbol, "fund_sector": sector, "fund_industry": row["fund_industry"] or None}
    total = sum(m["weight"] for m in members.values())
    ranked = sorted(members.values(), key=lambda m: -m["weight"])
    for rank, member in enumerate(ranked, start=1):
        member["weight"] = member["weight"] / total * 100
        member["rank"] = rank
    return ranked


def _download(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
        return response.read()


def fetch_index(index_id, download=_download):
    """Downloads and reads one index's members -> (as_of, members). Raises SourceError if the
    file is unusable or has fewer members than the index should."""
    index = INDEXES[index_id]
    content = download(index["url"])
    if index["format"] == "ssga":
        as_of, rows = parse_ssga(content)
    else:
        as_of, rows = parse_ishares(content.decode("utf-8-sig", errors="replace"))
    members = members_from(rows)
    if len(members) < index["min_count"]:
        raise SourceError(f"The {index['fund']} holdings file listed only {len(members)} stocks")
    return as_of, members


# ---------- Storage ----------

def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS members (
            index_id TEXT NOT NULL, market TEXT NOT NULL, symbol TEXT NOT NULL, weight REAL NOT NULL, rank INTEGER NOT NULL,
            fund_sector TEXT, fund_industry TEXT, PRIMARY KEY (index_id, symbol)
        );
        CREATE TABLE IF NOT EXISTS indexes (
            index_id TEXT PRIMARY KEY, as_of TEXT, fetched_at TEXT, last_attempt TEXT, last_error TEXT
        );
        CREATE TABLE IF NOT EXISTS companies (
            market TEXT NOT NULL, symbol TEXT NOT NULL, name TEXT, market_cap REAL, market_cap_at TEXT,
            sector TEXT, industry TEXT, profile_at TEXT, pe REAL, return_1y REAL, PRIMARY KEY (market, symbol)
        );
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
    """)
    # Stores from #109 have no P/E or 1-year change yet; market_cap_at dates all three
    have = {row["name"] for row in conn.execute("PRAGMA table_info(companies)")}
    for column in ("pe", "return_1y"):
        if column not in have:
            conn.execute(f"ALTER TABLE companies ADD COLUMN {column} REAL")
    return conn


def _meta(conn):
    return {row["key"]: json.loads(row["value"]) for row in conn.execute("SELECT key, value FROM meta")}


def _set_meta(conn, **values):
    conn.executemany("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                     [(key, json.dumps(value)) for key, value in values.items()])


def store_index(index_id, as_of, members, now):
    """Replaces one index's members (one transaction) and adds any new companies."""
    market = INDEXES[index_id]["market"]
    with _connect() as conn:
        conn.execute("DELETE FROM members WHERE index_id = ?", (index_id,))
        conn.executemany("INSERT INTO members VALUES (?, ?, ?, ?, ?, ?, ?)", [
            (index_id, market, m["symbol"], m["weight"], m["rank"], m["fund_sector"], m["fund_industry"])
            for m in members])
        conn.executemany("INSERT OR IGNORE INTO companies (market, symbol, name) VALUES (?, ?, ?)", [
            (market, m["symbol"], display_name(m["name"].upper(), m["symbol"])[0]) for m in members])
        conn.execute("INSERT OR REPLACE INTO indexes VALUES (?, ?, ?, ?, NULL)",
                     (index_id, as_of, now.isoformat(), now.isoformat()))


def _record_failure(index_id, message, now):
    with _connect() as conn:
        conn.execute("INSERT OR IGNORE INTO indexes (index_id) VALUES (?)", (index_id,))
        conn.execute("UPDATE indexes SET last_attempt = ?, last_error = ? WHERE index_id = ?",
                     (now.isoformat(), mask_secrets(message), index_id))


def store_market_stats(market, stats, now):
    """Market cap, P/E and 1-year change for the companies we have; a name from the source
    replaces the fund's shortened one ("Cmnwlth Bk Of Aust") unless Yahoo's profile has given one."""
    with _connect() as conn:
        for symbol, item in stats.items():
            conn.execute("""UPDATE companies SET market_cap = ?, pe = ?, return_1y = ?, market_cap_at = ?,
                            name = CASE WHEN ? IS NOT NULL AND profile_at IS NULL THEN ? ELSE name END
                            WHERE market = ? AND symbol = ?""",
                         (item["market_cap"], item.get("pe"), item.get("return_1y"), now.isoformat(),
                          item.get("name"), item.get("name"), market, symbol))
        _set_meta(conn, **{f"stats_{market}_at": now.isoformat(), f"stats_{market}_error": None})


def _due(last_success, last_attempt, failed, now, every=REFRESH_AFTER):
    if failed and last_attempt and now - datetime.fromisoformat(last_attempt) < RETRY_AFTER:
        return False
    return not last_success or now - datetime.fromisoformat(last_success) >= every


def _error_text(exc, what):
    if isinstance(exc, (SourceError, yahoo.YahooUnavailable)):
        return str(exc)
    return f"Couldn't load {what} ({exc.__class__.__name__})."


# ---------- Refreshing ----------

async def refresh_indexes(now, download=_download):
    """Fetches every index whose copy is a week old. Returns how many were updated."""
    with _connect() as conn:
        state = {row["index_id"]: row for row in conn.execute("SELECT * FROM indexes")}
    updated = 0
    for index_id, index in INDEXES.items():
        row = state.get(index_id)
        if row and not _due(row["fetched_at"], row["last_attempt"], row["last_error"], now):
            continue
        try:
            as_of, members = await asyncio.to_thread(fetch_index, index_id, download)
            store_index(index_id, as_of, members, now)
            updated += 1
        except Exception as exc:
            _record_failure(index_id, _error_text(exc, f"the {index['fund']} holdings file"), now)
    return updated


async def refresh_market_stats(now, fetch=None, force=False):
    """Market cap, P/E and 1-year change for each market, daily (or when members changed: force).
    fetch(market, wanted symbols) defaults to Yahoo's screener."""
    fetch = fetch or yahoo.fetch_market_stats
    with _connect() as conn:
        meta = _meta(conn)
        wanted = {m: {r["symbol"] for r in conn.execute("SELECT DISTINCT symbol FROM members WHERE market = ?", (m,))}
                  for m in ("US", "ASX")}
    for market in ("US", "ASX"):
        at, error = meta.get(f"stats_{market}_at"), meta.get(f"stats_{market}_error")
        attempt = meta.get(f"stats_{market}_attempt")
        if not wanted[market] or not (force or _due(at, attempt, error, now, every=STATS_AFTER)):
            continue
        try:
            store_market_stats(market, await fetch(market, wanted[market]), now)
        except Exception as exc:
            with _connect() as conn:
                _set_meta(conn, **{f"stats_{market}_error": mask_secrets(_error_text(exc, f"{market} market data"))})
        with _connect() as conn:
            _set_meta(conn, **{f"stats_{market}_attempt": now.isoformat()})


async def fill_profiles(now, fetch_info=None, pause_s=PROFILE_PAUSE_S):
    """Looks up sector and industry on Yahoo for companies without them (or whose lookup is 90
    days old), one at a time. Stops after a few failures in a row. Returns how many were filled."""
    fetch_info = fetch_info or yahoo.fetch_info
    stale_before = (now - PROFILE_MAX_AGE).isoformat()
    with _connect() as conn:
        # Current members only (a company that left every index isn't looked up), largest first
        todo = conn.execute("""SELECT market, symbol FROM companies c
                               WHERE EXISTS (SELECT 1 FROM members m WHERE m.market = c.market AND m.symbol = c.symbol)
                               AND (profile_at IS NULL OR profile_at < ?) ORDER BY market_cap DESC""",
                            (stale_before,)).fetchall()
    filled = failures = 0
    for row in todo:
        try:
            info = await fetch_info(yahoo.ticker_for(row["symbol"], row["market"]))
        except yahoo.YahooUnavailable:
            info = {}  # Yahoo has nothing for it: don't ask again for 90 days
        except Exception as exc:
            failures += 1
            print(f"Index members: no Yahoo profile for {row['symbol']}: {mask_secrets(exc)}")
            if failures >= PROFILE_FAILURES_TO_STOP:
                break
            continue
        failures = 0
        with _connect() as conn:
            # The profile's market data only fills a gap the screener left (a stock outside its pages)
            cap = yahoo._number(info.get("marketCap"))
            change = yahoo._number(info.get("52WeekChange"))
            conn.execute("""UPDATE companies SET sector = ?, industry = ?, profile_at = ?, name = COALESCE(?, name),
                            market_cap_at = CASE WHEN market_cap IS NULL AND ? IS NOT NULL THEN ? ELSE market_cap_at END,
                            pe = CASE WHEN market_cap IS NULL THEN ? ELSE pe END,
                            return_1y = CASE WHEN market_cap IS NULL THEN ? ELSE return_1y END,
                            market_cap = COALESCE(market_cap, ?) WHERE market = ? AND symbol = ?""",
                         (info.get("sector"), info.get("industry"), now.isoformat(), info.get("longName"),
                          cap, now.isoformat(), yahoo._number(info.get("trailingPE")),
                          change * 100 if change is not None else None, cap, row["market"], row["symbol"]))
        filled += 1
        await asyncio.sleep(pause_s)
    return filled


async def refresh(now=None, download=_download, fetch_stats=None, fetch_info=None):
    """One check: members (weekly per index), then market data (daily), then missing sectors and
    industries. Never raises: failures are recorded and shown by status()."""
    now = now or datetime.now(timezone.utc)
    updated = await refresh_indexes(now, download)
    await refresh_market_stats(now, fetch_stats, force=updated > 0)
    await fill_profiles(now, fetch_info)


# ---------- The bundled starting copy ----------

TABLES = ("members", "indexes", "companies", "meta")


def export_seed(path=SEED_PATH):
    """Writes every table to JSON (sorted, so a rebuilt seed diffs line by line)."""
    with _connect() as conn:
        data = {t: sorted([dict(r) for r in conn.execute(f"SELECT * FROM {t}")], key=lambda r: json.dumps(r, sort_keys=True))
                for t in TABLES}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=0, sort_keys=True) + "\n")


def load_seed_if_missing(path=SEED_PATH):
    """A fresh install (no indices.sqlite yet) starts from the bundled seed, so the background task
    only tops it up instead of looking up ~700 companies first. Returns True if it was loaded."""
    if DB_PATH.exists() or not path.exists():
        return False
    data = json.loads(path.read_text())
    with _connect() as conn:
        for table in TABLES:
            for row in data.get(table, []):
                columns = ", ".join(row)
                conn.execute(f"INSERT OR REPLACE INTO {table} ({columns}) VALUES ({', '.join('?' * len(row))})",
                             list(row.values()))
    return True


async def keep_refreshed(check_every=timedelta(hours=3), idle_check=timedelta(minutes=1)):
    """Background task (started with the server): refreshes what's due, checking every few hours.
    Does nothing while config.index_loader_enabled() is off (the default), and notices when it is
    switched on."""
    seeded = False
    while True:
        if not config.index_loader_enabled():
            await asyncio.sleep(idle_check.total_seconds())
            continue
        if not seeded:
            seeded = True
            try:
                load_seed_if_missing()
            except Exception as exc:  # a damaged seed: start empty and fetch everything instead
                print(f"Index members: couldn't load the seed: {mask_secrets(exc)}")
        try:
            await refresh()
        except Exception as exc:  # e.g. a full disk; try again next time
            print(f"Index members: refresh failed: {mask_secrets(exc)}")
        await asyncio.sleep(check_every.total_seconds())


# ---------- Reading ----------

def _index_status(index_id, row, count):
    index = INDEXES[index_id]
    return {
        "id": index_id, "name": index["name"], "market": index["market"], "fund": index["fund"],
        "count": count, "as_of": row["as_of"] if row else None,
        "fetched_at": row["fetched_at"] if row else None,
        "last_error": row["last_error"] if row else None,
        # The last download failed, so this is an older copy (or there's none yet)
        "stale": bool(row and row["last_error"]) or not (row and row["fetched_at"]),
    }


def status():
    """Each index: its member count, the holdings file's date, when it was fetched, the last error."""
    with _connect() as conn:
        rows = {row["index_id"]: row for row in conn.execute("SELECT * FROM indexes")}
        counts = dict(conn.execute("SELECT index_id, COUNT(*) FROM members GROUP BY index_id").fetchall())
        meta = _meta(conn)
    return {
        "indexes": [_index_status(i, rows.get(i), counts.get(i, 0)) for i in INDEXES],
        # Market cap, P/E and 1-year change, per market
        "market_data": {m: {"as_of": meta.get(f"stats_{m}_at"), "last_error": meta.get(f"stats_{m}_error")}
                        for m in ("US", "ASX")},
        "profiles": profile_progress(),
    }


def members(index_id):
    """One index's members, largest weight first, with what each company is known for."""
    market = INDEXES[index_id]["market"]
    with _connect() as conn:
        row = conn.execute("SELECT * FROM indexes WHERE index_id = ?", (index_id,)).fetchone()
        stocks = conn.execute("""SELECT m.symbol, c.name, m.weight, m.rank, c.sector, c.industry, m.fund_sector,
                                        m.fund_industry, c.market_cap, c.pe, c.return_1y, c.market_cap_at, c.profile_at
                                 FROM members m LEFT JOIN companies c ON c.market = m.market AND c.symbol = m.symbol
                                 WHERE m.index_id = ? ORDER BY m.rank""", (index_id,)).fetchall()
    result = _index_status(index_id, row, len(stocks))
    result["currency"] = "AUD" if market == "ASX" else "USD"
    result["members"] = [{
        "symbol": s["symbol"], "name": s["name"], "weight": round(s["weight"], 4), "rank": s["rank"],
        # Yahoo's sector and industry once looked up; until then the fund's GICS ones, if any
        "sector": s["sector"] if s["profile_at"] else s["fund_sector"],
        "industry": s["industry"] if s["profile_at"] else s["fund_industry"],
        "classification": "yahoo" if s["profile_at"] else ("gics" if s["fund_sector"] else None),
        "market_cap": s["market_cap"], "pe": s["pe"], "return_1y": s["return_1y"],
        "market_cap_at": s["market_cap_at"],
    } for s in stocks]
    return result


def indices_for(symbol, market):
    """The indexes a stock (IB symbol, "US" or "ASX") belongs to, with its weight and rank in each."""
    with _connect() as conn:
        found = conn.execute("""SELECT m.index_id, m.weight, m.rank,
                                      (SELECT COUNT(*) FROM members n WHERE n.index_id = m.index_id) AS count
                               FROM members m WHERE m.market = ? AND m.symbol = ?""", (market, symbol)).fetchall()
        rows = {row["index_id"]: row for row in conn.execute("SELECT * FROM indexes")}
    result = []
    for row in sorted(found, key=lambda r: list(INDEXES).index(r["index_id"])):
        index = _index_status(row["index_id"], rows.get(row["index_id"]), row["count"])
        result.append({**index, "weight": round(row["weight"], 4), "rank": row["rank"]})
    return result


def profile_progress():
    """How many current members have had their Yahoo profile (sector, industry) looked up."""
    with _connect() as conn:
        done, total = conn.execute("""SELECT COUNT(profile_at), COUNT(*) FROM companies c WHERE EXISTS
                                      (SELECT 1 FROM members m WHERE m.market = c.market AND m.symbol = c.symbol)""").fetchone()
    return {"done": done, "total": total, "complete": total > 0 and done == total}


def universe():
    """Every current member company (both markets, once each), for finding competitors (#111)."""
    with _connect() as conn:
        rows = conn.execute("""SELECT c.market, c.symbol, c.name, c.sector, c.industry, c.profile_at, c.market_cap,
                                      c.pe, c.return_1y, c.market_cap_at FROM companies c WHERE EXISTS
                                      (SELECT 1 FROM members m WHERE m.market = c.market AND m.symbol = c.symbol)""").fetchall()
    return [dict(row) for row in rows]


if __name__ == "__main__":
    # Rebuild the bundled seed: python constituents.py --seed (run from backend/, ~40 minutes the first time)
    if sys.argv[1:] != ["--seed"]:
        sys.exit("usage: python constituents.py --seed")
    asyncio.run(refresh())
    progress = profile_progress()
    if not progress["complete"]:
        sys.exit(f"Only {progress['done']} of {progress['total']} profiles filled (Yahoo failing?); run it again")
    export_seed()
    print(f"Wrote {SEED_PATH} ({progress['total']} companies)")
