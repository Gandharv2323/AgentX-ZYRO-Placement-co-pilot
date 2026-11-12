"""Optional outbound providers: Adzuna job search and an Anthropic planner.

Both are OFF unless configured, and neither is on the demo path. The whole point of
this module is that the app behaves identically with them missing — so every network
call goes through `http_json`, which tests replace with a fake. That is how these are
verified without a key or an internet connection.

Env:
  PLACEPILOT_JOBS=auto|mock|adzuna     ADZUNA_APP_ID, ADZUNA_APP_KEY, ADZUNA_COUNTRY=in
  PLACEPILOT_LLM=auto|off|anthropic    ANTHROPIC_API_KEY, PLACEPILOT_MODEL
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

from . import config, core  # config import loads .env before any mode check

_ = config

ADZUNA_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "claude-sonnet-4-5"
OPENROUTER_MODEL = "nvidia/nemotron-3.5-lightning:free"

# Free models are rate-limited and rotate availability, so a single hardcoded id is brittle.
# Tried in order; the first that answers wins, and the one that worked is remembered.
FREE_MODELS = [
    "nvidia/nemotron-3.5-lightning:free",
    "dots-studio/dots-3-note-preview:free",
    "google/gemma-4-31b-it:free",
    "cohere/north-mini-code:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
]
_LLM_PREFERENCE: list[str] = []  # models proven to answer, most recent first


def model_chain(model: str | None = None) -> list[str]:
    """Ordered model ids to try. Explicit model wins; then proven ones; then the free list."""
    if model:
        return [model]
    explicit = os.environ.get("PLACEPILOT_MODEL")
    if explicit:
        return [explicit]
    chain = [m for m in _LLM_PREFERENCE if m] + [m for m in FREE_MODELS if m not in _LLM_PREFERENCE]
    return chain


def remember_model(model: str) -> None:
    if model in _LLM_PREFERENCE:
        _LLM_PREFERENCE.remove(model)
    _LLM_PREFERENCE.insert(0, model)


class ProviderError(Exception):
    """A provider failed in a way the caller must degrade gracefully from."""


# ------------------------------------------------------------------ transport

def http_json(url: str, *, method: str = "GET", headers: dict | None = None,
              body: dict | None = None, timeout: float = 20.0) -> dict:
    """The single network chokepoint. Tests monkeypatch exactly this."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return json.loads(res.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise ProviderError(f"HTTP {exc.code} from {urllib.parse.urlparse(url).netloc}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise ProviderError(f"{type(exc).__name__} calling {urllib.parse.urlparse(url).netloc}") from exc


# ------------------------------------------------------------------ jobs

def adzuna_configured() -> bool:
    return bool(os.environ.get("ADZUNA_APP_ID") and os.environ.get("ADZUNA_APP_KEY"))


def jobs_mode() -> str:
    """auto: Adzuna when configured, otherwise the seeded set. mock/adzuna force one."""
    mode = (os.environ.get("PLACEPILOT_JOBS") or "auto").lower()
    if mode == "adzuna":
        return "adzuna" if adzuna_configured() else "mock"
    if mode == "mock":
        return "mock"
    return "adzuna" if adzuna_configured() else "mock"


def _parse_iso(value) -> str:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date().isoformat()
    except (ValueError, TypeError):
        return (date.today() + timedelta(days=14)).isoformat()


def _first(text: str, words: list[str]) -> list[str]:
    low = (text or "").lower()
    return [w for w in words if re.search(rf"\b{re.escape(w)}\b", low)]


def adzuna_search(query: str, location: str = "", *, count: int = 20,
                  transport=None) -> list[dict]:
    """Return listings in PlacePilot's internal shape, or raise ProviderError."""
    app_id = os.environ.get("ADZUNA_APP_ID", "")
    app_key = os.environ.get("ADZUNA_APP_KEY", "")
    if not (app_id and app_key):
        raise ProviderError("Adzuna keys are not configured.")
    country = os.environ.get("ADZUNA_COUNTRY", "in")
    params = {"app_id": app_id, "app_key": app_key, "results_per_page": str(min(count, 50)),
              "what": query, "content-type": "application/json"}
    if location:
        params["where"] = location
    url = f"{ADZUNA_URL.format(country=country)}?{urllib.parse.urlencode(params)}"
    payload = (transport or http_json)(url)

    results = payload.get("results")
    if not isinstance(results, list):
        raise ProviderError("Adzuna returned no results array.")
    out = []
    for item in results[:count]:
        desc = item.get("description") or ""
        title = item.get("title") or "Role"
        company = (item.get("company") or {}).get("display_name") or "Unknown company"
        loc = (item.get("location") or {}).get("display_name") or location or "India"
        must = _first(desc, sorted(core.SKILLS))[:4] or ["communication"]
        nice = [s for s in _first(desc, sorted(core.SKILLS)) if s not in must][:3]
        # Adzuna gives contract_type=permanent|contract and contract_time=full_time|part_time
        contract_time = (item.get("contract_type") or "").lower()
        is_intern = "intern" in title.lower() or "intern" in desc.lower()[:200]
        salary_min = item.get("salary_min")
        out.append({
            "id": f"adz_{item.get('id')}",
            "source": "adzuna",
            "external_id": str(item.get("id")),
            "title": title,
            "company": company,
            "location": loc.split(",")[0].strip() or "India",
            "remote": int("remote" in f"{loc} {title}".lower()),
            "employment": "internship" if is_intern else (contract_time or "full-time"),
            "seniority": "intern" if is_intern else "entry",
            "stipend_month": int(round((salary_min or 0) / 12)) if salary_min else 0,
            "description": re.sub(r"<[^>]+>", " ", desc)[:1200].strip(),
            "url": item.get("redirect_url") or "",
            "apply_by": _parse_iso(item.get("created") or ""),
            "posted_at": (item.get("created") or "")[:10] or date.today().isoformat(),
            "required_json": json.dumps(must),
            "nice_json": json.dumps(nice),
            "tags_json": json.dumps(["adzuna", (item.get("category") or {}).get("tag", "")]),
        })
    return out


def merge_jobs(conn, query: str, location: str, count: int) -> tuple[list[dict], dict]:
    """Seed rows always available; Adzuna adds live ones when configured and reachable.

    Returns (jobs, meta). meta['source'] is what the trace/UI reports, and the fallback
    reason is surfaced rather than hidden.
    """
    seeded = [dict(r) for r in conn.execute("SELECT * FROM jobs WHERE source='mock'")]
    meta = {"source": "mock", "fallback": None, "live": 0}
    if jobs_mode() != "adzuna":
        if (os.environ.get("PLACEPILOT_JOBS") or "auto").lower() == "adzuna":
            meta["fallback"] = "adzuna_requested_but_keys_missing"
        return seeded, meta
    try:
        live = adzuna_search(query, location, count=count)
    except ProviderError as exc:
        meta["fallback"] = f"adzuna_unavailable: {exc}"[:200]
        return seeded, meta
    if not live:
        meta["fallback"] = "adzuna_returned_zero_results"
        return seeded, meta
    meta["source"] = "adzuna+mock"
    meta["live"] = len(live)
    return seeded + live, meta


# ------------------------------------------------------------------ llm

def llm_mode() -> str:
    """auto: whichever provider has a key, else off. Explicit values force one."""
    mode = (os.environ.get("PLACEPILOT_LLM") or "auto").lower()
    if mode == "off":
        return "off"
    if mode == "anthropic":
        return "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "off"
    if mode == "openrouter":
        return "openrouter" if os.environ.get("OPENROUTER_API_KEY") else "off"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENROUTER_API_KEY"):
        return "openrouter"
    return "off"


def llm_available() -> bool:
    return llm_mode() != "off"


SYSTEM = (
    "You are PlacePilot's planner. You have tools and must decide the next tool call. "
    "Never invent resume content: tailoring may use only facts returned by read_facts. "
    "You can never send an application; the send tool is always refused without human approval. "
    "Reply with a single JSON object and nothing else: "
    '{"tool": "<name>", "args": {…}} or {"done": true, "summary": "<one line>"}.'
)


def plan_step(history: list[dict], tools: list[dict], *, transport=None,
              model: str | None = None) -> dict:
    """One LLM planning turn -> {"tool","args"} or {"done":True,"summary"}.

    Routes to whichever provider is configured. Raises ProviderError on transport/shape
    failure so the caller can fall back to the deterministic planner mid-run.
    """
    provider = llm_mode()
    if provider == "anthropic":
        return _plan_anthropic(history, tools, transport=transport, model=model)
    if provider == "openrouter":
        return _plan_openrouter(history, tools, transport=transport, model=model)
    raise ProviderError("No LLM provider is configured.")


def _tool_schemas(tools: list[dict]) -> list[dict]:
    return [{"name": t["name"], "description": t["detail"],
             "input_schema": {"type": "object", "properties": t.get("properties", {}),
                              "additionalProperties": True}} for t in tools]


def _plan_anthropic(history: list[dict], tools: list[dict], *, transport=None,
                    model: str | None = None) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ProviderError("ANTHROPIC_API_KEY is not set.")
    body = {
        "model": model or os.environ.get("PLACEPILOT_MODEL", DEFAULT_MODEL),
        "max_tokens": 700,
        "system": SYSTEM,
        "messages": history[-12:],
        "tools": _tool_schemas(tools),
    }
    payload = (transport or http_json)(
        ANTHROPIC_URL, method="POST",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        body=body,
    )
    return parse_plan(payload)


def _plan_openrouter(history: list[dict], tools: list[dict], *, transport=None,
                     model: str | None = None) -> dict:
    """OpenRouter speaks the OpenAI chat-completions dialect, so the message list is
    flattened and tool calls come back in `choices[0].message.tool_calls`.

    Tries each model in `model_chain` in turn: free tiers return 429 often, and a dead
    model should not end the run.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise ProviderError("OPENROUTER_API_KEY is not set.")
    messages = [{"role": "system", "content": SYSTEM}]
    for turn in history[-12:]:
        role, content = turn.get("role", "user"), turn.get("content")
        if isinstance(content, str):
            messages.append({"role": role, "content": content})
        elif isinstance(content, list):
            text = " ".join(c.get("content", "") if isinstance(c, dict) else str(c) for c in content)
            messages.append({"role": role, "content": text[:4000]})

    last: Exception | None = None
    for candidate in model_chain(model):
        body = {
            "model": candidate,
            "max_tokens": 700,
            "messages": messages,
            "tools": [{"type": "function", "function": {
                "name": t["name"], "description": t["detail"],
                "parameters": {"type": "object", "properties": {}, "additionalProperties": True}}}
                for t in tools],
        }
        try:
            payload = (transport or http_json)(
                OPENROUTER_URL, method="POST",
                headers={"Authorization": f"Bearer {api_key}",
                         "HTTP-Referer": "http://127.0.0.1:3210", "X-Title": "PlacePilot"},
                body=body,
            )
            plan = parse_openrouter_plan(payload)
            remember_model(candidate)
            return plan
        except ProviderError as exc:
            last = exc
            continue
    raise ProviderError(f"Every free model failed; last error: {last}")


def parse_openrouter_plan(payload: dict) -> dict:
    try:
        message = payload["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError(f"OpenRouter response shape unexpected: {payload.get('error') or payload}") from exc
    calls = message.get("tool_calls") or []
    if calls:
        fn = calls[0].get("function") or {}
        name = fn.get("name")
        raw = fn.get("arguments") or "{}"
        try:
            args = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError as exc:
            raise ProviderError("OpenRouter tool arguments were not valid JSON.") from exc
        if not isinstance(args, dict):
            raise ProviderError("OpenRouter tool arguments were not an object.")
        return {"tool": name, "args": args}
    text = (message.get("content") or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        parsed = json.loads(text)
    except ValueError as exc:
        raise ProviderError("OpenRouter returned no tool call and no JSON plan.") from exc
    if isinstance(parsed, dict) and (parsed.get("done") or parsed.get("tool")):
        return parsed
    raise ProviderError("OpenRouter plan had neither done nor tool.")


def parse_plan(payload: dict) -> dict:
    """Accept either a tool_use block or the JSON-object convention. Validate hard."""
    blocks = payload.get("content")
    if not isinstance(blocks, list):
        raise ProviderError("LLM response had no content array.")
    for block in blocks:
        if block.get("type") == "tool_use":
            args = block.get("input")
            if not isinstance(args, dict):
                raise ProviderError("tool_use input was not an object.")
            return {"tool": block.get("name"), "args": args}
        if block.get("type") == "text":
            text = (block.get("text") or "").strip()
            text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
            try:
                parsed = json.loads(text)
            except ValueError:
                continue
            if isinstance(parsed, dict) and (parsed.get("done") or parsed.get("tool")):
                return parsed
    raise ProviderError("LLM response contained no usable plan.")
