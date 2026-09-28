"""PubMed search through the NCBI E-utilities API.

ESearch finds matching PMIDs and keeps them on the NCBI history server, then
EFetch downloads full records (title, abstract, authors, MeSH, DOI) in batches.
NCBI allows 3 requests per second without an API key and 10 with one.
"""

import time
import xml.etree.ElementTree as ET

import requests

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
TOOL = "litassist"
BATCH = 200


class PubMedError(RuntimeError):
    pass


class PubMed:
    def __init__(self, email: str = "", api_key: str = "", session: requests.Session | None = None):
        self.email = email.strip()
        self.api_key = api_key.strip()
        self.session = session or requests.Session()
        self._interval = 0.11 if self.api_key else 0.34
        self._last = 0.0

    def _params(self, **extra) -> dict:
        params = {"db": "pubmed", "tool": TOOL, **extra}
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    def _get(self, endpoint: str, **params) -> requests.Response:
        for attempt in range(4):
            wait = self._interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                resp = self.session.post(BASE + endpoint, data=self._params(**params), timeout=60)
            except requests.RequestException as exc:
                if attempt == 3:
                    raise PubMedError(f"Could not reach PubMed: {exc}") from exc
                time.sleep(2 ** attempt)
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            if resp.status_code != 200:
                raise PubMedError(f"PubMed returned HTTP {resp.status_code}: {resp.text[:300]}")
            return resp
        raise PubMedError("PubMed is busy. Please try again in a minute.")

    def search(self, query: str, mindate: str = "", maxdate: str = "") -> dict:
        """Run ESearch. Returns count, query translation, and history keys."""
        extra = {"term": query, "usehistory": "y", "retmax": 0, "retmode": "json"}
        if mindate or maxdate:
            extra.update(datetype="pdat", mindate=mindate or "1800", maxdate=maxdate or "3000")
        data = self._get("esearch.fcgi", **extra).json()
        result = data.get("esearchresult", {})
        if "ERROR" in result:
            raise PubMedError(result["ERROR"])
        return {
            "count": int(result.get("count", 0)),
            "webenv": result.get("webenv", ""),
            "query_key": result.get("querykey", ""),
            "translation": result.get("querytranslation", ""),
            "warnings": result.get("warninglist", {}),
            "errors": result.get("errorlist", {}),
        }

    def fetch(self, search: dict, limit: int, progress=None) -> list[dict]:
        """Download up to `limit` records from a previous search."""
        total = min(search["count"], limit)
        records: list[dict] = []
        for start in range(0, total, BATCH):
            resp = self._get(
                "efetch.fcgi",
                WebEnv=search["webenv"],
                query_key=search["query_key"],
                retstart=start,
                retmax=min(BATCH, total - start),
                retmode="xml",
            )
            records.extend(parse_pubmed_xml(resp.content))
            if progress:
                progress(min(start + BATCH, total), total)
        return records

    def check(self) -> str:
        info = self.search("fertilization in vitro[mh] AND ghana[tiab]")
        return f"PubMed is reachable. Test search found {info['count']} records."


def _text(el) -> str:
    return " ".join("".join(el.itertext()).split()) if el is not None else ""


def _year(article) -> str:
    for path in (
        ".//Article/Journal/JournalIssue/PubDate/Year",
        ".//Article/ArticleDate/Year",
        ".//PubmedData/History/PubMedPubDate[@PubStatus='pubmed']/Year",
    ):
        el = article.find(path)
        if el is not None and el.text:
            return el.text.strip()
    medline = article.find(".//Article/Journal/JournalIssue/PubDate/MedlineDate")
    if medline is not None and medline.text:
        return medline.text.strip()[:4]
    return ""


def parse_pubmed_xml(content: bytes) -> list[dict]:
    root = ET.fromstring(content)
    out = []
    for art in root.findall("PubmedArticle"):
        cit = art.find("MedlineCitation")
        article = cit.find("Article")

        abstract_parts = []
        for part in article.findall("Abstract/AbstractText"):
            label = part.get("Label")
            text = _text(part)
            if text:
                abstract_parts.append(f"{label}: {text}" if label else text)

        authors = []
        for au in article.findall("AuthorList/Author"):
            last = au.findtext("LastName")
            if last:
                initials = au.findtext("Initials") or ""
                fore = au.findtext("ForeName") or ""
                authors.append({"last": last, "first": fore, "initials": initials})
            elif au.findtext("CollectiveName"):
                authors.append({"last": au.findtext("CollectiveName"), "first": "", "initials": ""})

        ids = {i.get("IdType"): (i.text or "").strip() for i in art.findall("PubmedData/ArticleIdList/ArticleId")}
        doi = ids.get("doi", "")
        if not doi:
            for loc in article.findall("ELocationID"):
                if loc.get("EIdType") == "doi":
                    doi = (loc.text or "").strip()

        journal = article.find("Journal")
        out.append({
            "source": "PubMed",
            "pmid": cit.findtext("PMID", "").strip(),
            "doi": doi,
            "pmcid": ids.get("pmc", ""),
            "title": _text(article.find("ArticleTitle")),
            "abstract": "\n\n".join(abstract_parts),
            "authors": authors,
            "journal": journal.findtext("Title", "") if journal is not None else "",
            "journal_abbrev": journal.findtext("ISOAbbreviation", "") if journal is not None else "",
            "year": _year(art),
            "volume": article.findtext("Journal/JournalIssue/Volume", ""),
            "issue": article.findtext("Journal/JournalIssue/Issue", ""),
            "pages": article.findtext("Pagination/MedlinePgn", ""),
            "language": article.findtext("Language", ""),
            "pub_types": [_text(p) for p in article.findall("PublicationTypeList/PublicationType")],
            "mesh": [_text(m.find("DescriptorName")) for m in cit.findall("MeshHeadingList/MeshHeading")],
            "keywords": [_text(k) for k in cit.findall("KeywordList/Keyword")],
        })
    return out
