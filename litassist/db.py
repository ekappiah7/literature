"""SQLite storage for projects, searches, records and screening decisions.

Every search run and every screening decision is recorded with a timestamp so
that the search methods and the PRISMA flow can be reconstructed later.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    question TEXT DEFAULT '',
    review_type TEXT DEFAULT 'Scoping review',
    population TEXT DEFAULT '',
    concept TEXT DEFAULT '',
    context TEXT DEFAULT '',
    inclusion TEXT DEFAULT '',
    exclusion TEXT DEFAULT '',
    strategy TEXT DEFAULT '',
    zotero_collection TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS searches (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    query TEXT NOT NULL,
    filters TEXT DEFAULT '',
    run_at TEXT NOT NULL,
    hits INTEGER NOT NULL,
    retrieved INTEGER NOT NULL,
    new_records INTEGER NOT NULL,
    duplicates INTEGER NOT NULL,
    note TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    search_id INTEGER REFERENCES searches(id),
    source TEXT NOT NULL,
    pmid TEXT DEFAULT '',
    doi TEXT DEFAULT '',
    pmcid TEXT DEFAULT '',
    title TEXT DEFAULT '',
    abstract TEXT DEFAULT '',
    authors TEXT DEFAULT '[]',
    journal TEXT DEFAULT '',
    journal_abbrev TEXT DEFAULT '',
    year TEXT DEFAULT '',
    volume TEXT DEFAULT '',
    issue TEXT DEFAULT '',
    pages TEXT DEFAULT '',
    language TEXT DEFAULT '',
    pub_types TEXT DEFAULT '[]',
    mesh TEXT DEFAULT '[]',
    keywords TEXT DEFAULT '[]',
    added_at TEXT NOT NULL,
    ta_decision TEXT DEFAULT '',
    ta_reason TEXT DEFAULT '',
    ta_decided_at TEXT DEFAULT '',
    zotero_key TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_records_project ON records(project_id);
CREATE INDEX IF NOT EXISTS idx_records_pmid ON records(project_id, pmid);
CREATE INDEX IF NOT EXISTS idx_records_doi ON records(project_id, doi);

CREATE TABLE IF NOT EXISTS decision_log (
    id INTEGER PRIMARY KEY,
    record_id INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT DEFAULT '',
    decided_by TEXT NOT NULL DEFAULT 'researcher',
    decided_at TEXT NOT NULL
);
"""

JSON_FIELDS = ("authors", "pub_types", "mesh", "keywords")
RECORD_FIELDS = (
    "source", "pmid", "doi", "pmcid", "title", "abstract", "authors", "journal",
    "journal_abbrev", "year", "volume", "issue", "pages", "language",
    "pub_types", "mesh", "keywords",
)
DECISIONS = ("include", "exclude", "maybe")


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def _record_from_row(row: sqlite3.Row) -> dict:
    rec = dict(row)
    for field in JSON_FIELDS:
        rec[field] = json.loads(rec.get(field) or "[]")
    return rec


# Projects

PROJECT_FIELDS = (
    "question", "review_type", "population", "concept", "context",
    "inclusion", "exclusion", "strategy", "zotero_collection",
)


def create_project(conn, name: str, **fields) -> int:
    values = {k: fields.get(k, "") for k in PROJECT_FIELDS}
    if not values["review_type"]:
        values["review_type"] = "Scoping review"
    cur = conn.execute(
        f"INSERT INTO projects (name, {', '.join(PROJECT_FIELDS)}, created_at) "
        f"VALUES (?, {', '.join('?' * len(PROJECT_FIELDS))}, ?)",
        (name.strip(), *values.values(), now()),
    )
    conn.commit()
    return cur.lastrowid


def update_project(conn, project_id: int, **fields) -> None:
    updates = {k: v for k, v in fields.items() if k in PROJECT_FIELDS or k == "name"}
    if not updates:
        return
    sets = ", ".join(f"{k} = ?" for k in updates)
    conn.execute(f"UPDATE projects SET {sets} WHERE id = ?", (*updates.values(), project_id))
    conn.commit()


def list_projects(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM projects ORDER BY name")]


def get_project(conn, project_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return dict(row) if row else None


def delete_project(conn, project_id: int) -> None:
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()


# Records

def normalise_doi(doi: str) -> str:
    doi = (doi or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
    return doi


def find_duplicate(conn, project_id: int, pmid: str, doi: str) -> int | None:
    if pmid:
        row = conn.execute(
            "SELECT id FROM records WHERE project_id = ? AND pmid = ?", (project_id, pmid)
        ).fetchone()
        if row:
            return row["id"]
    doi = normalise_doi(doi)
    if doi:
        row = conn.execute(
            "SELECT id FROM records WHERE project_id = ? AND doi = ?", (project_id, doi)
        ).fetchone()
        if row:
            return row["id"]
    return None


def add_records(conn, project_id: int, search_id: int | None, records: list[dict]) -> tuple[int, int]:
    """Insert records, skipping any already in the project. Returns (new, duplicates)."""
    new = dup = 0
    for rec in records:
        rec = dict(rec)
        rec["doi"] = normalise_doi(rec.get("doi", ""))
        if find_duplicate(conn, project_id, rec.get("pmid", ""), rec["doi"]):
            dup += 1
            continue
        values = []
        for field in RECORD_FIELDS:
            value = rec.get(field, [] if field in JSON_FIELDS else "")
            values.append(json.dumps(value) if field in JSON_FIELDS else str(value or ""))
        conn.execute(
            f"INSERT INTO records (project_id, search_id, {', '.join(RECORD_FIELDS)}, added_at) "
            f"VALUES (?, ?, {', '.join('?' * len(RECORD_FIELDS))}, ?)",
            (project_id, search_id, *values, now()),
        )
        new += 1
    conn.commit()
    return new, dup


def list_records(conn, project_id: int, decision: str | None = None) -> list[dict]:
    sql = "SELECT * FROM records WHERE project_id = ?"
    params: list = [project_id]
    if decision == "undecided":
        sql += " AND ta_decision = ''"
    elif decision:
        sql += " AND ta_decision = ?"
        params.append(decision)
    sql += " ORDER BY id"
    return [_record_from_row(r) for r in conn.execute(sql, params)]


def get_record(conn, record_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
    return _record_from_row(row) if row else None


def set_decision(conn, record_id: int, decision: str, reason: str = "", decided_by: str = "researcher") -> None:
    if decision not in DECISIONS and decision != "":
        raise ValueError(f"Unknown decision: {decision}")
    stamp = now()
    conn.execute(
        "UPDATE records SET ta_decision = ?, ta_reason = ?, ta_decided_at = ? WHERE id = ?",
        (decision, reason.strip(), stamp if decision else "", record_id),
    )
    conn.execute(
        "INSERT INTO decision_log (record_id, stage, decision, reason, decided_by, decided_at) "
        "VALUES (?, 'title_abstract', ?, ?, ?, ?)",
        (record_id, decision or "cleared", reason.strip(), decided_by, stamp),
    )
    conn.commit()


def set_zotero_key(conn, record_id: int, key: str) -> None:
    conn.execute("UPDATE records SET zotero_key = ? WHERE id = ?", (key, record_id))
    conn.commit()


# Searches

def log_search(conn, project_id: int, source: str, query: str, hits: int, filters: str = "", note: str = "") -> int:
    cur = conn.execute(
        "INSERT INTO searches (project_id, source, query, filters, run_at, hits, retrieved, new_records, duplicates, note) "
        "VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, ?)",
        (project_id, source, query, filters, now(), hits, note),
    )
    conn.commit()
    return cur.lastrowid


def finish_search(conn, search_id: int, retrieved: int, new: int, duplicates: int) -> None:
    conn.execute(
        "UPDATE searches SET retrieved = ?, new_records = ?, duplicates = ? WHERE id = ?",
        (retrieved, new, duplicates, search_id),
    )
    conn.commit()


def list_searches(conn, project_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM searches WHERE project_id = ? ORDER BY id", (project_id,)
    )]


def counts(conn, project_id: int) -> dict:
    """Numbers for the project overview and the PRISMA-ScR flow diagram."""
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(ta_decision = 'include') AS include,
            SUM(ta_decision = 'exclude') AS exclude,
            SUM(ta_decision = 'maybe') AS maybe,
            SUM(ta_decision = '') AS undecided
        FROM records WHERE project_id = ?
        """,
        (project_id,),
    ).fetchone()
    s = conn.execute(
        "SELECT COALESCE(SUM(retrieved), 0) AS retrieved, COALESCE(SUM(duplicates), 0) AS duplicates "
        "FROM searches WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    return {
        "records_identified": s["retrieved"],
        "duplicates_removed": s["duplicates"],
        "records_screened": row["total"] or 0,
        "included": row["include"] or 0,
        "excluded": row["exclude"] or 0,
        "maybe": row["maybe"] or 0,
        "undecided": row["undecided"] or 0,
    }
