"""Checking the graph (#115). The schema refuses most mistakes when they're made; this looks for the rest,
and for damage from outside (a database edited by hand, foreign keys switched off)."""


def check(conn):
    """A list of problems in plain words; empty when the graph is sound."""
    problems = []
    for row in conn.execute("""SELECT r.id FROM relationships r
                               WHERE NOT EXISTS (SELECT 1 FROM evidence e WHERE e.relationship_id = r.id)"""):
        problems.append(f"relationship {row['id']} has no evidence")
    for row in conn.execute("""SELECT r.id FROM relationships r
                               WHERE EXISTS (SELECT 1 FROM evidence e WHERE e.relationship_id = r.id)
                                 AND NOT EXISTS (SELECT 1 FROM evidence e WHERE e.relationship_id = r.id AND e.id = r.primary_evidence_id)"""):
        problems.append(f"relationship {row['id']}'s primary evidence isn't its own")
    for row in conn.execute("""SELECT r.id FROM relationships r
                               WHERE r.tier > (SELECT MIN(e.tier) FROM evidence e WHERE e.relationship_id = r.id)"""):
        problems.append(f"relationship {row['id']} has a worse tier than its best evidence")
    for row in conn.execute("PRAGMA foreign_key_check"):
        problems.append(f"{row['table']} row {row['rowid']} points to a missing {row['parent']} row")
    return problems
