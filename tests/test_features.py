import importlib.util
import io
import json
from pathlib import Path

import pytest
from docx import Document

from litassist import ai, charting, db, reporting, service
from litassist.export import to_ris
from litassist.importers import parse_csv, parse_file, parse_nbib, parse_ris
from litassist.pubmed import parse_pubmed_xml
from litassist.sources import parse_epmc, parse_openalex

HERE = Path(__file__).parent


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("LITASSIST_HOME", str(tmp_path))
    return db.connect(tmp_path / "t.db")


@pytest.fixture
def records():
    return parse_pubmed_xml((HERE / "pubmed_sample.xml").read_bytes())


class FakeAI:
    """Stands in for ai.AI: returns canned JSON and records the prompts."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def json(self, system, user, schema, max_tokens=4096):
        self.calls.append((system, user))
        return (self.reply(user) if callable(self.reply) else self.reply), "fake-model"


# Upgrading a database made by the first release

def test_migrates_first_release_database(tmp_path):
    spec = importlib.util.spec_from_file_location("old_db", HERE / "old_db_v1.py")
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    path = tmp_path / "old.db"
    oc = old.connect(path)
    pid = old.create_project(oc, "Old project", question="Q")
    old.add_records(oc, pid, None, [{"source": "PubMed", "pmid": "1", "title": "An old record about IVF outcomes"}])
    old.set_decision(oc, 1, "include")
    oc.close()

    conn = db.connect(path)
    rec = db.list_records(conn, pid)[0]
    assert rec["ta_decision"] == "include"
    assert rec["ai_decision"] == "" and rec["ft_decision"] == "" and rec["chart"] == {}
    assert rec["norm_title"] == "an old record about ivf outcomes"
    assert db.reasons(db.get_project(conn, pid)) == db.DEFAULT_EXCLUSION_REASONS
    assert db.counts(conn, pid)["ft_sought"] == 1


# Imports and other sources

def test_ris_round_trip(conn, records):
    pid = db.create_project(conn, "P")
    db.add_records(conn, pid, None, records)
    ris = to_ris(db.list_records(conn, pid)).encode()
    back = parse_ris(ris, "Imported: x.ris")
    assert [r["title"] for r in back] == [r["title"] for r in records]
    assert back[0]["pmid"] == "11111111" and back[0]["doi"] == "10.1000/example.1"
    assert back[0]["pages"] == "101-110" and back[0]["authors"][0]["last"] == "Mensah"
    # importing the round-tripped file into the same project finds every duplicate
    assert db.add_records(conn, pid, None, back) == (0, 2)


def test_csv_and_nbib():
    csv_data = ("Authors,Title,Year,Source,DOI\n"
                "\"K Mensah, A Owusu\",IVF outcomes in Accra: a review of 300 cycles,2019,Ghana Med J,"
                "https://doi.org/10.4314/gmj.v53i1.1\n").encode()
    rec = parse_csv(csv_data, "Imported: gs.csv")[0]
    assert rec["year"] == "2019" and rec["doi"] == "10.4314/gmj.v53i1.1" and len(rec["authors"]) == 2
    nbib = (b"PMID- 123456\nTI  - Embryo transfer outcomes in Lagos: a\n      retrospective study.\n"
            b"FAU - Adeyemi, Tunde\nJT  - Afr J Reprod Health\nDP  - 2015 Mar\nLID - 10.1/abc [doi]\n"
            b"AB  - We studied 100 women.\n\nPMID- 654321\nTI  - Second record title here.\n")
    recs = parse_nbib(nbib)
    assert recs[0]["title"] == "Embryo transfer outcomes in Lagos: a retrospective study."
    assert recs[0]["year"] == "2015" and recs[0]["doi"] == "10.1/abc" and recs[0]["authors"][0]["last"] == "Adeyemi"
    assert len(recs) == 2
    assert parse_file("x.nbib", nbib)[0]["pmid"] == "123456"
    with pytest.raises(ValueError):
        parse_file("x.docx", b"nonsense")


def test_title_dedup_across_sources(conn, records):
    pid = db.create_project(conn, "P")
    db.add_records(conn, pid, None, records)
    same_paper = {"source": "OpenAlex", "title": "Live birth after IVF in Kumasi, Ghana - a cohort study",
                  "year": "2021"}
    other_year = {"source": "OpenAlex", "title": "Live birth after IVF in Kumasi, Ghana: a cohort study.",
                  "year": "2010"}
    assert db.add_records(conn, pid, None, [same_paper, other_year]) == (1, 1)


def test_parse_epmc_and_openalex():
    e = parse_epmc({"source": "MED", "pmid": "9", "doi": "10.1/x", "title": "T", "abstractText": "<h4>A</h4> text",
                    "authorList": {"author": [{"lastName": "Boateng", "firstName": "Ama", "initials": "A"}]},
                    "journalInfo": {"yearOfPublication": 2020, "volume": "3", "journal": {"title": "J"}}})
    assert e["pmid"] == "9" and e["abstract"] == "A text" and e["year"] == "2020" and e["journal"] == "J"
    o = parse_openalex({"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1/y", "display_name": "Title",
                        "publication_year": 2022, "ids": {"pmid": "https://pubmed.ncbi.nlm.nih.gov/77"},
                        "abstract_inverted_index": {"IVF": [0], "in": [1], "Ghana": [2]},
                        "authorships": [{"author": {"display_name": "Kwame Nkrumah Mensah"}}],
                        "biblio": {"first_page": "5", "last_page": "9"}, "open_access": {"oa_url": "http://x"}})
    assert o["doi"] == "10.1/y" and o["pmid"] == "77" and o["abstract"] == "IVF in Ghana"
    assert o["authors"][0] == {"last": "Mensah", "first": "Kwame Nkrumah", "initials": "KN"}
    assert o["pages"] == "5-9" and o["oa_url"] == "http://x"


def test_import_logs_search(conn, records):
    pid = db.create_project(conn, "P")
    ris = to_ris([dict(r, id=0, ta_decision="", ta_reason="") for r in records]).encode()
    r = service.import_file(conn, pid, "ajol.ris", ris)
    assert r["new"] == 2
    log = db.list_searches(conn, pid)[0]
    assert log["source"] == "Imported: ajol.ris" and log["retrieved"] == 2


# AI screening

def test_ai_router_falls_back(monkeypatch):
    class Broken:
        name, model = "Gemini", "g"

        def json(self, *a, **k):
            raise ai.AIError("quota")

    class Works:
        name, model = "Anthropic", "c"

        def json(self, *a, **k):
            return {"decision": "maybe", "reason": "r", "criterion": "c", "confidence": "odd"}

    monkeypatch.setattr(ai, "make_provider", lambda name, s: Broken() if name == "gemini" else Works())
    router = ai.AI({"ai_primary": "gemini", "ai_use_backup": "yes"})
    result = ai.screen(router, {}, {"title": "t", "journal": "", "year": "", "pub_types": [], "abstract": ""})
    assert result["decision"] == "maybe" and result["model"] == "c" and result["confidence"] == "low"
    no_backup = ai.AI({"ai_primary": "gemini", "ai_use_backup": "no"})
    with pytest.raises(ai.AIError):
        ai.screen(no_backup, {}, {"title": "t", "journal": "", "year": "", "pub_types": [], "abstract": ""})


def test_ai_requires_a_key():
    with pytest.raises(ai.AIError):
        ai.AI({"ai_primary": "gemini", "ai_use_backup": "yes", "gemini_api_key": "", "anthropic_api_key": ""})


def test_gemini_request_and_schema_fallback():
    class Resp:
        def __init__(self, status, data):
            self.status_code, self._data, self.text = status, data, json.dumps(data)

        def json(self):
            return self._data

    class Session:
        def __init__(self):
            self.bodies = []

        def post(self, url, headers, json, timeout):
            self.bodies.append(json)
            assert headers["x-goog-api-key"] == "k" and "gemini-3.8-flash" in url
            if "responseJsonSchema" in json["generationConfig"]:
                return Resp(400, {"error": {"message": "Unknown name responseJsonSchema"}})
            text = '```json\n{"decision": "include", "reason": "r", "criterion": "c", "confidence": "high"}\n```'
            return Resp(200, {"candidates": [{"content": {"parts": [{"text": "thinking", "thought": True},
                                                                     {"text": text}]}}]})

    ai.GeminiProvider.use_schema = True
    s = Session()
    p = ai.GeminiProvider("k", session=s)
    assert p.json("sys", "user", ai.SCREEN_SCHEMA)["decision"] == "include"
    assert len(s.bodies) == 2 and ai.GeminiProvider.use_schema is False
    ai.GeminiProvider.use_schema = True


def test_ai_batch_and_agreement(conn, records, monkeypatch):
    pid = db.create_project(conn, "P", inclusion="IVF in Ghana")
    db.add_records(conn, pid, None, records)
    recs = db.list_records(conn, pid)
    fake = FakeAI(lambda user: {"decision": "exclude" if "ICSI" in user else "include", "reason": "r",
                                "criterion": "c", "confidence": "high"})
    monkeypatch.setattr(service, "AI", lambda s: fake)
    out = service.ai_screen_batch(conn, db.get_project(conn, pid), recs, {}, workers=2)
    assert out == {"done": 2, "failed": 0, "errors": []}
    assert "IVF in Ghana" in fake.calls[0][0]
    assert [r["title"] for r in db.list_by_ai(conn, pid, "exclude")] == ["ICSI outcomes in West Africa."]
    db.set_decision(conn, recs[0]["id"], "include")
    db.set_decision(conn, recs[1]["id"], "include")
    agree = db.ai_agreement(conn, pid)
    assert agree["compared"] == 2 and agree["agreed"] == 1 and agree["ai_would_miss"] == 1


# Second screener

def test_second_screener_kappa(conn):
    pid = db.create_project(conn, "P")
    db.add_records(conn, pid, None, [{"source": "x", "pmid": str(i), "title": f"Record number {i}"} for i in range(10)])
    recs = db.list_records(conn, pid)
    mine = ["include"] * 5 + ["exclude"] * 5
    theirs = ["include"] * 4 + ["exclude"] * 6
    for r, a, b in zip(recs, mine, theirs):
        db.set_decision(conn, r["id"], a, "x" if a == "exclude" else "")
        db.set_second_decision(conn, r["id"], b)
    s = db.screener_agreement(conn, pid)
    assert s["compared"] == 10 and s["percent"] == 90.0 and s["kappa"] == 0.8
    assert len(db.list_disagreements(conn, pid)) == 1


# Full text, charting and reporting

def test_fulltext_counts_and_upload(conn, records):
    from litassist import fulltext
    pid = db.create_project(conn, "P")
    db.add_records(conn, pid, None, records)
    a, b = db.list_records(conn, pid)
    db.set_decision(conn, a["id"], "include")
    db.set_decision(conn, b["id"], "maybe")
    path = fulltext.save_upload(db.get_record(conn, a["id"]), "paper.txt", b"Full text of the paper. " * 100)
    db.set_pdf(conn, a["id"], path)
    assert fulltext.read_text(path).startswith("Full text of the paper.")
    db.set_ft_decision(conn, a["id"], "include")
    db.set_ft_decision(conn, b["id"], "exclude", "Wrong population")
    c = db.counts(conn, pid)
    assert (c["ft_sought"], c["ft_not_retrieved"], c["ft_assessed"], c["ft_included"], c["ft_excluded"]) == (2, 1, 2, 1, 1)
    assert c["ft_excluded_reasons"] == {"Wrong population": 1}
    assert [r["id"] for r in db.included_in_review(conn, pid)] == [a["id"]]
    with pytest.raises(ValueError):
        fulltext.save_upload(db.get_record(conn, a["id"]), "paper.docx", b"PK..")


def test_jats_text():
    from litassist.fulltext import _jats_to_text
    xml = (b"<article><front><article-meta><title-group><article-title>My title</article-title></title-group>"
           b"<abstract><p>Short abstract.</p></abstract></article-meta></front><body><sec><title>Methods</title>"
           b"<p>We analysed 412 cycles.</p></sec></body></article>")
    text = _jats_to_text(xml)
    assert "My title" in text and "## Methods" in text and "We analysed 412 cycles." in text


def test_charting_extract_verifies_quotes():
    project = {"chart_fields": "Number of cycles: count\nDenominator: per what\nCountry: where"}
    text = "We analysed 412 IVF cycles in Kumasi, Ghana. Rates are per embryo transfer."
    fake = FakeAI({"fields": [
        {"name": "Number of cycles", "value": "412", "quote": "We analysed 412 IVF cycles"},
        {"name": "denominator", "value": "Per transfer", "quote": "rates are per embryo-transfer"},
        {"name": "Country", "value": "Nigeria", "quote": "treated in Lagos, Nigeria"},
    ]})
    chart, model = charting.extract(fake, project, {"title": "T", "year": "2020"}, text)
    assert chart["Number of cycles"] == {"value": "412", "quote": "We analysed 412 IVF cycles", "verified": True}
    assert chart["Denominator"]["verified"] is True
    assert chart["Country"]["verified"] is False
    assert model == "fake-model"


def test_draft_citations_are_checked(conn, records):
    pid = db.create_project(conn, "P")
    db.add_records(conn, pid, None, records)
    recs = db.list_records(conn, pid)
    a, b = recs
    db.set_chart(conn, a["id"], {"Number of cycles": {"value": "200", "quote": "", "verified": False}}, "checked")
    pool = [db.get_record(conn, a["id"])]
    fake = FakeAI({"sections": [{"heading": "Outcomes", "paragraphs": [
        f"One Ghanaian study reported 200 cycles [R{a['id']}].",
        f"Another claim [R{b['id']}] and an invented one [R9999].",
    ]}]})
    sections, report, model = reporting.draft(fake, db.get_project(conn, pid), pool)
    assert "(Mensah and Owusu, 2021)" in sections[0]["paragraphs"][0]
    assert "citation removed" in sections[0]["paragraphs"][1]
    assert report["cited"] == [a["id"]] and set(report["invalid_markers"]) == {b["id"], 9999}
    assert "Number of cycles: 200" in fake.calls[0][1]
    methods = reporting.methods_text([], db.counts(conn, pid))
    doc = Document(io.BytesIO(reporting.draft_docx(db.get_project(conn, pid), sections, pool, methods, report, model)))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "References" in text and "Mensah K, Owusu A (2021). Live birth after IVF in Kumasi" in text
    assert "https://doi.org/10.1000/example.1" in text


def test_prisma_and_methods(conn, records):
    pid = db.create_project(conn, "P")
    sid = db.log_search(conn, pid, "PubMed", "ivf AND ghana", 2, "from 2020")
    db.add_records(conn, pid, sid, records)
    db.finish_search(conn, sid, 2, 2, 0)
    c = db.counts(conn, pid)
    png = reporting.prisma_png(c)
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 20000
    text = reporting.methods_text(db.list_searches(conn, pid), c)
    assert "We searched PubMed" in text and "from 2020" in text and "2 records were identified" in text


def test_backup_excludes_settings(conn, tmp_path):
    import zipfile
    from litassist import config
    config.save_settings({"gemini_api_key": "secret"})
    name, data = service.backup_zip()
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert "t.db" in names and "settings.json" not in names
