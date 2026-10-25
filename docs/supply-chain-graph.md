# Supply chain graph

Milestone 10 builds the foundation: a database of companies and who supplies whom, where every link
carries the evidence it came from. Milestone 11 fills it with AI extraction, 12 draws it, 13 adds an
analyst and a shared server. This page is the reference for the schema (#115) and the conventions every
later piece follows.

## Conventions

- **Direction.** A relationship is *supplier → customer*: the supplier sells to the customer.
- **Two dependencies, both optional.** Each is a percentage from 0 to 100 and NULL when no document says.
  - `supplier_revenue_share`: how much of the **supplier's** revenue comes from this customer
    ("Customer A was 23% of NVIDIA's revenue"). It shows how much the supplier depends on the customer.
  - `customer_supply_share`: how much of what the **customer** buys comes from this supplier, of
    `customer_share_scope` ("chips", "wafers", "everything it buys"). "TSMC makes all of Apple's chips" is
    100 with scope "chips". It shows how much the customer depends on one supplier, which is what an
    investor in the customer needs to see.
- **Every relationship has evidence.** An `evidence` row ties it to a `document`, with the exact quote, where
  in the document it was, the extractor, and the shares and date that statement gave. Each piece of evidence
  keeps its own shares; the relationship holds the current best (merged in #127).
- **Evidence tiers.** 1 = structured data (XBRL tags, published supplier lists), 2 = text read by an AI and
  verified, 3 = news. A relationship's tier is its best evidence's.
- **Nothing is deleted when a link ends.** Its status becomes `ended` (or `stale`), so a synced copy can be
  told. Candidates the verifier refuses go in `rejected`, with the quote and document, so they aren't extracted
  and checked again.
- **Unnamed customers.** Filings often say "Customer A". These become placeholder companies (`is_placeholder`,
  `placeholder_for` = the company whose filing used the label), hidden by default, so the evidence is kept and a
  resolver can link them to a real company later.
- **Time.** ISO 8601 text in UTC (`2026-10-25T09:30:00Z`); dates as `2026-10-25`. JSON is stored as text.

## How the evidence rule is enforced

The database refuses a relationship without evidence; it isn't left to the code that writes it.

- `relationships.primary_evidence_id` is required and is a **composite foreign key** to
  `evidence (relationship_id, id)`, so it must be evidence *for that relationship*.
- The key is **deferred**: both rows are written in one transaction (`graph.add_relationship`), and the commit
  fails if either is missing.
- `evidence.document_id` is required, so every piece of evidence names its source document.
- The primary evidence can't be deleted while it is primary (move it to other evidence first); deleting a
  relationship deletes its evidence.
- `supply_chain.integrity.check()` finds what's left: damage done from outside, such as a hand-edited file.

## Tables

```mermaid
erDiagram
    companies ||--o{ identifiers : "has"
    companies ||--o{ documents : "files"
    companies ||--o{ relationships : "supplies (supplier_id)"
    companies ||--o{ relationships : "buys (customer_id)"
    relationships ||--|{ evidence : "backed by"
    relationships ||--|| evidence : "primary_evidence_id"
    documents ||--o{ evidence : "source of"
    documents ||--o{ rejected : "source of"
    jobs ||--o{ runs : "attempts"
    runs ||--o{ evidence : "found"
    themes ||--o{ theme_companies : "includes"
    companies ||--o{ theme_companies : "in"
    companies ||--o{ jobs : "about"
    documents ||--o{ jobs : "about"

    companies { int id PK
        text name
        text country
        int is_placeholder
        int placeholder_for FK }
    identifiers { int company_id FK
        text scheme "ticker, isin, figi, cik, lei, wikidata ..."
        text market
        text value }
    documents { int id PK
        text source "sec, mops, asx ..."
        text kind
        text external_id "unique per source"
        text content_hash "SHA-256"
        text status }
    relationships { int id PK
        int supplier_id FK
        int customer_id FK
        real supplier_revenue_share "nullable"
        real customer_supply_share "nullable"
        text customer_share_scope
        int tier "1 2 3"
        text status "active stale ended"
        real confidence
        int primary_evidence_id FK }
    evidence { int id PK
        int relationship_id FK
        int document_id FK
        text quote
        text locator
        int tier
        text extractor
        real supplier_revenue_share
        real customer_supply_share
        text verification }
    rejected { int id PK
        int document_id FK
        text quote
        text reason
        text rejected_by }
    jobs { int id PK
        text kind
        text key
        text status
        int priority
        int attempts }
    runs { int id PK
        int job_id FK
        text outcome
        real cost_usd }
    themes { int id PK
        text slug }
    theme_companies { int theme_id FK
        int company_id FK
        text segment }
```

- `identifiers`: one company has many (tickers per market, ISIN, FIGI, CIK, LEI, Wikidata); `(scheme, market, value)`
  is unique, so a ticker can't belong to two companies.
- `jobs`: at most one open (queued or running) job per `(kind, key)`; higher `priority` runs first.
- `runs`: one per attempt, with the model, tokens and `cost_usd`, so a daily budget is a sum.
- Migrations: `backend/supply_chain/migrations.py`, applied in order, each in a transaction, with a checksum
  so an edited old migration is noticed. The database is `supply_chain.sqlite` (in `data/`, or Application Support
  in the Mac app).

## Customer concentration from XBRL (#120)

10-Ks tag each "major customer" percentage as `us-gaap:ConcentrationRiskPercentage1`, with dimensions for the counterparty (`srt:MajorCustomersAxis`, or a supplier / vendor axis) and the benchmark (revenue, accounts receivable, purchases). `xbrl.import_filing` reads the filing's XBRL instance (`<doc>_htm.xml`) and label file (`_lab.xml`) and writes each figure as a relationship with **tier 1** evidence (extractor `xbrl`) pointing at the 10-K: the quote is the fact as tagged ("Apple, Inc.: 91% of revenue, 2025-03-30 to 2026-03-28 [us-gaap:ConcentrationRiskPercentage1, MajorCustomersAxis = crus:AppleIncMember]"), the locator the fact and context ids, `stated_on` the period end.

| Member | What happens |
|---|---|
| Unnamed ("Customer A", "Major Customer One", "Undisclosed Customer 1", "Supplier A", "Company A") | A placeholder company for the filer, one per label **and fiscal year** ("Customer A (unnamed customer of CoreWeave, Inc., year to 2025-12-31)"), because this year's Customer A need not be last year's. Never sent to the name lookup. |
| Named ("Apple, Inc.", "HP Inc.", "Dell Inc.") | The name resolver (#119). A match links the real company; anything else goes to `rejected` (`unresolved_company`), not guessed. |
| Group ("Top Ten Customers", "Three Largest Customers", "Ablecom and Compuware") | Left out: not one company. |
| Narrowed by a region or product line | Left out. A business segment is kept as a note. |

Benchmarks: a revenue share fills `supplier_revenue_share` (the filer supplies the counterparty); a purchases share means the counterparty is the filer's **supplier** and fills `customer_supply_share` with the benchmark as scope ("Supplier A: 63.1% of purchases, total" for Super Micro); a receivables share is kept as a `share_note` on the evidence only. Revenue and receivables figures of the same label and year are one relationship. Other benchmarks ("Manufacturer Concentration") are left out. The same figure tagged twice keeps the more precise one. `graph.refresh_shares` sets a relationship's shares from its newest evidence, so an older filing loaded later doesn't overwrite a newer figure.

The scout queues an `xbrl` job (priority 55) for every new 10-K that has XBRL data. 10-Qs (quarterly shares) and 20-Fs (IFRS tags) are not read yet.

## Running it and watching it (#122)

Settings > Supply chain pipeline has the **Run pipeline** switch (off by default: it uses the user's Anthropic key when it reads reports with Claude), a **monthly budget** in US dollars (default US$10) and a status line with **Open pipeline…**, which opens the pipeline sheet. The switches are kept in `pipeline_settings.json` next to the database (`supply_chain/control.py`); until someone chooses, "run" follows `PIPELINE` in `.env`.

The supervisor in `worker.keep_running` checks every 5 seconds: workers run while the pipeline is on, not paused and this month's spending (the sum of `runs.cost_usd` since the 1st, UTC) is under the budget. When that stops being true the workers stop (the job in hand goes back in the queue, no attempt counted) and they start again by themselves, e.g. next month. It also loads the watch list from `seed/themes.json` at start.

The sheet (`GET /pipeline`, `/pipeline/companies`, `/pipeline/log`, built by `supply_chain/status.py`) shows only what the tables say: Coverage (watched companies whose latest filing is downloaded), Links (active relationships, new in 7 days, ended), Needs attention (jobs failed for good, plus ones waiting to retry) and Cost (month against budget). A company is *failed* if one of its jobs failed for good, *reading* while a job runs, *waiting* while jobs are queued (or not yet looked at), *up to date* when everything is done, and *not on EDGAR* when SEC has no filings for it. The log is built from runs (RUN, DONE, FAIL, SCOUT) and relationships (LINK). Retry requeues failed jobs (`POST /pipeline/retry`); Run now looks at every watched company again and resumes a pause.

## Matching names to companies (#119)

Filings name companies in their own words ("TSMC", "Micron Technology, Inc.", "Customer A"). `resolver.resolve(conn, name)` maps a name to a company, and says how:

1. **Identifier store**: a company in the graph with that name, or a stored alias (`name` identifiers).
2. **Index data**: S&P 500, Nasdaq 100, Dow and ASX members (names and tickers from `constituents.py`).
3. **OpenFIGI**: a name search (works without a key at 25 a minute; `OPENFIGI_API_KEY` raises it to 250); accepted only when every equity listing with that name belongs to one share class.

Names are compared after normalising (case, accents, punctuation, `&`/`and`, `N.V.`/`NV`, and endings such as Inc, Corp, Co, Ltd, Limited, plc, AG, SA removed) plus a few aliases (`TSMC`). Nothing looser: a name that merely *starts* with a known company ("Apple Operations International Limited") is skipped as a probable subsidiary, a name two different companies share is skipped as ambiguous, and "Customer A" is skipped as unnamed. Share classes (GOOG / GOOGL) count as one company when their company market cap is the same. At OpenFIGI, depositary receipts (ADRs) of the same name are the same company, and an answer without the name is retried without the legal ending ("Wistron Corporation" -> "wistron", "Lenovo Group Limited" -> "lenovo group"). Common short names filings use are aliases (AMD, Amazon, Micron, Marvell, Meta, Dell); "Samsung" alone is left unmatched because it names a whole group.

Each decision is saved in `name_resolutions` (matched: `method`; skipped: `reason` and `detail`), with the identifiers that were learnt carrying the method as their `source`. The same name is not looked up twice; a skipped name is looked at again after 30 days. OpenFIGI being unreachable is not a decision and is not saved.

## Job queue and workers (#116)

Pipeline work is a **job** (`supply_chain/jobs.py`): a kind (`scout`, `download`, `read` ...) and a key (what it is
about). At most one open job exists per kind and key, so queueing the same work twice does nothing (except that the
more urgent priority wins). Workers (`supply_chain/worker.py`) claim jobs atomically, highest priority first, and
run the handler registered for the kind (`@handler("scout")`).

```
queued -> running -> done
                  -> queued again after a back-off (30 s, 2 min, 8 min ... up to 6 h) on an error
                  -> dead   when out of attempts (3 by default)
                  -> failed on a permanent error (the input is wrong)
```

- Every attempt writes a `runs` row (outcome, model, tokens, `cost_usd`), so a daily budget is one sum.
- **Survives restarts.** The queue is in the database. At start the runner takes back every job a previous
  process left running; on an orderly stop (the app quitting) the job in hand goes back without costing an
  attempt; after a crash the lost attempt counts, so a job that kills its worker every time ends up dead.
- Several workers can run side by side (`PIPELINE_WORKERS`, default 2). Only one runner process should use a
  database. A worker only claims kinds it has a handler for.
- **Off by default**: `PIPELINE=1` in `.env` starts the workers with the app, because they download filings and
  spend AI budget.

## What comes next

| Issue | Piece | Uses |
|---|---|---|
| #116 | job queue and workers (done) | `jobs`, `runs` |
| #117 | SEC client (done; `sec_client.py`, shared with the boards job; `supply_chain/sec.py` registers and downloads filings) | `documents` (hash, status) |
| #121 | AI hardware seed (done; 59 companies in `backend/seed/themes.json`, loaded by `supply_chain/themes.py`) | `companies`, `identifiers`, `themes` |
| #119 | name resolver (done; `supply_chain/resolver.py` + `openfigi.py`) | `identifiers` |
| #118 | SEC scout (done; `supply_chain/scout.py`: watches theme companies for 10-K, 10-Q, 8-K and queues downloads) | `themes`, `documents`, `jobs` |
| #120 | XBRL customer concentration (done; `supply_chain/xbrl.py`) | `relationships`, `evidence`, placeholder companies |
| #122 | pipeline status sheet (done; Settings group + `PipelineSheet.jsx`, `supply_chain/status.py`, `control.py`, `routers/pipeline.py`) | counts of `jobs`, `runs`, `documents` |
| M11 | chunker, reader, verifier, orchestrator, merge | `evidence`, `rejected`, `runs.cost_usd`, `relationships.confidence` |
| M12 | graph API and explorer | indexes on both ends of `relationships`; chains of up to three layers by a recursive query |
| M13 | server, export, sync | plain SQL (Postgres), `updated_at`, `ended` instead of deletes |
