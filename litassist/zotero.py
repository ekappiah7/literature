"""Send records to a Zotero collection through the Zotero web API.

Needs the numeric user ID and a private key with write access, both from
zotero.org/settings/keys. Items sync to the Zotero desktop app automatically.
"""

import requests

API = "https://api.zotero.org"
BATCH = 50


class ZoteroError(RuntimeError):
    pass


class Zotero:
    def __init__(self, user_id: str, api_key: str, session: requests.Session | None = None):
        if not user_id or not api_key:
            raise ZoteroError("Add your Zotero user ID and API key in Settings first.")
        self.base = f"{API}/users/{user_id.strip()}"
        self.session = session or requests.Session()
        self.session.headers.update({"Zotero-API-Key": api_key.strip(), "Zotero-API-Version": "3"})

    def _check(self, resp: requests.Response) -> requests.Response:
        if resp.status_code == 403:
            raise ZoteroError("Zotero refused the key. Check it has library write access.")
        if resp.status_code >= 400:
            raise ZoteroError(f"Zotero returned HTTP {resp.status_code}: {resp.text[:300]}")
        return resp

    def check(self) -> str:
        self._check(self.session.get(f"{self.base}/collections/top", params={"limit": 1}, timeout=30))
        return "Zotero connected."

    def find_or_create_collection(self, name: str) -> str:
        start = 0
        while True:
            resp = self._check(self.session.get(
                f"{self.base}/collections", params={"limit": 100, "start": start}, timeout=30))
            batch = resp.json()
            for c in batch:
                if c["data"]["name"] == name:
                    return c["key"]
            if len(batch) < 100:
                break
            start += 100
        resp = self._check(self.session.post(f"{self.base}/collections", json=[{"name": name}], timeout=30))
        created = resp.json().get("successful", {})
        if not created:
            raise ZoteroError(f"Could not create collection: {resp.json().get('failed')}")
        return next(iter(created.values()))["key"]

    def add_items(self, records: list[dict], collection_key: str, progress=None) -> dict[int, str]:
        """Create items and return {record id: Zotero item key}."""
        keys: dict[int, str] = {}
        for start in range(0, len(records), BATCH):
            chunk = records[start:start + BATCH]
            payload = [to_zotero_item(r, collection_key) for r in chunk]
            resp = self._check(self.session.post(f"{self.base}/items", json=payload, timeout=60))
            result = resp.json()
            for idx, item in result.get("successful", {}).items():
                keys[chunk[int(idx)]["id"]] = item["key"]
            if result.get("failed"):
                first = next(iter(result["failed"].values()))
                raise ZoteroError(f"Zotero rejected some items: {first.get('message')}")
            if progress:
                progress(min(start + BATCH, len(records)), len(records))
        return keys


def to_zotero_item(r: dict, collection_key: str) -> dict:
    extra = []
    if r["pmid"]:
        extra.append(f"PMID: {r['pmid']}")
    if r["pmcid"]:
        extra.append(f"PMCID: {r['pmcid']}")
    tags = [{"tag": m} for m in r["mesh"]]
    if r.get("ta_decision"):
        tags.append({"tag": f"screen:{r['ta_decision']}"})
    return {
        "itemType": "journalArticle",
        "title": r["title"],
        "creators": [
            {"creatorType": "author", "lastName": a["last"], "firstName": a["first"] or a["initials"]}
            if a["first"] or a["initials"] else {"creatorType": "author", "name": a["last"]}
            for a in r["authors"]
        ],
        "abstractNote": r["abstract"],
        "publicationTitle": r["journal"],
        "journalAbbreviation": r["journal_abbrev"],
        "volume": r["volume"],
        "issue": r["issue"],
        "pages": r["pages"],
        "date": r["year"],
        "language": r["language"],
        "DOI": r["doi"],
        "url": f"https://pubmed.ncbi.nlm.nih.gov/{r['pmid']}/" if r["pmid"] else "",
        "extra": "\n".join(extra),
        "tags": tags,
        "collections": [collection_key],
    }
