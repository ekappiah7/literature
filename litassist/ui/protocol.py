import streamlit as st

from litassist import db
from litassist.ui.common import show_flash, flash

REVIEW_TYPES = ["Scoping review", "Systematic review", "Narrative review", "Rapid evidence brief"]


def render(conn, project: dict) -> None:
    pid = project["id"]
    st.subheader(project["name"])
    show_flash("protocol")
    with st.form("protocol"):
        question = st.text_area("Review question", project["question"], height=80)
        review_type = st.selectbox("Review type", REVIEW_TYPES, index=REVIEW_TYPES.index(project["review_type"])
                                   if project["review_type"] in REVIEW_TYPES else 0)
        st.markdown("**PCC framework**")
        col1, col2, col3 = st.columns(3)
        population = col1.text_area("Population", project["population"], height=120)
        concept = col2.text_area("Concept", project["concept"], height=120)
        context = col3.text_area("Context", project["context"], height=120)
        col4, col5 = st.columns(2)
        inclusion = col4.text_area("Inclusion criteria", project["inclusion"], height=140)
        exclusion = col5.text_area("Exclusion criteria", project["exclusion"], height=140)
        st.markdown("**Exclusion reasons offered during screening** (one per line)")
        col6, col7 = st.columns(2)
        ta_reasons = col6.text_area("Title and abstract stage", "\n".join(db.reasons(project, "title_abstract")),
                                    height=180)
        ft_reasons = col7.text_area("Full text stage", "\n".join(db.reasons(project, "full_text")), height=180)
        new_name = st.text_input("Project name", project["name"])
        if st.form_submit_button("Save protocol", type="primary"):
            db.update_project(conn, pid, name=new_name.strip() or project["name"], question=question,
                              review_type=review_type, population=population, concept=concept,
                              context=context, inclusion=inclusion, exclusion=exclusion,
                              exclusion_reasons=ta_reasons, ft_reasons=ft_reasons)
            flash("protocol", "Saved.")
            st.rerun()
    st.caption("The AI suggestions use this protocol, so clear, specific criteria give better suggestions.")

    with st.expander("Delete this project"):
        st.warning("This permanently removes the project, its records, decisions and search log.")
        if st.checkbox(f"I understand, delete {project['name']}"):
            if st.button("Delete project"):
                db.delete_project(conn, pid)
                st.session_state.pop("project_id", None)
                st.rerun()
