"""Development check of the document chunker (#123) on real filings: not a test, nothing here runs in the app.

    cd backend && venv/bin/python scripts/chunk_report.py           # report on every filing in data/filings
    cd backend && venv/bin/python scripts/chunk_report.py --fetch   # first download a sample of AI hardware filings

For each filing it prints the form, the sections found, the chunk count and the estimated tokens, and flags a 10-K or
20-F without its risk factors or without customer / concentration notes, and a 10-K that fell back to "Full text".

The form comes from the documents table (filings the scout downloaded) or from data/filings/chunk_report.json, which
--fetch writes for the filings it downloads (they are not registered in the graph).
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sec_client  # noqa: E402
from supply_chain import chunker  # noqa: E402
from supply_chain.db import open_graph  # noqa: E402

MANIFEST = sec_client.filings_dir() / "chunk_report.json"
ANNUAL = ["NVDA", "AMD", "AVGO", "MRVL", "INTC", "QCOM", "MU", "AMAT", "LRCX", "KLAC", "SMCI", "DELL", "ANET", "CSCO", "AMKR",
          "WDC", "VRT", "ORCL", "CRWV", "GFS", "COHR", "TER", "JBL", "ALAB", "TSM", "ASML", "ARM"]
QUARTERLY = ["NVDA", "MU", "SMCI"]
AGREEMENTS = ["NVDA", "SMCI", "CRWV", "INTC", "AMD", "WDC", "GFS", "COHR"]
CONCENTRATION_NOTE = ("concentration", "customer", "segment", "geograph")


def load_manifest():
    return json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}


async def fetch_one(manifest, cik, filing, exhibits=False):
    saved = await sec_client.download(cik, filing["accession"], filing["primary_document"])
    folder = str(Path(saved["path"]).parent)
    if exhibits:
        for f in await sec_client.filing_files(cik, filing["accession"]):
            if chunker.exhibit_label(f["name"]):
                await sec_client.download(cik, filing["accession"], f["name"])
    manifest[folder] = {"form": filing["form"], "primary": filing["primary_document"], "filed": filing["filed"],
                        "items": filing.get("items") or []}


async def fetch_sample():
    manifest = load_manifest()

    async def latest(symbol, forms, count=1, items=None):
        cik = await sec_client.cik_for_ticker(symbol)
        if cik is None:
            print(f"  {symbol}: no CIK")
            return
        found = 0
        for filing in await sec_client.list_filings(cik, forms=forms):
            if items and not set(items) & set(filing.get("items") or []):
                continue
            if not filing.get("primary_document"):
                continue
            await fetch_one(manifest, cik, filing, exhibits=filing["form"] == "8-K")
            print(f"  {symbol} {filing['form']} {filing['filed']}")
            found += 1
            if found >= count:
                return

    for symbol in ANNUAL:
        await latest(symbol, ("10-K", "20-F"))
    for symbol in QUARTERLY:
        await latest(symbol, ("10-Q",))
    for symbol in AGREEMENTS:
        await latest(symbol, ("8-K",), items=("1.01", "1.02"))
    await latest("NVDA", ("8-K",), items=("2.02",))  # one that should give nothing
    MANIFEST.write_text(json.dumps(manifest, indent=1))


def filings():
    """[(folder, form, primary document)] for everything downloaded."""
    known = {}
    try:
        conn = open_graph()
        for row in conn.execute("SELECT kind, local_path FROM documents WHERE local_path IS NOT NULL"):
            path = Path(row["local_path"])
            known[str(path.parent)] = (row["kind"], path.name)
    except Exception as exc:  # the report still works on the manifest alone
        print(f"(documents table not read: {exc.__class__.__name__})")
    for folder, entry in load_manifest().items():
        known.setdefault(folder, (entry["form"], entry["primary"]))
    return sorted((folder, form, primary) for folder, (form, primary) in known.items() if (Path(folder) / primary).exists())


def problems(form, chunks):
    sections = {c.section for c in chunks}
    flags = []
    if form in ("10-K", "20-F"):
        if form == "10-K" and "Full text" in sections:
            flags.append("fell back to Full text")
        risk = "Item 1A" if form == "10-K" else "Item 3."
        if not any(s.startswith(risk) for s in sections):
            flags.append(f"no {risk} (risk factors)")
        notes = [s for s in sections if ", notes: " in s]
        if not notes:
            flags.append("no notes")
        elif not any(word in s.lower() for s in notes for word in CONCENTRATION_NOTE):
            flags.append("no customer / concentration / segment / geographic note")
    return flags


def report():
    rows = filings()
    if not rows:
        print("No filings in data/filings (run with --fetch, or let the pipeline download some)")
        return 0
    flagged = 0
    for folder, form, primary in rows:
        chunks = chunker.chunk_filing(folder, form, primary)
        flags = problems(form, chunks)
        flagged += bool(flags)
        name = "/".join(Path(folder).parts[-2:])
        print(f"\n{form:5} {name}/{primary}  {len(chunks)} chunks, {sum(c.tokens for c in chunks):,} tokens (estimated)"
              + (f"  !! {'; '.join(flags)}" if flags else ""))
        seen = {}
        for c in chunks:
            seen.setdefault((c.document, c.section), []).append(c.tokens)
        for (document, section), tokens in seen.items():
            where = "" if document == primary else f"[{document}] "
            print(f"    {where}{section[:110]}: {len(tokens)} x {max(tokens):,}")
    print(f"\n{len(rows)} filings, {flagged} flagged (chunker version {chunker.CHUNKER_VERSION})")
    return flagged


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--fetch", action="store_true", help="download a sample of filings first")
    if parser.parse_args().fetch:
        asyncio.run(fetch_sample())
    report()
