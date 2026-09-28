import streamlit as st

from litassist import db
from litassist.export import records_frame


def render(conn, project: dict) -> None:
    pid = project["id"]
    st.subheader("All records")
    records = db.list_records(conn, pid)
    if not records:
        st.write("No records yet. Run a search first.")
        return
    c = db.counts(conn, pid)
    m = st.columns(6)
    m[0].metric("Records", c["records_screened"])
    m[1].metric("Included", c["included"])
    m[2].metric("Maybe", c["maybe"])
    m[3].metric("Excluded", c["excluded"])
    m[4].metric("Not screened", c["undecided"])
    m[5].metric("In the review", c["ft_included"])
    col1, col2 = st.columns([3, 1])
    search = col1.text_input("Filter by word in title or abstract")
    source = col2.selectbox("Source", ["All"] + sorted({r["source"] for r in records}))
    df = records_frame(records)
    if search:
        df = df[df["Title"].str.contains(search, case=False) | df["Abstract"].str.contains(search, case=False)]
    if source != "All":
        df = df[df["Source"] == source]
    st.caption(f"{len(df)} records shown")
    st.dataframe(df[["PMID", "First author", "Year", "Title", "Journal", "Source", "Decision", "Reason",
                     "AI suggestion", "Full text decision"]],
                 hide_index=True, width="stretch", height=520)
