"""LitAssist: literature search and screening assistant.

Run with:  streamlit run app.py
"""

import re
from datetime import date

import pandas as pd
import streamlit as st

from litassist import config, db
from litassist.export import records_frame, to_bibtex, to_excel, to_ris
from litassist.pubmed import PubMed, PubMedError
from litassist.templates import TEMPLATES
from litassist.zotero import Zotero, ZoteroError

st.set_page_config(page_title="LitAssist", page_icon="📚", layout="wide")


@st.cache_resource
def get_conn():
    return db.connect(config.db_path())


conn = get_conn()
settings = config.load_settings()


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")[:40] or "project"


def pubmed_client() -> PubMed:
    return PubMed(email=settings["ncbi_email"], api_key=settings["ncbi_api_key"])


# Sidebar: project picker

with st.sidebar:
    st.title("LitAssist")
    projects = db.list_projects(conn)
    names = [p["name"] for p in projects]
    if "project_id" not in st.session_state and projects:
        st.session_state.project_id = projects[0]["id"]
    current = next((p for p in projects if p["id"] == st.session_state.get("project_id")), None)
    if projects:
        choice = st.selectbox("Project", names, index=names.index(current["name"]) if current else 0)
        current = projects[names.index(choice)]
        st.session_state.project_id = current["id"]

    with st.expander("New project", expanded=not projects):
        with st.form("new_project", clear_on_submit=True):
            new_name = st.text_input("Project name")
            template = st.selectbox("Start from", ["Blank project"] + list(TEMPLATES))
            if st.form_submit_button("Create project") and new_name.strip():
                if new_name.strip() in names:
                    st.error("A project with that name already exists.")
                else:
                    fields = TEMPLATES.get(template, {})
                    st.session_state.project_id = db.create_project(conn, new_name, **fields)
                    st.rerun()

    if current:
        c = db.counts(conn, current["id"])
        st.caption("Progress")
        st.write(f"{c['records_screened']} records, {c['undecided']} to screen")
        st.progress(0 if not c["records_screened"] else 1 - c["undecided"] / c["records_screened"])

# Settings (available even before the first project exists)


def render_settings():
    st.subheader("Settings")
    st.caption(f"Your data and settings are stored in {config.data_dir()}. They never leave this computer "
               "except when searching PubMed or sending to Zotero.")
    with st.form("settings"):
        st.markdown("**PubMed (NCBI)**")
        email = st.text_input("Your email (NCBI asks for this)", settings["ncbi_email"])
        ncbi_key = st.text_input("NCBI API key (optional, makes searches faster)", settings["ncbi_api_key"],
                                 type="password")
        st.markdown("**Zotero**")
        zid = st.text_input("Zotero user ID (a number)", settings["zotero_user_id"])
        zkey = st.text_input("Zotero API key", settings["zotero_api_key"], type="password")
        st.markdown("**Anthropic (for AI screening, coming in the next update)**")
        akey = st.text_input("Anthropic API key", settings["anthropic_api_key"], type="password")
        if st.form_submit_button("Save settings", type="primary"):
            config.save_settings({"ncbi_email": email, "ncbi_api_key": ncbi_key, "zotero_user_id": zid,
                                  "zotero_api_key": zkey, "anthropic_api_key": akey})
            st.session_state.settings_message = "Settings saved."
            st.rerun()

    if st.session_state.get("settings_message"):
        st.success(st.session_state.pop("settings_message"))

    t1, t2 = st.columns(2)
    if t1.button("Test PubMed"):
        try:
            st.success(pubmed_client().check())
        except PubMedError as exc:
            st.error(str(exc))
    if t2.button("Test Zotero"):
        try:
            st.success(Zotero(settings["zotero_user_id"], settings["zotero_api_key"]).check())
        except (ZoteroError, Exception) as exc:
            st.error(str(exc))

    with st.expander("Where do I get these?"):
        st.write("NCBI API key: sign in at ncbi.nlm.nih.gov, open Account settings, and create an API key.")
        st.write("Zotero: sign in at zotero.org/settings/keys. Your user ID is shown at the top of that page. "
                 "Click 'Create new private key', tick 'Allow library access' and 'Allow write access', then save.")
        st.write("Anthropic: create a key at platform.claude.com/settings/keys. Paste it here only, never into a chat.")


if not current:
    tab_start, tab_settings = st.tabs(["Getting started", "Settings"])
    with tab_start:
        st.header("Welcome to LitAssist")
        st.write("1. Open the Settings tab above, enter your email address, save, and click Test PubMed.")
        st.write("2. Create your first project with New project in the sidebar on the left. Choose the PhD "
                 "Objective 1 template to start with a draft scoping review protocol and PubMed search strategy.")
    with tab_settings:
        render_settings()
    st.stop()

pid = current["id"]
tab_protocol, tab_search, tab_screen, tab_library, tab_export, tab_settings = st.tabs(
    ["Protocol", "Search", "Screen", "Library", "Export", "Settings"]
)


# Protocol

with tab_protocol:
    st.subheader(current["name"])
    with st.form("protocol"):
        question = st.text_area("Review question", current["question"], height=80)
        review_type = st.selectbox(
            "Review type",
            ["Scoping review", "Systematic review", "Narrative review", "Rapid evidence brief"],
            index=["Scoping review", "Systematic review", "Narrative review", "Rapid evidence brief"].index(
                current["review_type"]) if current["review_type"] in
            ["Scoping review", "Systematic review", "Narrative review", "Rapid evidence brief"] else 0,
        )
        st.markdown("**PCC framework**")
        col1, col2, col3 = st.columns(3)
        population = col1.text_area("Population", current["population"], height=120)
        concept = col2.text_area("Concept", current["concept"], height=120)
        context = col3.text_area("Context", current["context"], height=120)
        col4, col5 = st.columns(2)
        inclusion = col4.text_area("Inclusion criteria", current["inclusion"], height=140)
        exclusion = col5.text_area("Exclusion criteria", current["exclusion"], height=140)
        new_name = st.text_input("Project name", current["name"])
        if st.form_submit_button("Save protocol", type="primary"):
            db.update_project(conn, pid, name=new_name.strip() or current["name"], question=question,
                              review_type=review_type, population=population, concept=concept,
                              context=context, inclusion=inclusion, exclusion=exclusion)
            st.success("Saved.")
            st.rerun()

    with st.expander("Delete this project"):
        st.warning("This permanently removes the project, its records, decisions and search log.")
        if st.checkbox(f"I understand, delete {current['name']}"):
            if st.button("Delete project"):
                db.delete_project(conn, pid)
                st.session_state.pop("project_id", None)
                st.rerun()


# Search

with tab_search:
    st.subheader("Search PubMed")
    st.caption("Edit the search string, check the number of hits, then retrieve the records. "
               "Every run is saved to the search log with its date and counts.")
    strategy = st.text_area("Search string", current["strategy"], height=220, key=f"strategy_{pid}")
    col1, col2, col3 = st.columns([1, 1, 2])
    mindate = col1.text_input("From year (optional)", "")
    maxdate = col2.text_input("To year (optional)", "")
    limit = col3.number_input("Maximum records to retrieve", 1, 10000, 2000, step=100)

    b1, b2, b3 = st.columns([1, 1, 3])
    if b1.button("Save search string"):
        db.update_project(conn, pid, strategy=strategy)
        st.success("Saved.")
    if b2.button("Check hit count"):
        try:
            info = pubmed_client().search(strategy, mindate, maxdate)
            st.session_state.preview = info
        except PubMedError as exc:
            st.error(str(exc))
    if b3.button("Run search and add records", type="primary"):
        db.update_project(conn, pid, strategy=strategy)
        try:
            client = pubmed_client()
            info = client.search(strategy, mindate, maxdate)
            limits = ", ".join(x for x in (f"from {mindate}" if mindate else "", f"to {maxdate}" if maxdate else "") if x)
            search_id = db.log_search(conn, pid, "PubMed", strategy, info["count"], filters=limits,
                                      note=f"Retrieved up to {limit}")
            bar = st.progress(0.0, "Downloading records")
            records = client.fetch(info, int(limit), lambda d, t: bar.progress(d / t, f"Downloaded {d} of {t}"))
            new, dup = db.add_records(conn, pid, search_id, records)
            db.finish_search(conn, search_id, len(records), new, dup)
            st.session_state.search_message = (f"PubMed found {info['count']} records. Retrieved {len(records)}: "
                                               f"{new} new, {dup} already in this project.")
            st.session_state.pop("preview", None)
            st.rerun()
        except PubMedError as exc:
            st.error(str(exc))
    if st.session_state.get("search_message"):
        st.success(st.session_state.pop("search_message"))

    preview = st.session_state.get("preview")
    if preview:
        st.info(f"PubMed would return {preview['count']} records.")
        for kind in ("warnings", "errors"):
            if preview.get(kind):
                st.warning(f"PubMed {kind}: {preview[kind]}")
        with st.expander("How PubMed interpreted the search"):
            st.code(preview["translation"] or "(not available)", language=None)

    st.subheader("Search log")
    log = db.list_searches(conn, pid)
    if log:
        df = pd.DataFrame(log)[["run_at", "source", "hits", "retrieved", "new_records", "duplicates", "filters", "query"]]
        df.columns = ["Date run", "Database", "Hits", "Retrieved", "New", "Duplicates", "Limits", "Search string"]
        st.dataframe(df, hide_index=True, width="stretch")
    else:
        st.write("No searches run yet.")


# Screen

REASONS = [
    "", "Not IVF or ICSI", "Not sub-Saharan Africa", "No outcome data", "Review or commentary",
    "Animal or laboratory study", "Duplicate", "Other",
]

with tab_screen:
    st.subheader("Title and abstract screening")
    mode = st.radio("Show", ["Not yet screened", "Maybe", "Included", "Excluded"], horizontal=True)
    decision_filter = {"Not yet screened": "undecided", "Maybe": "maybe", "Included": "include",
                       "Excluded": "exclude"}[mode]
    queue = db.list_records(conn, pid, decision_filter)
    if not queue:
        st.write("Nothing to show here.")
    else:
        key = f"pos_{pid}_{decision_filter}"
        pos = min(st.session_state.get(key, 0), len(queue) - 1)
        rec = queue[pos]
        st.caption(f"Record {pos + 1} of {len(queue)} in this list")
        with st.expander("Inclusion and exclusion criteria"):
            st.write(f"Include: {current['inclusion'] or 'not set'}")
            st.write(f"Exclude: {current['exclusion'] or 'not set'}")
        st.markdown(f"### {rec['title']}")
        authors = ", ".join(a["last"] for a in rec["authors"][:6]) + (" et al." if len(rec["authors"]) > 6 else "")
        links = []
        if rec["pmid"]:
            links.append(f"[PubMed](https://pubmed.ncbi.nlm.nih.gov/{rec['pmid']}/)")
        if rec["doi"]:
            links.append(f"[DOI](https://doi.org/{rec['doi']})")
        st.caption(f"{authors} · {rec['journal']} {rec['year']} · " + " · ".join(links))
        if rec["pub_types"]:
            st.caption("Publication type: " + ", ".join(rec["pub_types"]))
        st.write(rec["abstract"] or "_No abstract available._")
        if rec["ta_decision"]:
            st.info(f"Current decision: {rec['ta_decision']}" + (f" ({rec['ta_reason']})" if rec["ta_reason"] else ""))

        reason = st.selectbox("Reason (needed for exclude)", REASONS, key=f"reason_{rec['id']}")
        note = st.text_input("Note (optional)", key=f"note_{rec['id']}")
        full_reason = "; ".join(x for x in (reason, note) if x)
        c1, c2, c3, c4, c5 = st.columns(5)

        def decide(decision):
            db.set_decision(conn, rec["id"], decision, full_reason)
            if decision_filter != "undecided" and decision != decision_filter:
                st.session_state[key] = pos
            elif decision_filter != "undecided":
                st.session_state[key] = pos + 1

        if c1.button("Include", type="primary", width="stretch"):
            decide("include")
            st.rerun()
        if c2.button("Maybe", width="stretch"):
            decide("maybe")
            st.rerun()
        if c3.button("Exclude", width="stretch"):
            if not reason:
                st.error("Choose a reason for exclusion.")
            else:
                decide("exclude")
                st.rerun()
        if c4.button("Previous", width="stretch", disabled=pos == 0):
            st.session_state[key] = pos - 1
            st.rerun()
        if c5.button("Skip", width="stretch", disabled=pos >= len(queue) - 1):
            st.session_state[key] = pos + 1
            st.rerun()


# Library

with tab_library:
    st.subheader("All records")
    records = db.list_records(conn, pid)
    if records:
        c = db.counts(conn, pid)
        m = st.columns(5)
        m[0].metric("Records", c["records_screened"])
        m[1].metric("Included", c["included"])
        m[2].metric("Maybe", c["maybe"])
        m[3].metric("Excluded", c["excluded"])
        m[4].metric("Not screened", c["undecided"])
        search = st.text_input("Filter by word in title or abstract")
        df = records_frame(records)
        if search:
            mask = df["Title"].str.contains(search, case=False) | df["Abstract"].str.contains(search, case=False)
            df = df[mask]
        st.dataframe(df[["PMID", "First author", "Year", "Title", "Journal", "Decision", "Reason"]],
                     hide_index=True, width="stretch", height=500)
    else:
        st.write("No records yet. Run a search first.")


# Export

with tab_export:
    st.subheader("Export")
    which = st.radio("Records to export", ["Included", "Included and maybe", "All records"], horizontal=True)
    all_recs = db.list_records(conn, pid)
    chosen = {
        "Included": [r for r in all_recs if r["ta_decision"] == "include"],
        "Included and maybe": [r for r in all_recs if r["ta_decision"] in ("include", "maybe")],
        "All records": all_recs,
    }[which]
    st.write(f"{len(chosen)} records selected.")
    stem = f"{slug(current['name'])}_{date.today():%Y%m%d}"
    c1, c2, c3 = st.columns(3)
    c1.download_button("RIS (Zotero or Mendeley)", to_ris(chosen), f"{stem}.ris", "application/x-research-info-systems",
                       disabled=not chosen, width="stretch")
    c2.download_button("BibTeX", to_bibtex(chosen), f"{stem}.bib", "application/x-bibtex",
                       disabled=not chosen, width="stretch")
    c3.download_button(
        "Excel workbook (records, search log, PRISMA counts)",
        to_excel(current, chosen, db.list_searches(conn, pid), db.counts(conn, pid)),
        f"{stem}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )
    st.caption("In Mendeley Reference Manager use File, Import library, RIS. In Zotero use File, Import.")

    st.divider()
    st.subheader("Send to Zotero")
    collection = st.text_input("Zotero collection name", current["zotero_collection"] or current["name"])
    pending = [r for r in chosen if not r["zotero_key"]]
    st.write(f"{len(pending)} of the selected records have not been sent to Zotero yet.")
    if st.button("Send to Zotero", disabled=not pending):
        try:
            z = Zotero(settings["zotero_user_id"], settings["zotero_api_key"])
            coll_key = z.find_or_create_collection(collection)
            bar = st.progress(0.0, "Sending")
            keys = z.add_items(pending, coll_key, lambda d, t: bar.progress(d / t, f"Sent {d} of {t}"))
            for rid, zkey in keys.items():
                db.set_zotero_key(conn, rid, zkey)
            db.update_project(conn, pid, zotero_collection=collection)
            st.success(f"Sent {len(keys)} records to the Zotero collection '{collection}'.")
        except ZoteroError as exc:
            st.error(str(exc))

with tab_settings:
    render_settings()
