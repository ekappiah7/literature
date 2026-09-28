"""Finding, storing and reading full texts.

Free full texts come from Europe PMC (open access XML for PubMed Central
articles) and Unpaywall (legal open access PDFs found by DOI). Paywalled
papers can be uploaded as PDFs obtained through the university library.
Files are kept in Documents\\LitAssist\\fulltexts\\<project id>.
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
from pypdf import PdfReader

from litassist import config

EPMC_XML = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
UNPAYWALL = "https://api.unpaywall.org/v2/{doi}"
HEADERS = {"User-Agent": "LitAssist/1.0 (personal literature review tool)"}


def folder(project_id: int) -> Path:
    path = config.data_dir() / "fulltexts" / str(project_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _jats_to_text(xml: bytes) -> str:
    root = ET.fromstring(xml)
    parts = []
    title = root.find(".//article-title")
    if title is not None:
        parts.append(" ".join("".join(title.itertext()).split()))
    for tag in ("abstract", "body"):
        for section in root.iter(tag):
            for el in section.iter():
                if el.tag in ("title", "p", "td", "th", "caption"):
                    text = " ".join("".join(el.itertext()).split())
                    if text:
                        parts.append(("\n## " + text) if el.tag == "title" else text)
                    el.clear()
    return "\n\n".join(parts)


def fetch_open_access(record: dict, email: str, session: requests.Session | None = None) -> tuple[str, str]:
    """Try to save a free full text. Returns (saved path or '', where it came from or why not)."""
    session = session or requests.Session()
    session.headers.update(HEADERS)
    dest = folder(record["project_id"])
    if record.get("pmcid"):
        try:
            resp = session.get(EPMC_XML.format(pmcid=record["pmcid"]), timeout=60)
            if resp.status_code == 200 and resp.content.strip().startswith(b"<"):
                text = _jats_to_text(resp.content)
                if len(text) > 2000:
                    path = dest / f"{record['id']}.txt"
                    path.write_text(text, encoding="utf-8")
                    return str(path), f"Europe PMC open access ({record['pmcid']})"
        except (requests.RequestException, ET.ParseError):
            pass
    urls = [record["oa_url"]] if record.get("oa_url") else []
    if record.get("doi") and email:
        try:
            resp = session.get(UNPAYWALL.format(doi=record["doi"]), params={"email": email}, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                for loc in [data.get("best_oa_location")] + (data.get("oa_locations") or []):
                    if loc:
                        urls += [u for u in (loc.get("url_for_pdf"), loc.get("url")) if u]
        except (requests.RequestException, ValueError):
            pass
    seen = set()
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        try:
            resp = session.get(url, timeout=60, allow_redirects=True)
        except requests.RequestException:
            continue
        if resp.status_code == 200 and resp.content[:5] == b"%PDF-":
            path = dest / f"{record['id']}.pdf"
            path.write_bytes(resp.content)
            return str(path), f"Open access PDF ({url})"
    if not record.get("doi") and not record.get("pmcid"):
        return "", "No DOI or PMCID to look up."
    if record.get("doi") and not email:
        return "", "Add your email in Settings so Unpaywall can be searched."
    return "", "No free full text found. Get it through your library and upload the PDF."


def save_upload(record: dict, filename: str, data: bytes) -> str:
    suffix = ".pdf" if data[:5] == b"%PDF-" else Path(filename).suffix.lower() or ".txt"
    if suffix not in (".pdf", ".txt"):
        raise ValueError("Upload a PDF or plain text file.")
    path = folder(record["project_id"]) / f"{record['id']}{suffix}"
    path.write_bytes(data)
    return str(path)


def read_text(path: str, max_chars: int = 400_000) -> str:
    """Plain text of a stored full text, for reading and AI charting."""
    if not path or not Path(path).exists():
        return ""
    p = Path(path)
    if p.suffix == ".pdf":
        try:
            reader = PdfReader(str(p))
            text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception:  # noqa: BLE001 - damaged or encrypted PDFs
            return ""
    else:
        text = p.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"[ \t]+", " ", text)
    return text[:max_chars]
