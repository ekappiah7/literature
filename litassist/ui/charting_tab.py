import streamlit as st

from litassist import charting, db, fulltext
from litassist.ai import AI, AIError
from litassist.ui.common import authors_short, flash, show_flash

STATUS = {"": "Not started", "ai draft": "AI draft, needs checking", "checked": "Checked"}


def _source_text(rec: dict) -> tuple[str, str]:
    text = fulltext.read_text(rec["pdf_path"])
    if len(text) > 1500:
        return text, "full text"
    return f"Title: {rec['title']}\n\nAbstract: {rec['abstract']}", "abstract only"


def _fill(conn, ai: AI, project: dict, rec: dict) -> str:
    text, kind = _source_text(rec)
    chart, model = charting.extract(ai, project, rec, text)
    db.set_chart(conn, rec["id"], chart, "ai draft", f"{model} from {kind}")
    return kind


def render(conn, project: dict, settings: dict) -> None:
    pid = project["id"]
    show_flash("charting")
    fields = charting.fields_for(project)

    with st.expander("Charting form fields", expanded=not project.get("chart_fields")):
        st.caption("One field per line, written as 'Field name: what to record'. The AI and the Excel export follow "
                   "this list.")
        text = st.text_area("Fields", project.get("chart_fields") or charting.GENERIC_FIELDS, height=300)
        c1, c2 = st.columns(2)
        if c1.button("Save fields"):
            db.update_project(conn, pid, chart_fields=text)
            flash("charting", "Charting form saved.")
            st.rerun()
        if c2.button("Load the PhD Objective 1 form"):
            db.update_project(conn, pid, chart_fields=charting.OBJECTIVE_1_FIELDS)
            flash("charting", "Objective 1 charting form loaded.")
            st.rerun()

    records = db.included_in_review(conn, pid)
    if not records:
        st.write("Records you include at the full text stage are charted here.")
        return

    counts = {s: sum(1 for r in records if r["chart_status"] == s) for s in STATUS}
    st.write(f"{len(records)} sources included: {counts['checked']} checked, {counts['ai draft']} AI drafts to check, "
             f"{counts['']} not started.")
    todo = [r for r in records if not r["chart_status"]]
    if todo and st.button(f"AI draft for all {len(todo)} not started"):
        try:
            ai = AI(settings)
            bar = st.progress(0.0, "Charting")
            errors = []
            for i, rec in enumerate(todo, 1):
                try:
                    _fill(conn, ai, project, rec)
                except AIError as exc:
                    errors.append(str(exc))
                bar.progress(i / len(todo), f"{i} of {len(todo)}")
            flash("charting", f"AI drafts made for {len(todo) - len(errors)} sources."
                  + (f" {len(errors)} failed: {errors[0]}" if errors else ""), "warning" if errors else "success")
            st.rerun()
        except AIError as exc:
            st.error(str(exc))

    labels = {f"[{STATUS[r['chart_status']]}] {authors_short(r, 1)} {r['year']}: {r['title'][:80]}": r for r in records}
    rec = labels[st.selectbox("Source", list(labels))]
    st.markdown(f"### {rec['title']}")
    has_text = len(fulltext.read_text(rec["pdf_path"], 2000)) > 1500
    st.caption(("Full text available." if has_text else "No readable full text; the AI will use the abstract only.")
               + (f" Last AI draft: {rec['chart_model']}." if rec["chart_model"] else ""))
    if st.button("AI draft from the text" if not rec["chart_status"] else "Redo AI draft (replaces current values)"):
        try:
            with st.spinner("Reading and charting"):
                kind = _fill(conn, AI(settings), project, rec)
            flash("charting", f"AI draft made from the {kind}. Check every value against its quote.")
            st.rerun()
        except AIError as exc:
            st.error(str(exc))

    chart = rec["chart"] or {}
    with st.form(f"chart_{rec['id']}"):
        values = {}
        for f in fields:
            item = chart.get(f["name"], {})
            values[f["name"]] = st.text_area(f["name"], item.get("value", ""), help=f["hint"], height=68,
                                             key=f"cf_{rec['id']}_{f['name']}")
            if item.get("quote"):
                mark = "Quote found in the text" if item.get("verified") else "Quote NOT found in the text, check this value"
                st.caption(f"{mark}: \"{item['quote'][:400]}\"")
        if st.form_submit_button("Save as checked", type="primary"):
            new_chart = {}
            for f in fields:
                old = chart.get(f["name"], {})
                new_chart[f["name"]] = {"value": values[f["name"]].strip(), "quote": old.get("quote", ""),
                                        "verified": old.get("verified", False),
                                        "edited": values[f["name"]].strip() != old.get("value", "")}
            db.set_chart(conn, rec["id"], new_chart, "checked")
            flash("charting", "Saved.")
            st.rerun()
