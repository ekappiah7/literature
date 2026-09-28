"""Import records from files: RIS (Zotero, Mendeley, EndNote, African Journals
Online, Scopus), CSV (Google Scholar via Publish or Perish, Excel sheets) and
PubMed's own .nbib format."""

import csv
import io
import re

RIS_MAP = {
    "TI": "title", "T1": "title", "AB": "abstract", "N2": "abstract",
    "JO": "journal", "JF": "journal", "T2": "journal", "J2": "journal_abbrev", "JA": "journal_abbrev",
    "VL": "volume", "IS": "issue", "DO": "doi", "LA": "language",
}


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _split_name(name: str) -> dict:
    name = name.strip()
    if "," in name:
        last, first = [p.strip() for p in name.split(",", 1)]
    else:
        parts = name.split()
        last, first = (parts[-1], " ".join(parts[:-1])) if len(parts) > 1 else (name, "")
    initials = "".join(p[0] for p in re.split(r"[\s.\-]+", first) if p)
    return {"last": last, "first": first, "initials": initials}


def _blank(source: str) -> dict:
    return {"source": source, "pmid": "", "doi": "", "pmcid": "", "title": "", "abstract": "", "authors": [],
            "journal": "", "journal_abbrev": "", "year": "", "volume": "", "issue": "", "pages": "",
            "language": "", "pub_types": [], "mesh": [], "keywords": []}


def _clean_doi(text: str) -> str:
    m = re.search(r"10\.\d{4,9}/\S+", text or "")
    return m.group(0).rstrip(".,;") if m else ""


def parse_ris(data: bytes, source: str) -> list[dict]:
    records, rec, sp, ep, last_tag = [], None, "", "", None
    for line in _decode(data).splitlines():
        m = re.match(r"^([A-Z][A-Z0-9])  -\s?(.*)$", line)
        if not m:
            if rec is not None and last_tag in ("AB", "N2", "TI", "T1") and line.strip():
                key = RIS_MAP[last_tag]
                rec[key] = f"{rec[key]} {line.strip()}".strip()
            continue
        tag, value = m.group(1), m.group(2).strip()
        last_tag = tag
        if tag == "TY":
            rec, sp, ep = _blank(source), "", ""
            rec["pub_types"] = [value]
        elif rec is None:
            continue
        elif tag == "ER":
            rec["pages"] = f"{sp}-{ep}" if sp and ep else sp
            records.append(rec)
            rec = None
        elif tag in ("AU", "A1", "A2") and value:
            rec["authors"].append(_split_name(value))
        elif tag in ("PY", "Y1", "DA") and not rec["year"]:
            yr = re.search(r"\d{4}", value)
            rec["year"] = yr.group(0) if yr else ""
        elif tag == "SP":
            sp = value
        elif tag == "EP":
            ep = value
        elif tag == "KW":
            rec["keywords"].append(value)
        elif tag in ("AN", "UR", "N1", "M1") and not rec["pmid"]:
            pm = re.search(r"(?:PMID[:\s]*|pubmed\.ncbi\.nlm\.nih\.gov/)(\d{5,9})", value)
            if pm:
                rec["pmid"] = pm.group(1)
            if tag == "UR" and not rec["doi"]:
                rec["doi"] = _clean_doi(value)
        elif tag in RIS_MAP and not rec[RIS_MAP[tag]]:
            rec[RIS_MAP[tag]] = _clean_doi(value) if tag == "DO" else value
    return [r for r in records if r["title"]]


def parse_nbib(data: bytes, source: str = "PubMed file") -> list[dict]:
    """PubMed MEDLINE format (.nbib or .txt from 'Save' on PubMed)."""
    records, rec, tag = [], None, None
    for line in _decode(data).splitlines() + [""]:
        if not line.strip():
            if rec and rec["title"]:
                records.append(rec)
            rec, tag = None, None
            continue
        m = re.match(r"^([A-Z]{2,4})\s*- (.*)$", line)
        if m:
            tag, value = m.group(1), m.group(2).strip()
            if rec is None:
                rec = _blank(source)
        elif rec is not None and tag:
            value = line.strip()
            key = {"TI": "title", "AB": "abstract"}.get(tag)
            if key:
                rec[key] += " " + value
            continue
        else:
            continue
        if tag == "PMID":
            rec["pmid"] = value
        elif tag == "TI":
            rec["title"] = value
        elif tag == "AB":
            rec["abstract"] = value
        elif tag == "FAU":
            rec["authors"].append(_split_name(value))
        elif tag == "JT":
            rec["journal"] = value
        elif tag == "TA":
            rec["journal_abbrev"] = value
        elif tag == "DP":
            yr = re.search(r"\d{4}", value)
            rec["year"] = yr.group(0) if yr else ""
        elif tag == "VI":
            rec["volume"] = value
        elif tag == "IP":
            rec["issue"] = value
        elif tag == "PG":
            rec["pages"] = value
        elif tag == "LA":
            rec["language"] = value
        elif tag == "PT":
            rec["pub_types"].append(value)
        elif tag == "MH":
            rec["mesh"].append(value.split("/")[0].lstrip("*"))
        elif tag in ("LID", "AID") and "[doi]" in value and not rec["doi"]:
            rec["doi"] = value.replace("[doi]", "").strip()
        elif tag == "PMC":
            rec["pmcid"] = value
    return records


CSV_COLUMNS = {
    "title": ["title", "article title", "document title"],
    "authors": ["authors", "author", "author full names", "author(s)"],
    "year": ["year", "publication year", "pubyear", "py"],
    "journal": ["source", "journal", "source title", "publication", "publisher"],
    "doi": ["doi"],
    "abstract": ["abstract"],
    "pmid": ["pmid", "pubmed id"],
    "volume": ["volume"],
    "issue": ["issue"],
    "pages": ["pages", "startpage"],
}


def parse_csv(data: bytes, source: str) -> list[dict]:
    text = _decode(data)
    dialect = csv.Sniffer().sniff(text[:5000], delimiters=",;\t") if text.strip() else csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        return []
    lookup = {name.strip().lower(): name for name in reader.fieldnames}
    cols = {key: next((lookup[c] for c in options if c in lookup), None) for key, options in CSV_COLUMNS.items()}
    if not cols["title"]:
        raise ValueError("The file needs a column called Title.")
    records = []
    for row in reader:
        rec = _blank(source)
        for key, col in cols.items():
            if not col:
                continue
            value = (row.get(col) or "").strip()
            if key == "authors":
                sep = ";" if ";" in value else ","
                rec["authors"] = [_split_name(n) for n in value.split(sep) if n.strip()]
            elif key == "year":
                yr = re.search(r"\d{4}", value)
                rec["year"] = yr.group(0) if yr else ""
            elif key == "doi":
                rec["doi"] = _clean_doi(value)
            else:
                rec[key] = value
        if rec["title"]:
            records.append(rec)
    return records


def parse_file(filename: str, data: bytes) -> list[dict]:
    name = filename.lower()
    source = f"Imported: {filename}"
    if name.endswith((".ris", ".txt")) and b"TY  -" in data[:5000]:
        return parse_ris(data, source)
    if name.endswith((".nbib", ".txt")) and b"PMID-" in data[:5000]:
        return parse_nbib(data, source)
    if name.endswith((".csv", ".tsv")):
        return parse_csv(data, source)
    if b"TY  -" in data[:5000]:
        return parse_ris(data, source)
    raise ValueError("Unsupported file. Use RIS (.ris), PubMed (.nbib) or CSV (.csv).")
