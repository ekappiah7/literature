from pathlib import Path

import streamlit as st

from litassist import db, fulltext
from litassist.ui.common import flash, record_header, show_flash

VIEWS = {
    "Not yet assessed": "undecided",
    "No full text yet": "no_pdf",
    "Maybe": "maybe",
    "Included": "include",
    "Excluded": "exclude",
    "All": "all",
}


def render(conn, project: dict, settings: dict) -> None:
    pid = project["id"]
    show_flash("fulltext")
    c = db.counts(conn, pid)
    m = st.columns(5)
    m[0].metric("Going to full text", c["ft_sought"])
    m[1].metric("Full text in hand", c["ft_sought"] - c["ft_not_retrieved"])
    m[2].metric("Assessed", c["ft_assessed"])
    m[3].metric("Included in review", c["ft_included"])
    m[4].metric("Excluded", c["ft_excluded"])
    if not c["ft_sought"]:
        st.write("Records you include or mark maybe on the Screen tab come here for full text review.")
        return

    missing = db.fulltext_queue(conn, pid, "no_pdf")
    if missing:
        st.caption("LitAssist can fetch free, legal full texts from Europe PMC and Unpaywall. The rest you can get "
                   "through your university library and upload below.")
        if st.button(f"Find free full texts for {len(missing)} records", type="primary"):
            bar = st.progress(0.0, "Looking for free full texts")
            found = 0
            for i, rec in enumerate(missing, 1):
                path, _ = fulltext.fetch_open_access(rec, settings["ncbi_email"])
                if path:
                    db.set_pdf(conn, rec["id"], path)
                    found += 1
                bar.progress(i / len(missing), f"Checked {i} of {len(missing)}, found {found}")
            flash("fulltext", f"Found free full texts for {found} of {len(missing)} records.")
            st.rerun()

    view = st.selectbox("Show", list(VIEWS))
    queue = db.fulltext_queue(conn, pid, VIEWS[view])
    if not queue:
        st.write("Nothing to show here.")
        return
    key = f"ftpos_{pid}_{view}"
    pos = min(st.session_state.get(key, 0), len(queue) - 1)
    rec = queue[pos]
    st.caption(f"Record {pos + 1} of {len(queue)} in this list")
    record_header(rec)
    st.caption(f"Title and abstract decision: {rec['ta_decision']}" +
               (f" ({rec['ta_reason']})" if rec["ta_reason"] else ""))

    if rec["pdf_path"] and Path(rec["pdf_path"]).exists():
        p = Path(rec["pdf_path"])
        c1, c2 = st.columns([1, 3])
        c1.download_button("Open full text", p.read_bytes(), file_name=f"{rec['id']}{p.suffix}",
                           mime="application/pdf" if p.suffix == ".pdf" else "text/plain")
        text = fulltext.read_text(str(p), 6000)
        with c2.expander("Preview the text LitAssist can read"):
            st.text(text[:6000] or "No readable text. The PDF may be a scanned image; charting will use the abstract.")
    else:
        c1, c2 = st.columns(2)
        if c1.button("Look for a free full text"):
            path, where = fulltext.fetch_open_access(rec, settings["ncbi_email"])
            if path:
                db.set_pdf(conn, rec["id"], path)
                flash("fulltext", f"Saved from {where}.")
                st.rerun()
            else:
                st.warning(where)
        if rec["oa_url"]:
            c2.markdown(f"[Possible free version]({rec['oa_url']})")
    upload = st.file_uploader("Upload the PDF", type=["pdf", "txt"], key=f"up_{rec['id']}")
    if upload:
        try:
            db.set_pdf(conn, rec["id"], fulltext.save_upload(rec, upload.name, upload.getvalue()))
            flash("fulltext", "Full text saved.")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    if rec["ft_decision"]:
        st.info(f"Full text decision: {rec['ft_decision']}" + (f" ({rec['ft_reason']})" if rec["ft_reason"] else ""))
    reason = st.selectbox("Reason (needed for exclude)", [""] + db.reasons(project, "full_text"), key=f"ftr_{rec['id']}")
    note = st.text_input("Note (optional)", key=f"ftn_{rec['id']}")
    full_reason = "; ".join(x for x in (reason, note) if x)

    def decide(decision):
        db.set_ft_decision(conn, rec["id"], decision, full_reason)
        leaves = VIEWS[view] in ("undecided", "no_pdf") or (VIEWS[view] != "all" and decision != VIEWS[view])
        st.session_state[key] = pos if leaves else pos + 1

    cols = st.columns(5)
    if cols[0].button("Include in review", type="primary", width="stretch"):
        decide("include")
        st.rerun()
    if cols[1].button("Maybe", width="stretch", key="ft_maybe"):
        decide("maybe")
        st.rerun()
    if cols[2].button("Exclude", width="stretch", key="ft_exclude"):
        if not reason:
            st.error("Choose a reason for exclusion.")
        else:
            decide("exclude")
            st.rerun()
    if cols[3].button("Previous", width="stretch", key="ft_prev", disabled=pos == 0):
        st.session_state[key] = pos - 1
        st.rerun()
    if cols[4].button("Next", width="stretch", key="ft_next", disabled=pos >= len(queue) - 1):
        st.session_state[key] = pos + 1
        st.rerun()
