"""Europe PMC and OpenAlex searches, plus OpenAlex citation lookups.

Both services are free and need no key. OpenAlex asks for an email address
(the "polite pool"), which is taken from Settings.
"""

import time

import requests

EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
OPENALEX = "https://api.openalex.org/works"


class SourceError(RuntimeError):
    pass


def _get(session: requests.Session, url: str, params: dict) -> dict:
    for attempt in range(4):
        try:
            resp = session.get(url, params=params, timeout=60)
        except requests.RequestException as exc:
            if attempt == 3:
                raise SourceError(f"Could not reach {url.split('/')[2]}: {exc}") from exc
            time.sleep(2 ** attempt)
            continue
        if resp.status_code == 429 and "budget" in resp.text.lower():
            raise SourceError("OpenAlex's free shared allowance is used up for today. Add a free OpenAlex API key "
                              "in Settings (openalex.org/settings/api) and try again.")
        if resp.status_code == 429 or resp.status_code >= 500:
            time.sleep(2 ** attempt)
            continue
        if resp.status_code != 200:
            raise SourceError(f"{url.split('/')[2]} returned HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.json()
    raise SourceError(f"{url.split('/')[2]} is busy. Please try again in a minute.")


def _year_filter(mindate: str, maxdate: str) -> str:
    if not (mindate or maxdate):
        return ""
    return f" AND (PUB_YEAR:[{mindate or 1800} TO {maxdate or 3000}])"


# Europe PMC

class EuropePMC:
    """Searches titles, abstracts and keywords by default, not full text, to match PubMed."""

    name = "Europe PMC"

    def __init__(self, email: str = "", session: requests.Session | None = None, title_abstract_only: bool = True):
        self.email = email
        self.session = session or requests.Session()
        self.title_abstract_only = title_abstract_only

    def _q(self, query: str, mindate: str, maxdate: str) -> str:
        q = f"TITLE_ABS:({query})" if self.title_abstract_only else f"({query})"
        return q + _year_filter(mindate, maxdate)

    def count(self, query: str, mindate: str = "", maxdate: str = "") -> int:
        data = _get(self.session, EPMC, {"query": self._q(query, mindate, maxdate),
                                         "format": "json", "pageSize": 1, "resultType": "idlist"})
        return int(data.get("hitCount", 0))

    def search(self, query: str, limit: int, mindate: str = "", maxdate: str = "", progress=None) -> tuple[int, list[dict]]:
        cursor, records, hits = "*", [], 0
        while len(records) < limit:
            data = _get(self.session, EPMC, {
                "query": self._q(query, mindate, maxdate), "format": "json", "resultType": "core",
                "pageSize": min(1000, limit - len(records)), "cursorMark": cursor,
                **({"email": self.email} if self.email else {}),
            })
            hits = int(data.get("hitCount", 0))
            batch = data.get("resultList", {}).get("result", [])
            records.extend(parse_epmc(r) for r in batch)
            if progress:
                progress(min(len(records), hits, limit), min(hits, limit) or 1)
            nxt = data.get("nextCursorMark")
            if not batch or not nxt or nxt == cursor:
                break
            cursor = nxt
        return hits, records[:limit]


def parse_epmc(r: dict) -> dict:
    authors = []
    for a in (r.get("authorList") or {}).get("author", []):
        if a.get("lastName"):
            authors.append({"last": a["lastName"], "first": a.get("firstName", ""), "initials": a.get("initials", "")})
        elif a.get("collectiveName"):
            authors.append({"last": a["collectiveName"], "first": "", "initials": ""})
    journal = (r.get("journalInfo") or {})
    jinfo = journal.get("journal") or {}
    kw = (r.get("keywordList") or {}).get("keyword", [])
    mesh = [m.get("descriptorName", "") for m in (r.get("meshHeadingList") or {}).get("meshHeading", [])]
    pub_types = (r.get("pubTypeList") or {}).get("pubType", [])
    source = r.get("source", "")
    return {
        "source": "Europe PMC" + (" (preprint)" if source == "PPR" else ""),
        "pmid": r.get("pmid", "") if source == "MED" or r.get("pmid") else "",
        "doi": r.get("doi", ""),
        "pmcid": r.get("pmcid", ""),
        "title": (r.get("title") or "").rstrip(),
        "abstract": _strip_tags(r.get("abstractText", "")),
        "authors": authors,
        "journal": jinfo.get("title", "") or r.get("bookOrReportDetails", {}).get("publisher", ""),
        "journal_abbrev": jinfo.get("isoabbreviation", ""),
        "year": str(journal.get("yearOfPublication") or r.get("pubYear", "")),
        "volume": journal.get("volume", ""),
        "issue": journal.get("issue", ""),
        "pages": r.get("pageInfo", ""),
        "language": r.get("language", ""),
        "pub_types": pub_types if isinstance(pub_types, list) else [pub_types],
        "mesh": mesh,
        "keywords": kw if isinstance(kw, list) else [kw],
    }


def _strip_tags(text: str) -> str:
    out, depth = [], 0
    for ch in text or "":
        if ch == "<":
            depth += 1
        elif ch == ">" and depth:
            depth -= 1
        elif not depth:
            out.append(ch)
    return " ".join("".join(out).split())


# OpenAlex

class OpenAlex:
    name = "OpenAlex"

    def __init__(self, email: str = "", api_key: str = "", session: requests.Session | None = None):
        self.email = email
        self.api_key = api_key.strip()
        self.session = session or requests.Session()

    def _params(self, **extra) -> dict:
        params = {**extra, **({"mailto": self.email} if self.email else {})}
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    @staticmethod
    def _filter(mindate: str, maxdate: str) -> str:
        parts = []
        if mindate:
            parts.append(f"from_publication_date:{mindate}-01-01")
        if maxdate:
            parts.append(f"to_publication_date:{maxdate}-12-31")
        return ",".join(parts)

    def _page(self, params: dict) -> dict:
        return _get(self.session, OPENALEX, self._params(**params))

    def count(self, query: str, mindate: str = "", maxdate: str = "") -> int:
        params = {"search": query, "per-page": 1}
        if self._filter(mindate, maxdate):
            params["filter"] = self._filter(mindate, maxdate)
        return int(self._page(params)["meta"]["count"])

    def _collect(self, params: dict, limit: int, progress=None) -> tuple[int, list[dict]]:
        cursor, records, hits = "*", [], 0
        while len(records) < limit:
            data = self._page({**params, "per-page": 200, "cursor": cursor})
            hits = int(data["meta"]["count"])
            batch = data.get("results", [])
            records.extend(parse_openalex(w) for w in batch)
            if progress:
                progress(min(len(records), hits, limit), min(hits, limit) or 1)
            cursor = data["meta"].get("next_cursor")
            if not batch or not cursor:
                break
        return hits, records[:limit]

    def search(self, query: str, limit: int, mindate: str = "", maxdate: str = "", progress=None) -> tuple[int, list[dict]]:
        params = {"search": query}
        if self._filter(mindate, maxdate):
            params["filter"] = self._filter(mindate, maxdate)
        return self._collect(params, limit, progress)

    def work(self, doi: str = "", pmid: str = "", openalex_id: str = "") -> dict | None:
        if openalex_id:
            key = openalex_id.rsplit("/", 1)[-1]
        elif doi:
            key = f"doi:{doi}"
        elif pmid:
            key = f"pmid:{pmid}"
        else:
            return None
        try:
            return _get(self.session, f"{OPENALEX}/{key}", self._params())
        except SourceError:
            return None

    def references(self, work: dict, limit: int = 500) -> list[dict]:
        ids = [w.rsplit("/", 1)[-1] for w in work.get("referenced_works", [])][:limit]
        records = []
        for start in range(0, len(ids), 50):
            chunk = "|".join(ids[start:start + 50])
            data = self._page({"filter": f"openalex_id:{chunk}", "per-page": 50})
            records.extend(parse_openalex(w) for w in data.get("results", []))
        return records

    def cited_by(self, work: dict, limit: int = 500) -> list[dict]:
        key = work["id"].rsplit("/", 1)[-1]
        return self._collect({"filter": f"cites:{key}"}, limit)[1]


def _abstract(inverted: dict | None) -> str:
    if not inverted:
        return ""
    words = {}
    for word, positions in inverted.items():
        for pos in positions:
            words[pos] = word
    return " ".join(words[i] for i in sorted(words))


def parse_openalex(w: dict) -> dict:
    ids = w.get("ids") or {}
    pmid = (ids.get("pmid") or "").rsplit("/", 1)[-1]
    pmcid = (ids.get("pmcid") or "").rsplit("/", 1)[-1]
    authors = []
    for a in w.get("authorships", []):
        name = (a.get("author") or {}).get("display_name") or a.get("raw_author_name") or ""
        if not name:
            continue
        parts = name.split()
        last = parts[-1] if parts else name
        first = " ".join(parts[:-1])
        authors.append({"last": last, "first": first, "initials": "".join(p[0] for p in parts[:-1] if p)})
    loc = w.get("primary_location") or {}
    source = loc.get("source") or {}
    biblio = w.get("biblio") or {}
    pages = biblio.get("first_page") or ""
    if biblio.get("last_page") and biblio.get("last_page") != pages:
        pages = f"{pages}-{biblio['last_page']}"
    oa = w.get("open_access") or {}
    return {
        "source": "OpenAlex",
        "openalex_id": w.get("id", ""),
        "pmid": pmid,
        "doi": (w.get("doi") or "").replace("https://doi.org/", ""),
        "pmcid": pmcid,
        "title": w.get("display_name") or w.get("title") or "",
        "abstract": _abstract(w.get("abstract_inverted_index")),
        "authors": authors,
        "journal": source.get("display_name", ""),
        "journal_abbrev": "",
        "year": str(w.get("publication_year") or ""),
        "volume": biblio.get("volume") or "",
        "issue": biblio.get("issue") or "",
        "pages": pages,
        "language": w.get("language") or "",
        "pub_types": [w.get("type", "")] if w.get("type") else [],
        "mesh": [m.get("descriptor_name", "") for m in w.get("mesh", [])],
        "keywords": [k.get("display_name", "") for k in w.get("keywords", [])][:10],
        "oa_url": oa.get("oa_url") or "",
    }


# Starter queries for the non-PubMed sources, derived from the PubMed template topic.
EPMC_OBJ1 = (
    '("in vitro fertilization" OR "in vitro fertilisation" OR IVF OR ICSI OR "intracytoplasmic sperm injection" '
    'OR "assisted reproductive technology" OR "assisted reproduction" OR "embryo transfer") AND '
    '("sub-Saharan" OR Africa OR Ghana OR Nigeria OR Kenya OR "South Africa" OR Cameroon OR Uganda OR Tanzania '
    'OR Ethiopia OR Senegal OR "Cote d\'Ivoire" OR Togo OR Benin OR Zambia OR Zimbabwe OR Malawi OR Rwanda OR Sudan '
    'OR Mali OR "Burkina Faso" OR Niger OR Mozambique OR Namibia OR Botswana OR Gabon OR Congo) '
    'NOT (animal OR bovine OR cattle OR buffalo OR mice OR mouse)'
)
OPENALEX_OBJ1 = "(IVF OR ICSI OR \"in vitro fertilization\" OR \"assisted reproduction\") AND (Africa OR Ghana OR Nigeria OR \"sub-Saharan\")"
