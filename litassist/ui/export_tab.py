from datetime import date

import streamlit as st

from litassist import charting, db, service
from litassist.export import to_bibtex, to_excel, to_ris
from litassist.ui.common import slug
from litassist.zotero import Zotero, ZoteroError


def render(conn, project: dict, settings: dict) -> None:
    pid = project["id"]
    st.subheader("Export")
    which = st.radio("Records to export",
                     ["Included in the review", "Included at title and abstract", "Included and maybe", "All records"],
                     horizontal=True)
    all_recs = db.list_records(conn, pid)
    chosen = {
        "Included in the review": [r for r in all_recs if r["ft_decision"] == "include"],
        "Included at title and abstract": [r for r in all_recs if r["ta_decision"] == "include"],
        "Included and maybe": [r for r in all_recs if r["ta_decision"] in ("include", "maybe")],
        "All records": all_recs,
    }[which]
    st.write(f"{len(chosen)} records selected.")
    stem = f"{slug(project['name'])}_{date.today():%Y%m%d}"
    charted = db.included_in_review(conn, pid)
    c1, c2, c3 = st.columns(3)
    c1.download_button("RIS (Zotero or Mendeley)", to_ris(chosen), f"{stem}.ris",
                       "application/x-research-info-systems", disabled=not chosen, width="stretch")
    c2.download_button("BibTeX", to_bibtex(chosen), f"{stem}.bib", "application/x-bibtex",
                       disabled=not chosen, width="stretch")
    if c3.button("Prepare Excel workbook", width="stretch"):
        st.session_state[f"xlsx_{pid}"] = to_excel(project, chosen, db.list_searches(conn, pid), db.counts(conn, pid),
                                                   charted, [f["name"] for f in charting.fields_for(project)])
    if st.session_state.get(f"xlsx_{pid}"):
        c3.download_button("Download Excel workbook", st.session_state[f"xlsx_{pid}"], f"{stem}.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
    st.caption("The workbook has sheets for records, charting, search log, PRISMA-ScR counts and the protocol. "
               "In Mendeley Reference Manager use File, Import library, RIS. In Zotero use File, Import.")

    st.divider()
    st.subheader("Send to Zotero")
    collection = st.text_input("Zotero collection name", project["zotero_collection"] or project["name"])
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

    st.divider()
    st.subheader("Back up your work")
    st.caption("A zip of all projects, decisions and full texts. Your API keys are not included. "
               "Save it to Google Drive or a flash drive.")
    if st.button("Prepare backup"):
        name, data = service.backup_zip()
        st.download_button("Download backup", data, name, "application/zip")
