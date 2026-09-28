"""LitAssist: literature search, screening, charting and drafting assistant.

Run with:  streamlit run app.py
"""

import streamlit as st

from litassist import config, db
from litassist.templates import TEMPLATES
from litassist.ui import (charting_tab, export_tab, fulltext_tab, library, protocol, report, screen, search,
                          settings_tab)

st.set_page_config(page_title="LitAssist", page_icon="📚", layout="wide")


@st.cache_resource
def get_conn():
    return db.connect(config.db_path())


conn = get_conn()
settings = config.load_settings()

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
                    st.session_state.project_id = db.create_project(conn, new_name, **TEMPLATES.get(template, {}))
                    st.rerun()

    if current:
        c = db.counts(conn, current["id"])
        st.caption("Progress")
        st.write(f"{c['records_screened']} records, {c['undecided']} to screen")
        st.progress(0 if not c["records_screened"] else 1 - c["undecided"] / c["records_screened"])
        if c["ft_sought"]:
            st.write(f"Full text: {c['ft_assessed']} of {c['ft_sought']} assessed")
            st.write(f"In the review: {c['ft_included']}")

if not current:
    tab_start, tab_settings = st.tabs(["Getting started", "Settings"])
    with tab_start:
        st.header("Welcome to LitAssist")
        st.write("1. Open the Settings tab above, enter your email address, save, and click Test PubMed.")
        st.write("2. Create your first project with New project in the sidebar on the left. Choose the PhD "
                 "Objective 1 template to start with a draft scoping review protocol and PubMed search strategy.")
    with tab_settings:
        settings_tab.render(settings)
    st.stop()

tabs = st.tabs(["Protocol", "Search", "Screen", "Full text", "Charting", "Library", "Report", "Export", "Settings"])
with tabs[0]:
    protocol.render(conn, current)
with tabs[1]:
    search.render(conn, current, settings)
with tabs[2]:
    screen.render(conn, current, settings)
with tabs[3]:
    fulltext_tab.render(conn, current, settings)
with tabs[4]:
    charting_tab.render(conn, current, settings)
with tabs[5]:
    library.render(conn, current)
with tabs[6]:
    report.render(conn, current, settings)
with tabs[7]:
    export_tab.render(conn, current, settings)
with tabs[8]:
    settings_tab.render(settings)
