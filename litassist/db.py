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


# Columns added after the first release, so older databases are upgraded in place.
ADDED_COLUMNS = {
    "projects": ["exclusion_reasons", "ft_reasons", "chart_fields"],
    "records": [
        "ai_decision", "ai_reason", "ai_criterion", "ai_confidence", "ai_model", "ai_at",
        "norm_title", "openalex_id",
        "second_decision", "second_reason", "second_at",
        "oa_url", "pdf_path", "ft_decision", "ft_reason", "ft_at",
        "chart", "chart_status", "chart_model", "chart_at",
    ],
}

DEFAULT_EXCLUSION_REASONS = [
    "Wrong population", "Wrong concept", "Wrong context or setting", "No outcome data",
    "Review, editorial or commentary", "Animal or laboratory study", "Duplicate", "Other",
]
DEFAULT_FT_REASONS = [
    "Full text not available", "Wrong population", "Wrong concept", "Wrong context or setting",
    "No usable outcome data", "Conference abstract without data", "Duplicate publication", "Other",
]


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    for table, columns in ADDED_COLUMNS.items():
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for col in columns:
            if col not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_records_title ON records(project_id, norm_title)")
    for row in conn.execute("SELECT id, title FROM records WHERE norm_title = '' OR norm_title IS NULL").fetchall():
        conn.execute("UPDATE records SET norm_title = ? WHERE id = ?", (normalise_title(row["title"]), row["id"]))
    conn.commit()
    return conn


def _record_from_row(row: sqlite3.Row) -> dict:
    rec = dict(row)
    for field in JSON_FIELDS:
        rec[field] = json.loads(rec.get(field) or "[]")
    rec["chart"] = json.loads(rec.get("chart") or "{}")
    for key, value in rec.items():
        if value is None:
            rec[key] = ""
    return rec


# Projects

PROJECT_FIELDS = (
    "question", "review_type", "population", "concept", "context",
    "inclusion", "exclusion", "strategy", "zotero_collection",
    "exclusion_reasons", "ft_reasons", "chart_fields",
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


def reasons(project: dict, stage: str = "title_abstract") -> list[str]:
    """Exclusion reasons for a project, falling back to the defaults."""
    text = project.get("exclusion_reasons" if stage == "title_abstract" else "ft_reasons") or ""
    items = [line.strip() for line in text.splitlines() if line.strip()]
    return items or (DEFAULT_EXCLUSION_REASONS if stage == "title_abstract" else DEFAULT_FT_REASONS)


def list_projects(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM projects ORDER BY name")]


def get_project(conn, project_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return dict(row) if row else None


def delete_project(conn, project_id: int) -> None:
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()


# Records

def normalise_title(title: str) -> str:
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in (title or "")).split())


def normalise_doi(doi: str) -> str:
    doi = (doi or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
    return doi


def find_duplicate(conn, project_id: int, pmid: str, doi: str, title: str = "", year: str = "") -> int | None:
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
    norm = normalise_title(title)
    if len(norm) >= 25:
        for row in conn.execute(
            "SELECT id, year FROM records WHERE project_id = ? AND norm_title = ?", (project_id, norm)
        ):
            if not year or not row["year"] or abs(int(row["year"][:4] or 0) - int(str(year)[:4] or 0)) <= 1:
                return row["id"]
    return None


def add_records(conn, project_id: int, search_id: int | None, records: list[dict]) -> tuple[int, int]:
    """Insert records, skipping any already in the project. Returns (new, duplicates)."""
    new = dup = 0
    for rec in records:
        rec = dict(rec)
        rec["doi"] = normalise_doi(rec.get("doi", ""))
        if find_duplicate(conn, project_id, rec.get("pmid", ""), rec["doi"], rec.get("title", ""), rec.get("year", "")):
            dup += 1
            continue
        values = []
        for field in RECORD_FIELDS:
            value = rec.get(field, [] if field in JSON_FIELDS else "")
            values.append(json.dumps(value) if field in JSON_FIELDS else str(value or ""))
        conn.execute(
            f"INSERT INTO records (project_id, search_id, {', '.join(RECORD_FIELDS)}, added_at, norm_title, openalex_id) "
            f"VALUES (?, ?, {', '.join('?' * len(RECORD_FIELDS))}, ?, ?, ?)",
            (project_id, search_id, *values, now(), normalise_title(rec.get("title", "")), rec.get("openalex_id", "")),
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


def set_ai_suggestion(conn, record_id: int, result: dict) -> None:
    conn.execute(
        "UPDATE records SET ai_decision = ?, ai_reason = ?, ai_criterion = ?, ai_confidence = ?, "
        "ai_model = ?, ai_at = ? WHERE id = ?",
        (result["decision"], result["reason"], result["criterion"], result["confidence"],
         result.get("model", ""), now(), record_id),
    )
    conn.commit()


def list_by_ai(conn, project_id: int, ai_decision: str) -> list[dict]:
    """Unscreened records with a given AI suggestion."""
    return [_record_from_row(r) for r in conn.execute(
        "SELECT * FROM records WHERE project_id = ? AND ta_decision = '' AND ai_decision = ? ORDER BY id",
        (project_id, ai_decision),
    )]


def ai_agreement(conn, project_id: int) -> dict:
    """How often the AI suggestion matched the researcher's decision."""
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS compared,
            SUM(ai_decision = ta_decision) AS agreed,
            SUM(ai_decision = 'exclude' AND ta_decision IN ('include', 'maybe')) AS ai_would_miss
        FROM records
        WHERE project_id = ? AND ta_decision != '' AND ai_decision != ''
        """,
        (project_id,),
    ).fetchone()
    pending = conn.execute(
        "SELECT COUNT(*) FROM records WHERE project_id = ? AND ai_decision = ''", (project_id,)
    ).fetchone()[0]
    return {"compared": row["compared"] or 0, "agreed": row["agreed"] or 0,
            "ai_would_miss": row["ai_would_miss"] or 0, "without_ai": pending}


def set_second_decision(conn, record_id: int, decision: str, reason: str = "") -> None:
    if decision not in DECISIONS:
        raise ValueError(f"Unknown decision: {decision}")
    stamp = now()
    conn.execute("UPDATE records SET second_decision = ?, second_reason = ?, second_at = ? WHERE id = ?",
                 (decision, reason.strip(), stamp, record_id))
    conn.execute(
        "INSERT INTO decision_log (record_id, stage, decision, reason, decided_by, decided_at) "
        "VALUES (?, 'title_abstract', ?, ?, 'second screener', ?)",
        (record_id, decision, reason.strip(), stamp),
    )
    conn.commit()


def screener_agreement(conn, project_id: int) -> dict:
    """Agreement between the researcher and the second screener, with Cohen's kappa."""
    rows = conn.execute(
        "SELECT ta_decision, second_decision FROM records WHERE project_id = ? "
        "AND ta_decision != '' AND second_decision != ''",
        (project_id,),
    ).fetchall()
    n = len(rows)
    second_total = conn.execute(
        "SELECT COUNT(*) FROM records WHERE project_id = ? AND second_decision != ''", (project_id,)
    ).fetchone()[0]
    if not n:
        return {"compared": 0, "agreed": 0, "percent": None, "kappa": None, "second_screened": second_total,
                "disagreements": []}
    agreed = sum(a == b for a, b in rows)
    po = agreed / n
    pe = sum(
        (sum(a == c for a, _ in rows) / n) * (sum(b == c for _, b in rows) / n) for c in DECISIONS
    )
    kappa = None if pe == 1 else (po - pe) / (1 - pe)
    return {"compared": n, "agreed": agreed, "percent": round(100 * po, 1),
            "kappa": None if kappa is None else round(kappa, 2), "second_screened": second_total}


def list_disagreements(conn, project_id: int) -> list[dict]:
    return [_record_from_row(r) for r in conn.execute(
        "SELECT * FROM records WHERE project_id = ? AND ta_decision != '' AND second_decision != '' "
        "AND ta_decision != second_decision ORDER BY id",
        (project_id,),
    )]


def fulltext_queue(conn, project_id: int, status: str = "all") -> list[dict]:
    """Records going forward to full text: included or maybe at title and abstract."""
    sql = "SELECT * FROM records WHERE project_id = ? AND ta_decision IN ('include', 'maybe')"
    if status == "undecided":
        sql += " AND ft_decision = ''"
    elif status in DECISIONS:
        sql += f" AND ft_decision = '{status}'"
    elif status == "no_pdf":
        sql += " AND pdf_path = ''"
    return [_record_from_row(r) for r in conn.execute(sql + " ORDER BY id", (project_id,))]


def set_ft_decision(conn, record_id: int, decision: str, reason: str = "") -> None:
    if decision not in DECISIONS and decision != "":
        raise ValueError(f"Unknown decision: {decision}")
    stamp = now()
    conn.execute("UPDATE records SET ft_decision = ?, ft_reason = ?, ft_at = ? WHERE id = ?",
                 (decision, reason.strip(), stamp if decision else "", record_id))
    conn.execute(
        "INSERT INTO decision_log (record_id, stage, decision, reason, decided_by, decided_at) "
        "VALUES (?, 'full_text', ?, ?, 'researcher', ?)",
        (record_id, decision or "cleared", reason.strip(), stamp),
    )
    conn.commit()


def set_pdf(conn, record_id: int, pdf_path: str, oa_url: str = "") -> None:
    conn.execute("UPDATE records SET pdf_path = ?, oa_url = COALESCE(NULLIF(?, ''), oa_url) WHERE id = ?",
                 (pdf_path, oa_url, record_id))
    conn.commit()


def set_oa_url(conn, record_id: int, url: str) -> None:
    conn.execute("UPDATE records SET oa_url = ? WHERE id = ?", (url, record_id))
    conn.commit()


def included_in_review(conn, project_id: int) -> list[dict]:
    return [_record_from_row(r) for r in conn.execute(
        "SELECT * FROM records WHERE project_id = ? AND ft_decision = 'include' ORDER BY year, id", (project_id,)
    )]


def set_chart(conn, record_id: int, chart: dict, status: str, model: str = "") -> None:
    conn.execute("UPDATE records SET chart = ?, chart_status = ?, chart_model = COALESCE(NULLIF(?, ''), chart_model), "
                 "chart_at = ? WHERE id = ?", (json.dumps(chart), status, model, now(), record_id))
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
            SUM(ta_decision = '') AS undecided,
            SUM(ta_decision IN ('include', 'maybe')) AS sought,
            SUM(ta_decision IN ('include', 'maybe') AND pdf_path = '') AS no_pdf,
            SUM(ta_decision IN ('include', 'maybe') AND ft_decision != '') AS ft_assessed,
            SUM(ta_decision IN ('include', 'maybe') AND ft_decision = 'exclude') AS ft_excluded,
            SUM(ta_decision IN ('include', 'maybe') AND ft_decision = 'include') AS ft_included,
            SUM(ta_decision IN ('include', 'maybe') AND ft_decision IN ('', 'maybe')) AS ft_pending
        FROM records WHERE project_id = ?
        """,
        (project_id,),
    ).fetchone()
    s = conn.execute(
        "SELECT COALESCE(SUM(retrieved), 0) AS retrieved, COALESCE(SUM(duplicates), 0) AS duplicates "
        "FROM searches WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    by_source = {r["source"]: r["n"] for r in conn.execute(
        "SELECT source, SUM(retrieved) AS n FROM searches WHERE project_id = ? GROUP BY source", (project_id,)
    )}
    ft_reasons = {r["reason"] or "No reason given": r["n"] for r in conn.execute(
        "SELECT ft_reason AS reason, COUNT(*) AS n FROM records WHERE project_id = ? AND ft_decision = 'exclude' "
        "GROUP BY ft_reason ORDER BY n DESC", (project_id,)
    )}
    get = lambda k: row[k] or 0  # noqa: E731
    return {
        "records_identified": s["retrieved"],
        "by_source": by_source,
        "duplicates_removed": s["duplicates"],
        "records_screened": get("total"),
        "included": get("include"),
        "excluded": get("exclude"),
        "maybe": get("maybe"),
        "undecided": get("undecided"),
        "ft_sought": get("sought"),
        "ft_not_retrieved": get("no_pdf"),
        "ft_assessed": get("ft_assessed"),
        "ft_excluded": get("ft_excluded"),
        "ft_excluded_reasons": ft_reasons,
        "ft_included": get("ft_included"),
        "ft_pending": get("ft_pending"),
    }
