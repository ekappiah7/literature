"""Exports: RIS and BibTeX for Zotero or Mendeley, and Excel for analysis."""

import io
import re
import unicodedata

import pandas as pd


def _author_name(a: dict) -> str:
    return f"{a['last']}, {a['first'] or a['initials']}".rstrip(", ")


def _pages(pages: str) -> tuple[str, str]:
    if "-" in pages:
        start, end = pages.split("-", 1)
        return start.strip(), end.strip()
    return pages.strip(), ""


def to_ris(records: list[dict]) -> str:
    lines = []
    for r in records:
        lines.append("TY  - JOUR")
        for a in r["authors"]:
            lines.append(f"AU  - {_author_name(a)}")
        lines.append(f"TI  - {r['title']}")
        if r["journal"]:
            lines.append(f"T2  - {r['journal']}")
        if r["journal_abbrev"]:
            lines.append(f"J2  - {r['journal_abbrev']}")
        if r["year"]:
            lines.append(f"PY  - {r['year']}")
        for tag, key in (("VL", "volume"), ("IS", "issue")):
            if r[key]:
                lines.append(f"{tag}  - {r[key]}")
        start, end = _pages(r["pages"])
        if start:
            lines.append(f"SP  - {start}")
        if end:
            lines.append(f"EP  - {end}")
        if r["abstract"]:
            lines.append(f"AB  - {r['abstract'].replace(chr(10), ' ')}")
        if r["doi"]:
            lines.append(f"DO  - {r['doi']}")
        if r["pmid"]:
            lines.append(f"AN  - PMID:{r['pmid']}")
            lines.append(f"UR  - https://pubmed.ncbi.nlm.nih.gov/{r['pmid']}/")
        if r["language"]:
            lines.append(f"LA  - {r['language']}")
        for kw in r["mesh"] + r["keywords"]:
            lines.append(f"KW  - {kw}")
        if r.get("ta_decision"):
            lines.append(f"N1  - Screening: {r['ta_decision']}" + (f" ({r['ta_reason']})" if r.get("ta_reason") else ""))
        lines.append("ER  - ")
        lines.append("")
    return "\r\n".join(lines)


def _bib_escape(text: str) -> str:
    return re.sub(r"([&%$#_{}])", r"\\\1", text or "")


def _bib_key(r: dict, used: set) -> str:
    last = r["authors"][0]["last"] if r["authors"] else "anon"
    last = unicodedata.normalize("NFKD", last).encode("ascii", "ignore").decode()
    word = next((w for w in re.findall(r"[A-Za-z]+", r["title"]) if len(w) > 3), "paper")
    base = f"{re.sub(r'[^A-Za-z]', '', last).lower()}{r['year']}{word.lower()}"
    key, n = base, 1
    while key in used:
        n += 1
        key = f"{base}{chr(96 + n)}"
    used.add(key)
    return key


def to_bibtex(records: list[dict]) -> str:
    used: set = set()
    entries = []
    for r in records:
        fields = {
            "author": " and ".join(_author_name(a) for a in r["authors"]),
            "title": r["title"],
            "journal": r["journal"],
            "year": r["year"],
            "volume": r["volume"],
            "number": r["issue"],
            "pages": r["pages"].replace("-", "--"),
            "doi": r["doi"],
            "pmid": r["pmid"],
            "abstract": r["abstract"].replace("\n", " "),
            "keywords": ", ".join(r["mesh"] + r["keywords"]),
        }
        body = ",\n".join(f"  {k} = {{{_bib_escape(v)}}}" for k, v in fields.items() if v)
        entries.append(f"@article{{{_bib_key(r, used)},\n{body}\n}}")
    return "\n\n".join(entries) + "\n"


def records_frame(records: list[dict]) -> pd.DataFrame:
    rows = []
    for r in records:
        rows.append({
            "ID": r["id"],
            "PMID": r["pmid"],
            "DOI": r["doi"],
            "First author": r["authors"][0]["last"] if r["authors"] else "",
            "Authors": "; ".join(_author_name(a) for a in r["authors"]),
            "Year": r["year"],
            "Title": r["title"],
            "Journal": r["journal"],
            "Volume": r["volume"],
            "Issue": r["issue"],
            "Pages": r["pages"],
            "Publication types": "; ".join(r["pub_types"]),
            "Decision": r["ta_decision"],
            "Reason": r["ta_reason"],
            "Decided at": r["ta_decided_at"],
            "AI suggestion": r.get("ai_decision", ""),
            "AI reason": r.get("ai_reason", ""),
            "AI criterion": r.get("ai_criterion", ""),
            "AI confidence": r.get("ai_confidence", ""),
            "AI model": r.get("ai_model", ""),
            "Second screener": r.get("second_decision", ""),
            "Full text decision": r.get("ft_decision", ""),
            "Full text reason": r.get("ft_reason", ""),
            "Full text file": "yes" if r.get("pdf_path") else "",
            "Source": r["source"],
            "Abstract": r["abstract"],
            "MeSH": "; ".join(r["mesh"]),
        })
    return pd.DataFrame(rows)


def charting_frame(records: list[dict], fields: list[str]) -> pd.DataFrame:
    rows = []
    for r in records:
        row = {"ID": r["id"], "Study": f"{r['authors'][0]['last'] if r['authors'] else ''} {r['year']}".strip(),
               "Title": r["title"], "DOI": r["doi"], "PMID": r["pmid"], "Charting status": r.get("chart_status", "")}
        chart = r.get("chart") or {}
        for f in fields:
            item = chart.get(f, {})
            row[f] = item.get("value", "") if isinstance(item, dict) else str(item)
        rows.append(row)
    return pd.DataFrame(rows)


def to_excel(project: dict, records: list[dict], searches: list[dict], counts: dict,
             charted: list[dict] | None = None, chart_fields: list[str] | None = None) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        records_frame(records).to_excel(xl, sheet_name="Records", index=False)
        if charted:
            charting_frame(charted, chart_fields or []).to_excel(xl, sheet_name="Charting", index=False)
        log = pd.DataFrame(searches)
        if not log.empty:
            log = log[["run_at", "source", "query", "filters", "hits", "retrieved", "new_records", "duplicates", "note"]]
            log.columns = ["Date run", "Database", "Search string", "Limits", "Hits", "Retrieved", "New", "Duplicates", "Note"]
        log.to_excel(xl, sheet_name="Search log", index=False)
        flow = pd.DataFrame(
            [
                ("Records identified from databases", counts["records_identified"]),
                ("Duplicate records removed", counts["duplicates_removed"]),
                ("Records screened (title and abstract)", counts["records_screened"]),
                ("Records excluded", counts["excluded"]),
                ("Records marked maybe", counts["maybe"]),
                ("Records not yet screened", counts["undecided"]),
                ("Full texts sought", counts.get("ft_sought", "")),
                ("Full texts not retrieved", counts.get("ft_not_retrieved", "")),
                ("Full texts assessed", counts.get("ft_assessed", "")),
                ("Full texts excluded", counts.get("ft_excluded", "")),
                ("Sources included in the review", counts.get("ft_included", "")),
            ],
            columns=["PRISMA-ScR stage", "Count"],
        )
        flow.to_excel(xl, sheet_name="PRISMA counts", index=False)
        pd.DataFrame(
            [(k.replace("_", " ").capitalize(), project.get(k, "")) for k in
             ("name", "question", "review_type", "population", "concept", "context", "inclusion", "exclusion", "strategy")],
            columns=["Field", "Value"],
        ).to_excel(xl, sheet_name="Protocol", index=False)
        if counts.get("ft_excluded_reasons"):
            pd.DataFrame(list(counts["ft_excluded_reasons"].items()), columns=["Full text exclusion reason", "Count"]) \
                .to_excel(xl, sheet_name="Full text exclusions", index=False)
        for ws in xl.book.worksheets:
            for col in ws.columns:
                width = max(len(str(c.value or "")) for c in col[:50])
                ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 60)
    return buf.getvalue()
