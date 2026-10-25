"""The graph's schema as numbered migrations (#115). Each one runs once, in order, in a transaction,
and is recorded in schema_migrations with a checksum, so an edited old migration is noticed. Never
change a migration that has shipped: add a new one.

The SQL is plain and portable (no SQLite-only features), because the pipeline moves to Postgres on a
server in Milestone 13 (#148): text timestamps in ISO form (UTC), JSON kept as text, integer ids,
partial indexes and deferred foreign keys, which Postgres has too. The only change needed there is
the id column syntax (INTEGER PRIMARY KEY -> GENERATED ... AS IDENTITY) and creating the two circular
foreign keys (relationships <-> evidence) with ALTER TABLE after both tables exist.
"""

# Direction: the SUPPLIER sells to the CUSTOMER. Shares are percentages from 0 to 100:
#   supplier_revenue_share  how much of the supplier's revenue comes from this customer
#                           (the supplier's dependency: "Customer A is 23% of NVIDIA's revenue")
#   customer_supply_share   how much of what the customer buys (of customer_share_scope: "chips",
#                           "wafers", or "everything it buys") comes from this supplier
#                           (the customer's dependency: "TSMC makes all of Apple's chips" = 100)
# Either is NULL when no filing says so. Evidence tiers: 1 structured data (XBRL, published supplier
# lists), 2 text read by an AI and verified, 3 news.

INITIAL = """
CREATE TABLE companies (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    country TEXT,                      -- ISO 3166 alpha-2
    sector TEXT,
    industry TEXT,
    -- "Customer A" in a filing that doesn't name it: kept so its evidence isn't lost, linked to a real
    -- company when it is resolved. placeholder_for is the company whose filing used the label.
    is_placeholder INTEGER NOT NULL DEFAULT 0 CHECK (is_placeholder IN (0, 1)),
    placeholder_for INTEGER REFERENCES companies (id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (is_placeholder = 0 OR placeholder_for IS NOT NULL)
);
CREATE INDEX companies_name ON companies (name);

CREATE TABLE identifiers (
    id INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies (id) ON DELETE CASCADE,
    scheme TEXT NOT NULL,              -- ticker, isin, figi, share_class_figi, cik, lei, wikidata, ... (graph.IDENTIFIER_SCHEMES)
    value TEXT NOT NULL CHECK (length(trim(value)) > 0),
    market TEXT NOT NULL DEFAULT '',   -- the exchange or market a ticker belongs to (US, ASX, TWSE); '' for global ids
    source TEXT,                       -- where we learnt it (openfigi, sec, seed, ...)
    created_at TEXT NOT NULL,
    UNIQUE (scheme, market, value)
);
CREATE INDEX identifiers_company ON identifiers (company_id);

CREATE TABLE documents (
    id INTEGER PRIMARY KEY,
    company_id INTEGER REFERENCES companies (id),   -- who filed or published it
    source TEXT NOT NULL,              -- sec, mops, asx, edinet, dart, web, news
    kind TEXT NOT NULL,                -- 10-K, 10-Q, 8-K, annual_report, announcement, supplier_list, ...
    external_id TEXT NOT NULL,         -- the source's own id (SEC accession number, announcement id) or a hash of the url
    url TEXT NOT NULL,
    title TEXT,
    filed_at TEXT,                     -- date
    period_end TEXT,                   -- date the report covers
    language TEXT,
    content_hash TEXT,                 -- SHA-256 of the downloaded bytes; NULL until downloaded
    size_bytes INTEGER,
    local_path TEXT,
    fetched_at TEXT,
    status TEXT NOT NULL DEFAULT 'discovered' CHECK (status IN ('discovered', 'downloaded', 'processed', 'failed')),
    created_at TEXT NOT NULL,
    UNIQUE (source, external_id)
);
CREATE INDEX documents_company ON documents (company_id, filed_at);
CREATE INDEX documents_hash ON documents (content_hash);

CREATE TABLE themes (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE theme_companies (
    theme_id INTEGER NOT NULL REFERENCES themes (id) ON DELETE CASCADE,
    company_id INTEGER NOT NULL REFERENCES companies (id) ON DELETE CASCADE,
    segment TEXT,                      -- e.g. GPUs, memory, foundry, packaging
    added_at TEXT NOT NULL,
    PRIMARY KEY (theme_id, company_id)
);

CREATE TABLE runs (
    id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES jobs (id),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    outcome TEXT NOT NULL DEFAULT 'running' CHECK (outcome IN ('running', 'ok', 'error', 'retry', 'abandoned')),
    error TEXT,
    worker TEXT,
    model TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd REAL,                     -- priced when the run finished: a daily budget is a sum over this
    notes TEXT                         -- JSON: counts of what the run found
);
CREATE INDEX runs_job ON runs (job_id);
CREATE INDEX runs_started ON runs (started_at);

CREATE TABLE jobs (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,                -- scout, download, resolve, xbrl, chunk, read, verify, merge, ...
    key TEXT NOT NULL,                 -- what it works on (an accession number, a company id): at most one open job per kind and key
    payload TEXT NOT NULL DEFAULT '{}',-- JSON
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'failed', 'dead', 'cancelled')),
    priority INTEGER NOT NULL DEFAULT 100,          -- higher runs first (your holdings' companies get more)
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    run_after TEXT NOT NULL,           -- not before this time (retries back off)
    locked_by TEXT,
    locked_at TEXT,
    last_error TEXT,
    company_id INTEGER REFERENCES companies (id),
    document_id INTEGER REFERENCES documents (id),
    parent_job_id INTEGER REFERENCES jobs (id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE UNIQUE INDEX jobs_open_key ON jobs (kind, key) WHERE status IN ('queued', 'running');
CREATE INDEX jobs_pick ON jobs (status, priority DESC, run_after);

CREATE TABLE relationships (
    id INTEGER PRIMARY KEY,
    supplier_id INTEGER NOT NULL REFERENCES companies (id),
    customer_id INTEGER NOT NULL REFERENCES companies (id),
    kind TEXT NOT NULL DEFAULT 'supplies',          -- graph.RELATIONSHIP_KINDS
    what TEXT,                                      -- what is supplied: "memory chips", "foundry services"
    supplier_revenue_share REAL CHECK (supplier_revenue_share IS NULL OR (supplier_revenue_share >= 0 AND supplier_revenue_share <= 100)),
    customer_supply_share REAL CHECK (customer_supply_share IS NULL OR (customer_supply_share >= 0 AND customer_supply_share <= 100)),
    customer_share_scope TEXT,                      -- what customer_supply_share is a share of: "chips", "total purchases"
    shares_as_of TEXT,                              -- date the shares are for
    confidence REAL NOT NULL DEFAULT 0 CHECK (confidence >= 0 AND confidence <= 1),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'stale', 'ended')),   -- ended links stay (never deleted: sync needs to say they ended)
    tier INTEGER NOT NULL CHECK (tier IN (1, 2, 3)),  -- the best evidence tier behind it
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    ended_at TEXT,
    -- Where it came from: the evidence row that first established it. The foreign key is composite, so
    -- that row must be evidence FOR THIS relationship, and deferred, so both rows are written in one
    -- transaction (graph.add_relationship) and the commit fails if either is missing.
    primary_evidence_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (supplier_id <> customer_id),
    UNIQUE (supplier_id, customer_id, kind),
    FOREIGN KEY (id, primary_evidence_id) REFERENCES evidence (relationship_id, id) DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX relationships_supplier ON relationships (supplier_id, status);
CREATE INDEX relationships_customer ON relationships (customer_id, status);

CREATE TABLE evidence (
    id INTEGER PRIMARY KEY,
    relationship_id INTEGER NOT NULL REFERENCES relationships (id) ON DELETE CASCADE,
    document_id INTEGER NOT NULL REFERENCES documents (id),
    quote TEXT NOT NULL CHECK (length(trim(quote)) > 0),   -- the exact words (or for XBRL, the fact as tagged)
    quote_hash TEXT NOT NULL,                              -- SHA-256 of the normalised quote: the same quote isn't stored twice
    locator TEXT,                                          -- where in the document: "Item 1A, p. 12", an XBRL context
    tier INTEGER NOT NULL CHECK (tier IN (1, 2, 3)),
    extractor TEXT NOT NULL,                               -- xbrl, supplier_list, reader, news, manual
    supplier_revenue_share REAL CHECK (supplier_revenue_share IS NULL OR (supplier_revenue_share >= 0 AND supplier_revenue_share <= 100)),
    customer_supply_share REAL CHECK (customer_supply_share IS NULL OR (customer_supply_share >= 0 AND customer_supply_share <= 100)),
    customer_share_scope TEXT,
    share_note TEXT,
    stated_on TEXT,                                        -- date the statement is about
    verification TEXT NOT NULL DEFAULT 'unchecked' CHECK (verification IN ('unchecked', 'verified', 'failed')),
    run_id INTEGER REFERENCES runs (id),
    created_at TEXT NOT NULL,
    UNIQUE (relationship_id, id),
    UNIQUE (relationship_id, document_id, quote_hash)
);
CREATE INDEX evidence_document ON evidence (document_id);

CREATE TABLE rejected (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents (id),
    run_id INTEGER REFERENCES runs (id),
    supplier_name TEXT,                -- the names as they were extracted
    customer_name TEXT,
    supplier_id INTEGER REFERENCES companies (id),
    customer_id INTEGER REFERENCES companies (id),
    quote TEXT NOT NULL CHECK (length(trim(quote)) > 0),
    candidate_hash TEXT NOT NULL,      -- SHA-256 of names + quote: a rejected candidate isn't extracted and checked again
    payload TEXT,                      -- JSON of the whole candidate
    reason TEXT NOT NULL,              -- quote_not_found, not_a_supply_relationship, wrong_direction, unresolved_company, duplicate, ...
    detail TEXT,
    rejected_by TEXT NOT NULL CHECK (rejected_by IN ('verifier', 'rule', 'human')),
    created_at TEXT NOT NULL,
    UNIQUE (document_id, candidate_hash)
);
"""

NAME_RESOLUTIONS = """
-- How each company name from a filing was (or wasn't) matched to a company (#119): the decision is kept so the same
-- name isn't looked up again, and a skipped name says why
CREATE TABLE name_resolutions (
    id INTEGER PRIMARY KEY,
    name_key TEXT NOT NULL UNIQUE,     -- the name normalised (resolver.name_key)
    name TEXT NOT NULL,                -- as first seen
    status TEXT NOT NULL CHECK (status IN ('matched', 'skipped')),
    company_id INTEGER REFERENCES companies (id),
    method TEXT,                       -- identifier_store, index_data, openfigi (matched only)
    reason TEXT,                       -- skipped only: unnamed, no_match, ambiguous, possible_subsidiary, conflict
    detail TEXT,                       -- the candidates considered, in plain words
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK ((status = 'matched' AND company_id IS NOT NULL AND method IS NOT NULL) OR (status = 'skipped' AND reason IS NOT NULL))
);
CREATE INDEX name_resolutions_company ON name_resolutions (company_id);
"""

READER = """
-- One row per chunk the Reader (#124) sent to Claude, so a job retried after a failure doesn't read (and pay for) the
-- same chunk twice. Chunks are identified by the chunker's version and number within the document.
CREATE TABLE chunk_reads (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents (id),
    chunker_version INTEGER NOT NULL,
    chunk_number INTEGER NOT NULL,
    locator TEXT NOT NULL,
    text_hash TEXT NOT NULL,           -- SHA-256 of the chunk text
    run_id INTEGER REFERENCES runs (id),
    model TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd REAL,
    found INTEGER NOT NULL,            -- relationships the model returned for the chunk
    read_at TEXT NOT NULL,
    UNIQUE (document_id, chunker_version, chunk_number)
);

-- What the Reader found: a claim and its quote, waiting for the Verifier (#125). Never a relationship by itself.
-- Direction as in relationships (the supplier sells to the customer); a partnership is stored with the filer as
-- supplier, but has no direction.
CREATE TABLE candidates (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents (id),
    chunk_read_id INTEGER NOT NULL REFERENCES chunk_reads (id),
    run_id INTEGER REFERENCES runs (id),
    kind TEXT NOT NULL CHECK (kind IN ('supplies', 'partnership')),
    counterparty_role TEXT NOT NULL CHECK (counterparty_role IN ('supplier', 'customer', 'partner')),
    supplier_name TEXT NOT NULL,       -- as written (the filer: its own name)
    customer_name TEXT NOT NULL,
    supplier_is_filer INTEGER NOT NULL CHECK (supplier_is_filer IN (0, 1)),
    customer_is_filer INTEGER NOT NULL CHECK (customer_is_filer IN (0, 1)),
    supplier_unnamed INTEGER NOT NULL DEFAULT 0 CHECK (supplier_unnamed IN (0, 1)),   -- "Customer A": the name is the label
    customer_unnamed INTEGER NOT NULL DEFAULT 0 CHECK (customer_unnamed IN (0, 1)),
    supplier_id INTEGER REFERENCES companies (id),   -- NULL only for an unnamed counterparty
    customer_id INTEGER REFERENCES companies (id),
    resolved_by TEXT,                  -- how the counterparty's name was matched (resolver method)
    what TEXT,
    supplier_revenue_share REAL CHECK (supplier_revenue_share IS NULL OR (supplier_revenue_share >= 0 AND supplier_revenue_share <= 100)),
    customer_supply_share REAL CHECK (customer_supply_share IS NULL OR (customer_supply_share >= 0 AND customer_supply_share <= 100)),
    customer_share_scope TEXT,
    share_as_written TEXT,             -- "48% of total revenue", "substantially all"
    share_dropped TEXT,                -- why a share the model gave was removed: "supplier_revenue_share: digits_not_in_quote"
    period_as_written TEXT,
    stated_on TEXT,                    -- date
    ended INTEGER NOT NULL DEFAULT 0 CHECK (ended IN (0, 1)),
    quote TEXT NOT NULL CHECK (length(trim(quote)) > 0),
    locator TEXT NOT NULL,             -- the paragraph holding the quote: "Item 1A. Risk Factors, paragraph 41 [chunker v1]"
    context TEXT NOT NULL,             -- that paragraph and its neighbours: all the Verifier sees besides the claim
    candidate_hash TEXT NOT NULL,      -- names + kind + quote: what the overlap between chunks finds twice is kept once
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'supported', 'partly_supported', 'not_supported', 'linked')),
    verdict TEXT,                      -- JSON from the Verifier
    verified_run_id INTEGER REFERENCES runs (id),
    relationship_id INTEGER REFERENCES relationships (id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (document_id, candidate_hash)
);
CREATE INDEX candidates_pending ON candidates (status, document_id);
"""

VERIFIED_EVIDENCE = """
-- Who checked a piece of evidence (#125): the model that actually answered the Verifier (a refusal fallback can answer in
-- place of config.VERIFIER_MODEL). NULL for evidence nobody checked (XBRL facts are structured data).
ALTER TABLE evidence ADD COLUMN verified_by TEXT;
-- The statement says the relationship has ended or will end; the merge (#127) ends the link from the newest one.
ALTER TABLE evidence ADD COLUMN states_ended INTEGER NOT NULL DEFAULT 0 CHECK (states_ended IN (0, 1));
"""

VERIFY_ATTEMPTS = """
-- A candidate the Verifier couldn't check (the fallback declined too, or the answer skipped it twice) is tried once more
-- after a wait, then left for the pipeline sheet's Needs attention, so the scheduler never pays for it in a loop.
ALTER TABLE candidates ADD COLUMN verify_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE candidates ADD COLUMN verify_after TEXT;   -- not checked again before this time
"""

# (version, name, sql). Add new migrations at the end.
MIGRATIONS = [
    (1, "initial graph schema (#115)", INITIAL),
    (2, "company name resolutions (#119)", NAME_RESOLUTIONS),
    (3, "chunk reads and Reader candidates (#124)", READER),
    (4, "verified_by and states_ended on evidence (#125)", VERIFIED_EVIDENCE),
    (5, "verify attempts on candidates (#125)", VERIFY_ATTEMPTS),
]
