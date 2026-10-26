"""A real, capped run of the supply chain pipeline on a few companies (#126): a development tool, not part of the app.

    cd backend && venv/bin/python scripts/pipeline_run.py --budget 0.50 --companies AMD,NVDA,MU,ANET
    cd backend && venv/bin/python scripts/pipeline_run.py --report            # only print the report on what is in the database
    cd backend && venv/bin/python scripts/pipeline_run.py --budget 0.01 --companies ANET --copy-database   # on a copy: nothing is left in your database

It uses the real data folder (data/supply_chain.sqlite, data/filings, usage.sqlite) and the same workers, handlers and
orchestrator as the app, but:
- only the companies named are scouted (the watch list is loaded, so the Companies panel shows it, but nothing else is queued);
- --budget is this run's own hard cap: the daily pace is off for the run and nothing is started that would take it past the cap
  (the monthly budget in your settings still applies on top). Your settings file is not touched;
- --hold marks companies as held (their jobs run first), as the app does from IB; with --holdings-from-backend they are read from
  the dev backend's GET /positions when it is running with IB Gateway connected.
It ends when no more work is due (or at --minutes) and prints the links, their confidence levels, what was rejected, the cost and a
check of the pipeline sheet's numbers against the database.
"""
import argparse
import asyncio
import json
import sqlite3
import sys
import tempfile
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
import usage_store  # noqa: E402
from supply_chain import control, db, jobs, merge, orchestrator, status, themes, worker  # noqa: E402,F401
from supply_chain import reader, scout, verifier, xbrl  # noqa: E402,F401  (register the handlers)

BACKEND = "http://127.0.0.1:8000"


def held_from_backend():
    """[(symbol, exchange)] from the dev backend's /positions, or None when it isn't running / IB isn't connected."""
    try:
        with urllib.request.urlopen(f"{BACKEND}/positions", timeout=5) as response:
            return [(p["symbol"], p.get("exchange")) for p in json.load(response) if p.get("sec_type", "STK") == "STK"]
    except Exception:
        return None


def company_for(conn, symbol, market="US"):
    row = conn.execute("""SELECT company_id FROM identifiers WHERE scheme = 'ticker' AND value = ? AND market = ?""", (symbol, market)).fetchone()
    return row["company_id"] if row else None


def stamp(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def run_pipeline(conn, path, company_ids, workers, minutes):
    for company_id in company_ids:
        jobs.enqueue(conn, "scout", str(company_id), priority=70, company_id=company_id)
    pool = [worker.Worker(path, name=f"run-{i}") for i in range(workers)]
    pool[0].start(exclusive=True)
    tasks = [asyncio.create_task(w.run_forever(exclusive=False)) for w in pool]
    deadline = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    quiet = 0
    try:
        while datetime.now(timezone.utc) < deadline:
            await asyncio.sleep(3)
            kinds = orchestrator.claimable_kinds(conn, worker.HANDLERS)
            due = conn.execute(
                f"""SELECT COUNT(*) FROM jobs WHERE status IN ('queued', 'running') AND (status = 'running' OR run_after <= ?)
                    AND kind IN ({', '.join('?' * len(kinds))})""", (stamp(datetime.now(timezone.utc)), *kinds)).fetchone()[0]
            quiet = quiet + 1 if due == 0 else 0
            if quiet >= 3:
                break
    finally:
        for w in pool:
            w.stop()
        await asyncio.gather(*tasks, return_exceptions=True)


def money(value):
    return f"US${value:.4f}"


def report(conn, since):
    start = stamp(since)
    print("\n=== Cost ===")
    rows = conn.execute("""SELECT j.kind, COUNT(*) runs, SUM(r.cost_usd) cost, SUM(r.input_tokens) tin, SUM(r.output_tokens) tout
                           FROM runs r JOIN jobs j ON j.id = r.job_id WHERE r.started_at >= ? AND r.cost_usd > 0 GROUP BY j.kind""", (start,)).fetchall()
    total = 0.0
    for r in rows:
        total += r["cost"]
        print(f"  {r['kind']:7} {r['runs']:3} runs  {r['tin'] or 0:>9,} in  {r['tout'] or 0:>7,} out  {money(r['cost'])}")
    print(f"  total this run: {money(total)}")

    print("\n=== Links ===")
    links = conn.execute("""SELECT r.*, s.name AS supplier, c.name AS customer FROM relationships r JOIN companies s ON s.id = r.supplier_id
                            JOIN companies c ON c.id = r.customer_id WHERE r.merged_into IS NULL ORDER BY r.confidence DESC, r.id""").fetchall()
    for r in links:
        evidence = conn.execute("SELECT COUNT(*) FROM evidence WHERE relationship_id = ?", (r["id"],)).fetchone()[0]
        arrow = "<->" if r["kind"] == "partnership" else "->"
        shares = ", ".join(x for x in (r["supplier_revenue_share"] is not None and f"{r['supplier_revenue_share']:g}% of supplier's revenue",
                                       r["customer_supply_share"] is not None and f"{r['customer_supply_share']:g}% of customer's {r['customer_share_scope'] or 'purchases'}") if x)
        print(f"  [{merge.level(r['confidence']):6} {r['confidence']}] tier {r['tier']} {r['status']:6} {r['supplier']} {arrow} {r['customer']} ({r['kind']}; {evidence} evidence){' - ' + shares if shares else ''}")
        quote = conn.execute("SELECT quote, locator, extractor FROM evidence WHERE id = ?", (r["primary_evidence_id"],)).fetchone()
        print(f"      {quote['extractor']}: {quote['quote'][:170]}{'…' if len(quote['quote']) > 170 else ''}")
    print(f"  {len(links)} links")

    print("\n=== Candidates ===")
    for r in conn.execute("SELECT status, COUNT(*) n FROM candidates GROUP BY status"):
        print(f"  {r['status']:17} {r['n']}")
    print("\n=== Rejected ===")
    for r in conn.execute("SELECT reason, rejected_by, COUNT(*) n FROM rejected GROUP BY reason, rejected_by ORDER BY n DESC"):
        print(f"  {r['n']:3} {r['reason']} ({r['rejected_by']})")
    for r in conn.execute("SELECT supplier_name, customer_name, reason, rejected_by, detail FROM rejected ORDER BY id LIMIT 25"):
        print(f"    - {r['supplier_name']} -> {r['customer_name']}: {r['reason']} ({r['rejected_by']}) {(r['detail'] or '')[:110]}")

    print("\n=== Jobs ===")
    for r in conn.execute("SELECT kind, status, COUNT(*) n FROM jobs GROUP BY kind, status ORDER BY kind, status"):
        print(f"  {r['kind']:9} {r['status']:9} {r['n']}")
    failed = conn.execute("SELECT kind, key, last_error FROM jobs WHERE status IN ('failed', 'dead') LIMIT 10").fetchall()
    for r in failed:
        print(f"    ! {r['kind']} {r['key']}: {(r['last_error'] or '')[:120]}")
    waiting = conn.execute("SELECT kind, key, run_after, last_error FROM jobs WHERE status = 'queued' AND (last_error LIKE 'waiting for%' OR last_error LIKE 'too big%')").fetchall()
    for r in waiting:
        print(f"    waiting: {r['kind']} {r['key']} until {r['run_after']}: {(r['last_error'] or '')[:100]}")

    print("\n=== Sheet against the database ===")
    overview = status.overview(conn)
    checks_waiting = (overview["cost"]["waiting_for_tomorrow"], conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'queued' AND last_error LIKE 'waiting for %'").fetchone()[0])
    month_start = stamp(control.month_start())
    checks = [
        ("links total", overview["links"]["total"], conn.execute("SELECT COUNT(*) FROM relationships WHERE status != 'ended' AND merged_into IS NULL").fetchone()[0]),
        ("links ended", overview["links"]["ended"], conn.execute("SELECT COUNT(*) FROM relationships WHERE status = 'ended' AND merged_into IS NULL").fetchone()[0]),
        ("cost this month", overview["cost"]["month"], round(conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM runs WHERE started_at >= ?", (month_start,)).fetchone()[0], 4)),
        ("cost read + verify", round(overview["cost"]["by_stage"]["read"] + overview["cost"]["by_stage"]["verify"], 4),
         round(conn.execute("SELECT COALESCE(SUM(r.cost_usd), 0) FROM runs r JOIN jobs j ON j.id = r.job_id WHERE j.kind IN ('read', 'verify') AND r.started_at >= ?", (month_start,)).fetchone()[0], 4)),
        ("companies' costs add up", round(sum(c["cost_usd"] for c in status.company_rows(conn)), 4),
         round(conn.execute("SELECT COALESCE(SUM(r.cost_usd), 0) FROM runs r JOIN jobs j ON j.id = r.job_id WHERE j.company_id IS NOT NULL AND r.started_at >= ?", (month_start,)).fetchone()[0], 4)),
        ("cost today", overview["cost"]["today"], round(conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM runs WHERE started_at >= ?", (stamp(control.day_start()),)).fetchone()[0], 4)),
    ]
    # the usage log (usage.sqlite) is kept per call; compare what it logged since this run started with what the runs recorded
    with usage_store._connect() as usage_conn:
        logged = usage_conn.execute("SELECT COALESCE(SUM(cost_usd), 0), COUNT(*) FROM ai_usage WHERE feature LIKE 'supply_chain_%' AND created_at >= ?",
                                    (since.astimezone().isoformat(timespec="seconds"),)).fetchone()
    in_runs = conn.execute("SELECT COALESCE(SUM(r.cost_usd), 0) FROM runs r JOIN jobs j ON j.id = r.job_id WHERE j.kind IN ('read', 'verify') AND r.started_at >= ?", (start,)).fetchone()[0]
    checks.append((f"runs' cost vs usage log since the start ({logged[1]} calls)", round(in_runs, 4), round(logged[0], 4)))
    checks.append(("attention total", overview["attention"]["total"],
                   conn.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('failed', 'dead')").fetchone()[0]
                   + conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'queued' AND attempts > 0 AND last_error IS NOT NULL").fetchone()[0]
                   + verifier.unchecked_count(conn)
                   + conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'queued' AND last_error LIKE 'too big for the budget%'").fetchone()[0]))
    checks.append(("jobs waiting for tomorrow", *checks_waiting))
    for name, sheet, database in checks:
        print(f"  {'OK ' if abs(sheet - database) < 1e-4 else 'DIFF'} {name}: sheet {sheet} / database {database}")
    problems = __import__("supply_chain.integrity", fromlist=["check"]).check(conn)
    print(f"  integrity.check(): {problems or 'no problems'}")


async def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--budget", type=float, default=0.50, help="this run's hard cap in US$ (default 0.50)")
    parser.add_argument("--companies", default="AMD,NVDA,MU,ANET", help="tickers of theme companies to run")
    parser.add_argument("--hold", default="", help="tickers to mark as held for this run")
    parser.add_argument("--holdings-from-backend", action="store_true", help="read the holdings from the dev backend's /positions")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--minutes", type=float, default=25)
    parser.add_argument("--report", action="store_true", help="only print the report")
    parser.add_argument("--copy-database", action="store_true", help="work on a temporary copy of supply_chain.sqlite (and its settings): "
                        "no job, link or setting is left in the real one (the Claude calls still cost real money and are logged in usage.sqlite)")
    args = parser.parse_args()

    if args.copy_database:
        folder = Path(tempfile.mkdtemp(prefix="pipeline-run-"))
        source = sqlite3.connect(db.DB_PATH)
        copy = sqlite3.connect(folder / db.DB_PATH.name)
        source.backup(copy)
        source.close(), copy.close()
        db.DB_PATH = folder / db.DB_PATH.name  # control.settings_path() follows it
        print(f"Working on a copy: {db.DB_PATH}")
    path = db.DB_PATH
    conn = db.open_graph(path)
    since = datetime.now(timezone.utc)
    if args.report:
        report(conn, since - timedelta(days=1))
        return
    themes.seed_themes(conn)
    wanted = [t.strip().upper() for t in args.companies.split(",") if t.strip()]
    ids = {}
    for ticker in wanted:
        company_id = company_for(conn, ticker)
        if company_id is None:
            print(f"{ticker}: not in the watch list, skipped")
        else:
            ids[ticker] = company_id
    held = [t.strip().upper() for t in args.hold.split(",") if t.strip()]
    if args.holdings_from_backend:
        positions = held_from_backend()
        if positions is None:
            print("Holdings: the dev backend isn't running with IB connected; no holdings used")
        else:
            held += [symbol for symbol, _ in positions]
            print(f"Holdings from IB: {', '.join(sorted({s for s, _ in positions})) or 'none'}")
    in_theme = [t for t in held if t in ids or company_for(conn, t)]
    previously_held = [r["id"] for r in conn.execute("SELECT id FROM companies WHERE held = 1")]  # put back at the end
    conn.execute("UPDATE companies SET held = 0")
    for ticker in set(in_theme):
        company_id = company_for(conn, ticker)
        conn.execute("UPDATE companies SET held = 1 WHERE id = ?", (company_id,))
        if ticker not in ids:
            ids[ticker] = company_id
    print(f"Running {', '.join(ids)} (held: {', '.join(sorted(set(in_theme))) or 'none'}) with a cap of {money(args.budget)}")

    orchestrator.limits.pacing = False
    orchestrator.limits.run_cap_usd = args.budget
    orchestrator.limits.run_since = since
    try:
        await run_pipeline(conn, path, list(ids.values()), args.workers, args.minutes)
    finally:
        conn.execute("UPDATE companies SET held = 0")
        for company_id in previously_held:
            conn.execute("UPDATE companies SET held = 1 WHERE id = ?", (company_id,))
    print(f"Merging: {merge.recompute_all(conn)}")
    report(conn, since)


if __name__ == "__main__":
    if not config.anthropic_api_key():
        sys.exit("No ANTHROPIC_API_KEY in .env")
    asyncio.run(main())
