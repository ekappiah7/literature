"""The charting (data extraction) form and AI-assisted filling.

The AI proposes a value for each field with the exact passage it came from.
Every quote is checked against the source text; values whose quote cannot be
found are flagged so the researcher checks them first.
"""

import re

from litassist.ai import AI, AIError, protocol_text

OBJECTIVE_1_FIELDS = """Country: country or countries where patients were treated
City and centres: city, number of centres, public or private
Study period: years of data collection
Study design: retrospective or prospective cohort, cross-sectional, trial, registry, case series
Number of women: number of women or couples
Number of cycles: number of treatment cycles
Age: age distribution of women (mean, median, range)
Infertility causes: main causes, for example tubal factor, fibroids, male factor
Treatment: IVF, ICSI or both; fresh or frozen transfer; donor cycles
Outcomes reported: biochemical, clinical or ongoing pregnancy, live birth, cumulative live birth
Outcome definitions: exactly as written by the authors
Denominator: per cycle started, per retrieval, per transfer, per woman
Unit of analysis: cycle or woman
Repeated cycles handled: Yes (how), No (treated as independent), or Unclear
Statistical methods: descriptive only, chi-square, logistic regression, multilevel or mixed models, survival or cumulative methods, Bayesian
Main results: headline success rates with their denominators
Reporting notes: gaps or problems in reporting"""

GENERIC_FIELDS = """Country and setting: where the study was done
Study design: design as described by the authors
Population: who was studied and how many
Main findings: key results relevant to the review question
Notes: anything else relevant"""


def parse_fields(text: str) -> list[dict]:
    fields = []
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        name, _, hint = line.partition(":")
        fields.append({"name": name.strip(), "hint": hint.strip()})
    return fields


def fields_for(project: dict) -> list[dict]:
    return parse_fields(project.get("chart_fields") or GENERIC_FIELDS)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def quote_found(quote: str, source: str) -> bool:
    q = _norm(quote)
    return bool(q) and q in _norm(source)


SCHEMA = {
    "type": "object",
    "properties": {
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "value": {"type": "string"},
                    "quote": {"type": "string"},
                },
                "required": ["name", "value", "quote"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["fields"],
    "additionalProperties": False,
}

SYSTEM = """You extract data from a research article into a charting form for a review.

Rules:
- Use only the article text provided. Never use outside knowledge and never guess.
- For each field give a short value and the exact sentence or phrase from the text that supports it, copied word for word.
- If the text does not report the field, set value to "Not reported" and quote to "".
- Keep numbers exactly as written, including their denominators.
- Answer only with JSON: {{"fields": [{{"name": ..., "value": ..., "quote": ...}}]}} with one entry per field, in order.

Review protocol, for context:
{protocol}"""


def extract(ai: AI, project: dict, record: dict, source_text: str) -> tuple[dict, str]:
    fields = fields_for(project)
    form = "\n".join(f"- {f['name']}: {f['hint']}" for f in fields)
    user = (f"Charting form fields:\n{form}\n\nArticle: {record['title']} ({record['year']})\n\n"
            f"Article text:\n{source_text}")
    data, model = ai.json(SYSTEM.format(protocol=protocol_text(project)), user, SCHEMA, max_tokens=8000)
    answers = {str(item.get("name", "")).strip().lower(): item for item in data.get("fields", [])}
    chart = {}
    for f in fields:
        item = answers.get(f["name"].lower(), {})
        value = str(item.get("value", "")).strip() or "Not reported"
        quote = str(item.get("quote", "")).strip()
        chart[f["name"]] = {
            "value": value,
            "quote": quote,
            "verified": bool(quote) and quote_found(quote, source_text),
        }
    if not chart:
        raise AIError("The AI returned no charting values.")
    return chart, model
