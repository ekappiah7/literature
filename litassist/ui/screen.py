import streamlit as st

from litassist import db, service
from litassist.ai import AIError
from litassist.ui.common import ai_box, flash, record_header, show_flash

VIEWS = {
    "Not yet screened": ("undecided", None),
    "AI suggests include": ("ai", "include"),
    "AI suggests maybe": ("ai", "maybe"),
    "AI suggests exclude": ("ai", "exclude"),
    "Maybe": ("maybe", None),
    "Included": ("include", None),
    "Excluded": ("exclude", None),
    "Disagreements with second screener": ("disagree", None),
}


def _queue(conn, pid: int, view: str) -> list[dict]:
    kind, ai = VIEWS[view]
    if kind == "ai":
        return db.list_by_ai(conn, pid, ai)
    if kind == "disagree":
        return db.list_disagreements(conn, pid)
    return db.list_records(conn, pid, kind)


def _sample_order(rec: dict) -> int:
    """A fixed pseudo-random order, so the second screener sees a spread of records."""
    return (rec["id"] * 2654435761) % 4294967296


def _ai_panel(conn, project: dict, settings: dict) -> None:
    pid = project["id"]
    agree = db.ai_agreement(conn, pid)
    pending = [r for r in db.list_records(conn, pid, "undecided") if not r["ai_decision"]]
    with st.expander(f"AI suggestions ({len(pending)} unscreened records without one)", expanded=bool(pending)):
        st.caption("The AI reads each title and abstract against your protocol and suggests include, maybe or "
                   "exclude with a reason. You still make every decision. Main model: "
                   f"{'Gemini' if settings['ai_primary'] == 'gemini' else 'Anthropic'}"
                   f"{', with the other as backup' if settings['ai_use_backup'] == 'yes' else ''}.")
        c1, c2 = st.columns(2)
        batch = None
        if c1.button("Suggest for the next 25", disabled=not pending):
            batch = pending[:25]
        if c2.button(f"Suggest for all {len(pending)}", disabled=not pending):
            batch = pending
        if batch:
            try:
                bar = st.progress(0.0, "Asking the AI")
                r = service.ai_screen_batch(conn, project, batch, settings,
                                            lambda d, t: bar.progress(d / t, f"{d} of {t} records"))
                msg = f"AI suggestions added for {r['done']} records."
                if r["failed"]:
                    msg += f" {r['failed']} failed: {' | '.join(r['errors'])}"
                flash("screen", msg, "warning" if r["failed"] else "success")
                st.rerun()
            except AIError as exc:
                st.error(str(exc))
        if agree["compared"]:
            pct = round(100 * agree["agreed"] / agree["compared"])
            st.write(f"On the {agree['compared']} records you have screened that also have an AI suggestion, "
                     f"the AI agreed with you {pct}% of the time.")
            if agree["ai_would_miss"]:
                st.warning(f"The AI suggested exclude for {agree['ai_would_miss']} record(s) you kept. Check the "
                           "criteria wording on the Protocol tab and never rely on AI exclusions alone.")
            else:
                st.success("So far the AI has not suggested excluding anything you kept.")


def render(conn, project: dict, settings: dict) -> None:
    pid = project["id"]
    show_flash("screen")
    who = st.radio("Screening as", ["Me", "Second screener (blind)"], horizontal=True,
                   help="The second screener sees no earlier decisions or AI suggestions. Use it for a colleague "
                        "screening a sample, then compare agreement.")
    reasons = [""] + db.reasons(project, "title_abstract")

    if who == "Me":
        _ai_panel(conn, project, settings)
        view = st.selectbox("Show", list(VIEWS))
        queue = _queue(conn, pid, view)
        second = False
    else:
        stats = db.screener_agreement(conn, pid)
        if stats["compared"]:
            kappa = f", Cohen's kappa {stats['kappa']}" if stats["kappa"] is not None else ""
            st.info(f"Second screener has screened {stats['second_screened']} records. On the {stats['compared']} "
                    f"you have both screened, you agreed on {stats['percent']}%{kappa}. "
                    "Resolve disagreements from 'Me' view, 'Disagreements with second screener'.")
        target = st.number_input("Sample size for the second screener", 10, 5000, 50, step=10)
        done = [r for r in db.list_records(conn, pid) if r["second_decision"]]
        remaining = sorted([r for r in db.list_records(conn, pid) if not r["second_decision"]], key=_sample_order)
        queue = remaining[:max(0, int(target) - len(done))]
        st.caption(f"{len(done)} of {int(target)} screened in this sample.")
        view, second = "second", True

    if not queue:
        st.write("Nothing to show here.")
        return

    key = f"pos_{pid}_{view}"
    pos = min(st.session_state.get(key, 0), len(queue) - 1)
    rec = queue[pos]
    st.caption(f"Record {pos + 1} of {len(queue)} in this list. "
               "Keyboard: I include, M maybe, E exclude, A accept AI, N next, P previous.")
    with st.expander("Inclusion and exclusion criteria"):
        st.write(f"Include: {project['inclusion'] or 'not set'}")
        st.write(f"Exclude: {project['exclusion'] or 'not set'}")
    record_header(rec)
    st.write(rec["abstract"] or "_No abstract available._")
    if not second:
        ai_box(rec)
        if rec["ta_decision"]:
            st.info(f"Your decision: {rec['ta_decision']}" + (f" ({rec['ta_reason']})" if rec["ta_reason"] else "")
                    + (f" · Second screener: {rec['second_decision']}" if rec["second_decision"] else ""))

    reason = st.selectbox("Reason (needed for exclude)", reasons, key=f"reason_{rec['id']}_{second}")
    note = st.text_input("Note (optional)", key=f"note_{rec['id']}_{second}")
    full_reason = "; ".join(x for x in (reason, note) if x)

    def decide(decision: str, why: str) -> None:
        if second:
            db.set_second_decision(conn, rec["id"], decision, why)
        else:
            db.set_decision(conn, rec["id"], decision, why)
            kind = VIEWS[view][0]
            leaves_list = kind in ("undecided", "ai") or decision != kind
            st.session_state[key] = pos if leaves_list else pos + 1

    cols = st.columns(6)
    if cols[0].button("Include", type="primary", width="stretch", shortcut="i"):
        decide("include", full_reason)
        st.rerun()
    if cols[1].button("Maybe", width="stretch", shortcut="m"):
        decide("maybe", full_reason)
        st.rerun()
    if cols[2].button("Exclude", width="stretch", shortcut="e"):
        if not reason:
            st.error("Choose a reason for exclusion.")
        else:
            decide("exclude", full_reason)
            st.rerun()
    can_accept = not second and bool(rec.get("ai_decision"))
    if cols[3].button("Accept AI", width="stretch", shortcut="a", disabled=not can_accept,
                      help="Record the AI's suggestion as your decision, with its reason."):
        decide(rec["ai_decision"], f"Agreed with AI: {rec['ai_reason']}" + (f"; {note}" if note else ""))
        st.rerun()
    if cols[4].button("Previous", width="stretch", shortcut="p", disabled=pos == 0):
        st.session_state[key] = pos - 1
        st.rerun()
    if cols[5].button("Next", width="stretch", shortcut="n", disabled=pos >= len(queue) - 1):
        st.session_state[key] = pos + 1
        st.rerun()
