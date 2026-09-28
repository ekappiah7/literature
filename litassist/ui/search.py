import pandas as pd
import streamlit as st

from litassist import db, service
from litassist.pubmed import PubMedError
from litassist.sources import EPMC_OBJ1, OPENALEX_OBJ1, SourceError
from litassist.ui.common import authors_short, flash, show_flash

ERRORS = (PubMedError, SourceError)

HELP = {
    "PubMed": "PubMed syntax: MeSH terms with [Mesh], title and abstract words with [tiab].",
    "Europe PMC": "Europe PMC syntax: quoted phrases, AND, OR, NOT. Titles, abstracts and keywords are searched. "
                  "Adds preprints and some journals PubMed does not index.",
    "OpenAlex": "OpenAlex takes plain words and AND, OR, NOT. It covers statistics journals and African outlets "
                "that PubMed misses. Keep the search short.",
}


def _default_query(conn, project: dict, source: str) -> str:
    if source == "PubMed":
        return project["strategy"]
    for s in reversed(db.list_searches(conn, project["id"])):
        if s["source"] == source:
            return s["query"]
    if "Africa South of the Sahara" in (project["strategy"] or ""):
        return EPMC_OBJ1 if source == "Europe PMC" else OPENALEX_OBJ1
    return ""


def _result_message(r: dict) -> str:
    return (f"{r['source']}: found {r['hits']} records, retrieved {r['retrieved']}. "
            f"{r['new']} new, {r['duplicates']} already in this project.")


def render(conn, project: dict, settings: dict) -> None:
    pid = project["id"]
    show_flash("search")
    mode = st.radio("Add records from", ["PubMed", "Europe PMC", "OpenAlex", "A file (RIS, PubMed, CSV)",
                                         "Citation chasing"], horizontal=True)

    if mode in service.SOURCES:
        st.caption(HELP[mode] + " Every run is saved to the search log with its date and counts.")
        strategy = st.text_area("Search string", _default_query(conn, project, mode), height=200,
                                key=f"strategy_{pid}_{mode}")
        col1, col2, col3 = st.columns([1, 1, 2])
        mindate = col1.text_input("From year (optional)", "", key=f"min_{mode}")
        maxdate = col2.text_input("To year (optional)", "", key=f"max_{mode}")
        limit = col3.number_input("Maximum records to retrieve", 1, 20000, 5000, step=500, key=f"lim_{mode}")
        b1, b2 = st.columns([1, 3])
        if b1.button("Check hit count", key=f"count_{mode}"):
            try:
                n = service.count(mode, settings, strategy, mindate, maxdate)
                st.info(f"{mode} would return {n} records.")
            except ERRORS as exc:
                st.error(str(exc))
        if b2.button("Run search and add records", type="primary", key=f"run_{mode}"):
            if mode == "PubMed":
                db.update_project(conn, pid, strategy=strategy)
            try:
                bar = st.progress(0.0, "Downloading records")
                r = service.run_search(conn, pid, mode, settings, strategy, mindate, maxdate, int(limit),
                                       lambda d, t: bar.progress(min(d / t, 1.0), f"Downloaded {d} of {t}"))
                flash("search", _result_message(r))
                st.rerun()
            except ERRORS as exc:
                st.error(str(exc))

    elif mode.startswith("A file"):
        st.caption("Export records from African Journals Online, Google Scholar (via Publish or Perish), Scopus, "
                   "Zotero, Mendeley or PubMed, then import the file here. Duplicates are skipped and the import "
                   "is logged.")
        upload = st.file_uploader("Choose a file", type=["ris", "nbib", "txt", "csv", "tsv"])
        if upload and st.button("Import records", type="primary"):
            try:
                r = service.import_file(conn, pid, upload.name, upload.getvalue())
                flash("search", _result_message(r))
                st.rerun()
            except (ValueError, UnicodeDecodeError) as exc:
                st.error(f"Could not read that file: {exc}")

    else:
        st.caption("Find papers that an important record cites (its references) and papers that cite it, "
                   "using OpenAlex. Only records you included at title and abstract are listed.")
        included = db.list_records(conn, pid, "include")
        if not included:
            st.write("Include some records on the Screen tab first.")
        else:
            labels = {f"{authors_short(r, 1)} {r['year']}: {r['title'][:90]}": r for r in included}
            choice = st.selectbox("Record", list(labels))
            direction = st.radio("Look for", ["both", "references", "cited_by"], horizontal=True,
                                 format_func={"both": "References and citing papers", "references": "References only",
                                              "cited_by": "Citing papers only"}.get)
            if st.button("Find papers", type="primary"):
                try:
                    with st.spinner("Asking OpenAlex"):
                        r = service.chase_citations(conn, pid, labels[choice], settings, direction)
                    flash("search", r.get("note") or _result_message(r), "warning" if r.get("note") else "success")
                    st.rerun()
                except ERRORS as exc:
                    st.error(str(exc))

    st.divider()
    st.subheader("Search log")
    log = db.list_searches(conn, pid)
    if log:
        last = max(s["run_at"] for s in log)
        c1, c2 = st.columns([3, 1])
        c1.caption(f"Last search run {last}. Re-run your saved database searches regularly to catch new papers; "
                   "only records not already in the project are added.")
        if c2.button("Re-run saved searches"):
            try:
                bar = st.progress(0.0, "Searching")
                results = service.rerun_all(conn, pid, settings,
                                            lambda d, t: bar.progress(min(d / t, 1.0), f"{d} of {t}"))
                flash("search", " ".join(_result_message(r) for r in results) or "No saved database searches.")
                st.rerun()
            except ERRORS as exc:
                st.error(str(exc))
        df = pd.DataFrame(log)[["run_at", "source", "hits", "retrieved", "new_records", "duplicates", "filters", "query"]]
        df.columns = ["Date run", "Source", "Hits", "Retrieved", "New", "Duplicates", "Limits", "Search string"]
        st.dataframe(df, hide_index=True, width="stretch")
    else:
        st.write("No searches run yet.")
