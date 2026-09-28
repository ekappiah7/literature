"""AI helpers: Gemini as the main model, Anthropic Claude as the backup.

Every AI call asks for JSON that matches a schema, so answers can be checked
before use. The AI only suggests: screening suggestions, charting values with
supporting quotes, and draft text. The researcher confirms everything.
If the main provider fails (no key, rate limit, outage), the backup is tried.
"""

import json

import anthropic
import requests

GEMINI_MODELS = {
    "gemini-3.8-flash": "Gemini 3.8 Flash (latest, recommended)",
    "gemini-3-flash-preview": "Gemini 3 Flash (preview)",
    "gemini-3.5-flash-lite": "Gemini 3.5 Flash-Lite (cheapest)",
}
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"

ANTHROPIC_MODELS = {
    "claude-opus-5": "Claude Opus 5",
    "claude-sonnet-5": "Claude Sonnet 5 (cheaper)",
}
DEFAULT_ANTHROPIC_MODEL = "claude-opus-5"

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class AIError(RuntimeError):
    pass


def parse_json(text: str) -> dict:
    """Parse a JSON object, tolerating a surrounding code fence or stray text."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found")
    return json.loads(text[start:end + 1])


# Providers

class GeminiProvider:
    name = "Gemini"
    use_schema = True  # switched off if Google stops accepting the schema fields

    def __init__(self, api_key: str, model: str = DEFAULT_GEMINI_MODEL, session: requests.Session | None = None):
        if not api_key:
            raise AIError("No Gemini API key in Settings.")
        self.api_key = api_key.strip()
        self.model = model or DEFAULT_GEMINI_MODEL
        self.session = session or requests.Session()

    def _post(self, body: dict) -> tuple[int, dict | str]:
        try:
            resp = self.session.post(
                GEMINI_URL.format(model=self.model),
                headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
                json=body,
                timeout=300,
            )
        except requests.RequestException as exc:
            raise AIError(f"Could not reach Gemini: {exc}") from exc
        if resp.status_code == 200:
            return 200, resp.json()
        try:
            return resp.status_code, resp.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            return resp.status_code, resp.text[:300]

    def json(self, system: str, user: str, schema: dict, max_tokens: int = 4096) -> dict:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        if GeminiProvider.use_schema:
            body["generationConfig"].update(responseMimeType="application/json", responseJsonSchema=schema)
        status, data = self._post(body)
        if status == 400 and GeminiProvider.use_schema and "response" in str(data).lower():
            GeminiProvider.use_schema = False
            body["generationConfig"] = {"maxOutputTokens": max_tokens}
            status, data = self._post(body)
        if status != 200:
            raise AIError(f"Gemini returned HTTP {status}: {data}")
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            return parse_json(text)
        except (KeyError, IndexError, ValueError) as exc:
            reason = (data.get("candidates") or [{}])[0].get("finishReason") or data.get("promptFeedback")
            raise AIError(f"Gemini gave no usable answer ({reason}).") from exc


class ClaudeProvider:
    name = "Anthropic"

    def __init__(self, api_key: str, model: str = DEFAULT_ANTHROPIC_MODEL):
        if not api_key:
            raise AIError("No Anthropic API key in Settings.")
        self.model = model or DEFAULT_ANTHROPIC_MODEL
        self.client = anthropic.Anthropic(api_key=api_key.strip(), max_retries=3)

    def json(self, system: str, user: str, schema: dict, max_tokens: int = 4096) -> dict:
        try:
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
                # If a safety classifier declines, the API re-runs the request on a recommended fallback model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.AuthenticationError as exc:
            raise AIError("Anthropic rejected the API key.") from exc
        except anthropic.RateLimitError as exc:
            raise AIError("Anthropic rate limit reached. Try again shortly.") from exc
        except anthropic.APIStatusError as exc:
            raise AIError(f"Anthropic returned HTTP {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise AIError(f"Could not reach Anthropic: {exc}") from exc
        if response.stop_reason == "refusal":
            raise AIError("Anthropic declined this request.")
        if response.stop_reason == "max_tokens":
            raise AIError("Anthropic's answer was cut off.")
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            return parse_json(text)
        except ValueError as exc:
            raise AIError("Anthropic gave no usable answer.") from exc


class AI:
    """Tries the main provider, then the backup. Reports which model answered."""

    def __init__(self, settings: dict):
        self.providers = []
        problems = []
        order = ["gemini", "anthropic"] if settings.get("ai_primary", "gemini") == "gemini" else ["anthropic", "gemini"]
        if settings.get("ai_use_backup", "yes") != "yes":
            order = order[:1]
        for name in order:
            try:
                self.providers.append(make_provider(name, settings))
            except AIError as exc:
                problems.append(str(exc))
        if not self.providers:
            raise AIError("Add a Gemini or Anthropic API key in Settings to use the AI features. " + " ".join(problems))

    def json(self, system: str, user: str, schema: dict, max_tokens: int = 4096) -> tuple[dict, str]:
        errors = []
        for provider in self.providers:
            try:
                return provider.json(system, user, schema, max_tokens), provider.model
            except AIError as exc:
                errors.append(f"{provider.name}: {exc}")
        raise AIError(" | ".join(errors))


def make_provider(name: str, settings: dict):
    if name == "gemini":
        return GeminiProvider(settings.get("gemini_api_key", ""), settings.get("gemini_model", DEFAULT_GEMINI_MODEL))
    return ClaudeProvider(settings.get("anthropic_api_key", ""), settings.get("anthropic_model", DEFAULT_ANTHROPIC_MODEL))


def protocol_text(project: dict) -> str:
    f = {k: (project.get(k) or "not specified").strip() for k in
         ("review_type", "question", "population", "concept", "context", "inclusion", "exclusion")}
    return (
        f"Review type: {f['review_type']}\nReview question: {f['question']}\nPopulation: {f['population']}\n"
        f"Concept: {f['concept']}\nContext: {f['context']}\nInclusion criteria: {f['inclusion']}\n"
        f"Exclusion criteria: {f['exclusion']}"
    )


# Screening

SCREEN_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["include", "exclude", "maybe"]},
        "reason": {"type": "string", "description": "One sentence explaining the decision."},
        "criterion": {"type": "string", "description": "The inclusion or exclusion criterion relied on."},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["decision", "reason", "criterion", "confidence"],
    "additionalProperties": False,
}

SCREEN_SYSTEM = """You are assisting a researcher with title and abstract screening.
Judge each record strictly against the protocol below. You are making a suggestion; the researcher decides.

Rules:
- "include" if the record plausibly meets all inclusion criteria and no exclusion criterion applies.
- "exclude" only when the title or abstract clearly shows an exclusion criterion applies or an inclusion criterion is not met.
- "maybe" when the information is missing or unclear, including when there is no abstract. When in doubt, prefer maybe over exclude: missing a relevant study is worse than reading an extra full text.
- The reason must be one short sentence that refers to what the record actually says. Do not invent details.
- Set confidence to low whenever you are unsure.
- Answer only with a JSON object with the keys decision, reason, criterion and confidence.

Protocol
{protocol}"""


def record_text(record: dict) -> str:
    return (
        f"Title: {record['title'] or '(no title)'}\n"
        f"Journal and year: {record['journal']} {record['year']}\n"
        f"Publication types: {', '.join(record['pub_types']) or 'not given'}\n"
        f"Abstract: {record['abstract'] or '(no abstract available)'}"
    )


def screen(ai: AI, project: dict, record: dict) -> dict:
    data, model = ai.json(SCREEN_SYSTEM.format(protocol=protocol_text(project)), record_text(record), SCREEN_SCHEMA)
    if data.get("decision") not in ("include", "exclude", "maybe"):
        raise AIError(f"Unexpected decision in AI response: {data!r}")
    return {
        "decision": data["decision"],
        "reason": str(data.get("reason", "")).strip(),
        "criterion": str(data.get("criterion", "")).strip(),
        "confidence": data.get("confidence") if data.get("confidence") in ("high", "medium", "low") else "low",
        "model": model,
    }


# Key check

def check(provider: str, settings: dict) -> str:
    """Screen one made-up record to confirm a key works."""
    p = make_provider(provider, settings)
    project = {"review_type": "Scoping review", "question": "Outcomes of IVF in Ghana",
               "inclusion": "Human studies reporting IVF outcomes in Ghana", "exclusion": "Animal studies"}
    record = {"title": "Live birth after IVF at a Kumasi clinic", "journal": "Test", "year": "2024",
              "pub_types": [], "abstract": "We report live birth rates for 200 IVF cycles in Kumasi, Ghana."}
    data = p.json(SCREEN_SYSTEM.format(protocol=protocol_text(project)), record_text(record), SCREEN_SCHEMA, 1024)
    return f"{p.name} ({p.model}) is working. Test answer: {data.get('decision')}, {data.get('reason')}"
