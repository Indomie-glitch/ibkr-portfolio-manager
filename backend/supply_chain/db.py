"""Opening the graph database (#115): the file, foreign keys on, transactions, and running migrations."""
import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from config import DATA_DIR
from supply_chain.migrations import MIGRATIONS

DB_PATH = DATA_DIR / "supply_chain.sqlite"


class SchemaError(Exception):
    """The database doesn't match this code's migrations (a newer database, or an edited migration)."""


def now():
    """The time as stored everywhere in the graph: ISO 8601, UTC, to the second."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path=None):
    """A connection with rows as dicts and foreign keys enforced (SQLite leaves them off by default).
    Statements run in autocommit; group writes with transaction()."""
    path = path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


@contextmanager
def transaction(conn):
    """One atomic write. The deferred foreign keys (a relationship must have its evidence) are checked
    at the commit, which raises sqlite3.IntegrityError and undoes everything."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def checksum(sql):
    return hashlib.sha256(sql.encode()).hexdigest()


def migrate(conn, migrations=MIGRATIONS):
    """Runs the migrations not yet applied, oldest first, each in its own transaction. Returns the
    versions applied. Raises SchemaError for a database newer than the code, or one whose applied
    migration no longer matches the code's."""
    conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)""")
    applied = {r["version"]: r["checksum"] for r in conn.execute("SELECT version, checksum FROM schema_migrations")}
    known = {version: sql for version, _, sql in migrations}
    for version, stored in applied.items():
        if version not in known:
            raise SchemaError(f"The database is at version {max(applied)}, newer than this code's {max(known)}. Update the app.")
        if stored != checksum(known[version]):
            raise SchemaError(f"Migration {version} was changed after it was applied. Add a new migration instead.")
    done = []
    for version, name, sql in sorted(migrations):
        if version in applied:
            continue
        script = (f"BEGIN IMMEDIATE;\n{sql}\nINSERT INTO schema_migrations (version, name, checksum, applied_at) "
                  f"VALUES ({version}, '{name.replace(chr(39), chr(39) * 2)}', '{checksum(sql)}', '{now()}');\nCOMMIT;")
        try:
            conn.executescript(script)
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        done.append(version)
    return done


def open_graph(path=None):
    """The graph database, created and brought up to date if needed."""
    conn = connect(path)
    applied = migrate(conn)
    if 6 in applied or 8 in applied:  # the merge rules (#127) or the new confidence rule (#333) arrived: score every existing link
        from supply_chain import merge  # here: merge imports graph, which imports this module
        merge.recompute_all(conn)
    return conn


def version(conn):
    row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
    return row["v"] or 0
