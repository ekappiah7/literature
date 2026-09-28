"""Actions that combine storage with outside services. Each one logs what it did."""

import io
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

from litassist import config, db
from litassist.ai import AI, AIError, screen
from litassist.importers import parse_file
from litassist.pubmed import PubMed
from litassist.sources import EuropePMC, OpenAlex

SOURCES = ("PubMed", "Europe PMC", "OpenAlex")


def client(source: str, settings: dict):
    if source == "PubMed":
        return PubMed(email=settings["ncbi_email"], api_key=settings["ncbi_api_key"])
    if source == "Europe PMC":
        return EuropePMC(email=settings["ncbi_email"])
    return OpenAlex(email=settings["ncbi_email"], api_key=settings.get("openalex_api_key", ""))


def count(source: str, settings: dict, query: str, mindate: str = "", maxdate: str = "") -> int:
    c = client(source, settings)
    if source == "PubMed":
        return c.search(query, mindate, maxdate)["count"]
    return c.count(query, mindate, maxdate)


def limits_text(mindate: str, maxdate: str) -> str:
    return ", ".join(x for x in (f"from {mindate}" if mindate else "", f"to {maxdate}" if maxdate else "") if x)


def run_search(conn, project_id: int, source: str, settings: dict, query: str,
               mindate: str = "", maxdate: str = "", limit: int = 5000, progress=None) -> dict:
    c = client(source, settings)
    if source == "PubMed":
        info = c.search(query, mindate, maxdate)
        hits = info["count"]
        search_id = db.log_search(conn, project_id, source, query, hits, limits_text(mindate, maxdate),
                                  note=f"Retrieved up to {limit}")
        records = c.fetch(info, limit, progress)
    else:
        hits, records = c.search(query, limit, mindate, maxdate, progress)
        search_id = db.log_search(conn, project_id, source, query, hits, limits_text(mindate, maxdate),
                                  note=f"Retrieved up to {limit}")
    new, dup = db.add_records(conn, project_id, search_id, records)
    db.finish_search(conn, search_id, len(records), new, dup)
    return {"source": source, "hits": hits, "retrieved": len(records), "new": new, "duplicates": dup}


def rerun_all(conn, project_id: int, settings: dict, progress=None) -> list[dict]:
    """Re-run the latest version of every saved database search; only new records are added."""
    latest = {}
    for s in db.list_searches(conn, project_id):
        if s["source"] in SOURCES:
            latest[s["source"]] = s
    results = []
    for source, s in latest.items():
        mindate, maxdate = "", ""
        for part in s["filters"].split(", "):
            if part.startswith("from "):
                mindate = part[5:]
            elif part.startswith("to "):
                maxdate = part[3:]
        results.append(run_search(conn, project_id, source, settings, s["query"], mindate, maxdate, progress=progress))
    return results


def import_file(conn, project_id: int, filename: str, data: bytes) -> dict:
    records = parse_file(filename, data)
    search_id = db.log_search(conn, project_id, f"Imported: {filename}", f"File import: {filename}",
                              len(records), note="Records imported from a file export")
    new, dup = db.add_records(conn, project_id, search_id, records)
    db.finish_search(conn, search_id, len(records), new, dup)
    return {"source": filename, "hits": len(records), "retrieved": len(records), "new": new, "duplicates": dup}


def chase_citations(conn, project_id: int, record: dict, settings: dict, direction: str = "both") -> dict:
    oa = client("OpenAlex", settings)
    work = oa.work(doi=record["doi"], pmid=record["pmid"], openalex_id=record.get("openalex_id", ""))
    if not work:
        return {"source": "Citation chasing", "hits": 0, "retrieved": 0, "new": 0, "duplicates": 0,
                "note": "This record was not found in OpenAlex."}
    found = []
    if direction in ("both", "references"):
        found += oa.references(work)
    if direction in ("both", "cited_by"):
        found += oa.cited_by(work)
    label = f"Citation chasing: {record['authors'][0]['last'] if record['authors'] else 'record'} {record['year']}"
    search_id = db.log_search(conn, project_id, label, f"OpenAlex {direction} for record {record['id']} "
                              f"({record['doi'] or record['pmid']})", len(found))
    new, dup = db.add_records(conn, project_id, search_id, found)
    db.finish_search(conn, search_id, len(found), new, dup)
    return {"source": label, "hits": len(found), "retrieved": len(found), "new": new, "duplicates": dup}


def ai_screen_batch(conn, project: dict, records: list[dict], settings: dict, progress=None, workers: int = 4) -> dict:
    """Get AI suggestions for records. Stops early if every call is failing."""
    ai = AI(settings)
    done = failed = 0
    errors = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(screen, ai, project, r): r for r in records}
        for fut in as_completed(futures):
            rec = futures[fut]
            try:
                db.set_ai_suggestion(conn, rec["id"], fut.result())
                done += 1
            except AIError as exc:
                failed += 1
                errors.append(str(exc))
                if failed >= 5 and done == 0:
                    for f in futures:
                        f.cancel()
                    break
            if progress:
                progress(done + failed, len(records))
    return {"done": done, "failed": failed, "errors": errors[:3]}


def backup_zip() -> tuple[str, bytes]:
    """Zip the database and full texts. Settings (with API keys) are left out on purpose."""
    root = config.data_dir()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path in root.rglob("*"):
            if path.is_file() and path.name != config.SETTINGS_FILE:
                z.write(path, path.relative_to(root))
    return f"LitAssist_backup_{date.today():%Y%m%d}.zip", buf.getvalue()
