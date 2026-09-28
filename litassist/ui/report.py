import json
from datetime import date

import pandas as pd
import streamlit as st

from litassist import db, reporting
from litassist.ai import AI, AIError
from litassist.ui.common import slug


@st.cache_data(max_entries=20)
def _diagram(counts_json: str) -> bytes:
    return reporting.prisma_png(json.loads(counts_json))


def render(conn, project: dict, settings: dict) -> None:
    pid = project["id"]
    c = db.counts(conn, pid)
    searches = db.list_searches(conn, pid)
    stem = f"{slug(project['name'])}_{date.today():%Y%m%d}"

    st.subheader("PRISMA-ScR flow diagram")
    png = _diagram(json.dumps(c, sort_keys=True))
    col1, col2 = st.columns([2, 1])
    col1.image(png, width="stretch")
    col2.download_button("Download diagram (PNG)", png, f"{stem}_PRISMA.png", "image/png")
    col2.caption("Numbers update as you screen. Insert the PNG into Word with Insert, Pictures.")

    st.subheader("Search methods")
    st.caption("Written from your search log, so it describes exactly what was done. Edit it into your own words.")
    methods = reporting.methods_text(searches, c)
    st.text_area("Methods paragraph", methods, height=160)
    table = reporting.search_strings_table(searches)
    if table:
        st.dataframe(pd.DataFrame(table, columns=["Database", "Date", "Limits", "Hits", "Search string"]),
                     hide_index=True, width="stretch")

    st.subheader("First draft of the synthesis")
    included = db.included_in_review(conn, pid)
    charted = [r for r in included if r["chart_status"] == "checked"]
    st.caption(f"{len(included)} sources are included in the review; {len(charted)} have checked charting data. "
               "The AI writes only from the charted data and may cite only included sources. Every citation is "
               "checked and the reference list is built from your records, not by the AI.")
    use = st.radio("Write from", ["Checked charting only", "All included sources"], horizontal=True)
    focus = st.text_input("Focus (optional)", placeholder="For example: how denominators and repeated cycles were handled")
    pool = charted if use.startswith("Checked") else included
    if st.button("Write first draft", type="primary", disabled=not pool):
        try:
            with st.spinner("Writing the draft. This can take a minute."):
                sections, report, model = reporting.draft(AI(settings), project, pool, focus)
            cited = [r for r in pool if r["id"] in report["cited"]]
            st.session_state[f"draft_{pid}"] = (reporting.draft_docx(project, sections, cited, methods, report, model),
                                                sections, report)
        except AIError as exc:
            st.error(str(exc))
    saved = st.session_state.get(f"draft_{pid}")
    if saved:
        docx_bytes, sections, report = saved
        st.success(f"Draft ready. It cites {len(report['cited'])} of {len(pool)} sources."
                   + (f" {len(report['invalid_markers'])} invalid citation(s) were removed."
                      if report["invalid_markers"] else " Every citation matched an included source."))
        if report["not_cited"]:
            st.caption(f"{len(report['not_cited'])} included source(s) were not cited; check whether they belong.")
        st.download_button("Download draft (Word)", docx_bytes, f"{stem}_draft.docx",
                           "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        with st.expander("Preview"):
            for sec in sections:
                st.markdown(f"**{sec['heading']}**")
                for para in sec["paragraphs"]:
                    st.write(para)
