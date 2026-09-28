"""Small helpers shared by the tabs."""

import re

import streamlit as st


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")[:40] or "project"


def flash(key: str, message: str, kind: str = "success") -> None:
    """Show a message after the next page refresh."""
    st.session_state[f"flash_{key}"] = (kind, message)


def show_flash(key: str) -> None:
    item = st.session_state.pop(f"flash_{key}", None)
    if item:
        getattr(st, item[0])(item[1])


def authors_short(rec: dict, n: int = 6) -> str:
    names = [a["last"] for a in rec["authors"][:n]]
    return ", ".join(names) + (" et al." if len(rec["authors"]) > n else "")


def record_header(rec: dict) -> None:
    st.markdown(f"### {rec['title']}")
    links = []
    if rec["pmid"]:
        links.append(f"[PubMed](https://pubmed.ncbi.nlm.nih.gov/{rec['pmid']}/)")
    if rec["doi"]:
        links.append(f"[DOI](https://doi.org/{rec['doi']})")
    if rec.get("pmcid"):
        links.append(f"[Free full text](https://europepmc.org/article/PMC/{rec['pmcid'].replace('PMC', '')})")
    meta = " · ".join(x for x in (authors_short(rec), f"{rec['journal']} {rec['year']}".strip(), " · ".join(links)) if x)
    st.caption(meta)
    extra = []
    if rec["pub_types"]:
        extra.append("Type: " + ", ".join(rec["pub_types"]))
    extra.append(f"Source: {rec['source']}")
    st.caption(" · ".join(extra))


AI_COLOURS = {"include": "green", "maybe": "orange", "exclude": "red"}


def ai_box(rec: dict) -> None:
    if not rec.get("ai_decision"):
        return
    colour = AI_COLOURS.get(rec["ai_decision"], "gray")
    st.markdown(
        f"**AI suggests: :{colour}[{rec['ai_decision'].upper()}]** "
        f"({rec['ai_confidence']} confidence) · {rec['ai_reason']}  \n"
        f"<small>Criterion: {rec['ai_criterion']} · {rec['ai_model']}</small>",
        unsafe_allow_html=True,
    )
