"""LLM access for the agents (Agents plan Phase 0, §7a): provider registry, model factory, rate budget, response cache.

- Providers: free APIs only (D1) — Google AI Studio, Groq, OpenRouter (its OpenAI-compatible endpoint). The models are
  the LangChain chat classes the agents will use, with temperature 0 and **max_retries=0**: retries are decided here,
  never inside the client library.
- Data policy (ADR-037 amendment): every call states its `data_origin`; free tiers accept only "public" or
  "synthetic" (minimized: aggregates, not rows; no employee names). Anything else is refused before any request.
- Response cache: key = SHA-256 of everything sent (provider, model, parameters, messages, tool schemas, structured
  output schema + method). One append-only JSONL per model under Data/processed/agents/eval/llm_cache/ (git-ignored);
  a re-run makes 0 calls. Deterministic failures (bad request, unknown model) are cached too; quota, rate-limit,
  network and auth failures are not.
- Quota rules (fixed before any run): a local per-minute Budget (requests + tokens); a persisted daily request count
  per provider day that refuses a call once the provider's daily limit is reached (OpenRouter: 50 / day across all
  free models; Groq: 1,000 / day per model); a daily-quota 429 marks the model exhausted until the provider's day
  ends (no retry loop); a per-minute 429 or a transient error gets one wait (<= MAX_RATE_WAIT_S) and one retry, then
  the model stops for this run.
- Secrets: keys go only into the client objects or request headers, never into a URL, a cache key or a log line;
  every error text passes through `redact()`.
"""
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from langchain_core.messages import AIMessage, BaseMessage, message_to_dict, messages_from_dict
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel

from pipelines.lib.common import project_root, redact
from pipelines.lib.embeddings import Budget, est_tokens

EVAL_DIR = project_root() / "Data" / "processed" / "agents" / "eval"
CACHE_DIR = EVAL_DIR / "llm_cache"                  # git-ignored
FREE_TIER_DATA = {"public", "synthetic"}            # ADR-037 amendment: what a free tier may receive
TIMEOUT_S = 120
MAX_RATE_WAIT_S = 60                                # longest single wait on a per-minute limit
OUTPUT_RESERVE_TOKENS = 1_500                       # counted against the token budget before the reply is known

# Limits verified 2026-10-09 (Agents plan §7a). Gemini's free limits are shown only in AI Studio: conservative local
# values, the provider's 429 decides. `scope` = what a limit is shared by: one model, or every model of the provider.
PROVIDERS = {
    "gemini": {"key": "GEMINI_API_KEY", "rpm": 10, "tpm": 250_000, "rpd": None, "scope": "model",
               "day_tz": "America/Los_Angeles",
               "candidates": ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemma-4-31b-it"]},
    "groq": {"key": "GROQ_API_KEY", "rpm": 30, "tpm": 8_000, "rpd": 1_000, "scope": "model", "day_tz": "UTC",
             "candidates": ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]},
    "openrouter": {"key": "OPENROUTER_API_KEY", "rpm": 20, "tpm": 1_000_000, "rpd": 50, "scope": "provider",
                   "day_tz": "UTC", "base_url": "https://openrouter.ai/api/v1",
                   "candidates": ["nvidia/nemotron-3-super-120b-a12b:free", "thinkingmachines/inkling:free",
                                  "poolside/laguna-s-2.1:free"]},
}


class Exhausted(RuntimeError):
    """The model cannot be called now: daily quota reached, stopped for this run, or the key was refused."""


def has_key(provider: str) -> bool:
    return bool(os.environ.get(PROVIDERS[provider]["key"]))


def provider_day(provider: str) -> str:
    """The provider's current quota day (Gemini resets at midnight Pacific time, the others at midnight UTC)."""
    return datetime.now(ZoneInfo(PROVIDERS[provider]["day_tz"])).date().isoformat()


def slug(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", model)


# --- live model lists (no generation quota is spent) ---------------------------------------------------------------

def available_models(provider: str, client: httpx.Client) -> set[str]:
    """Model ids the provider serves right now (a vanished candidate is skipped and reported by the caller)."""
    key = os.environ[PROVIDERS[provider]["key"]]
    if provider == "gemini":
        out, token = set(), None
        while True:
            r = client.get("https://generativelanguage.googleapis.com/v1beta/models",
                           headers={"x-goog-api-key": key}, params={"pageSize": 1000, **({"pageToken": token} if token else {})})
            _raise_for(provider, r)
            js = r.json()
            out |= {m["name"].removeprefix("models/") for m in js.get("models", [])
                    if "generateContent" in m.get("supportedGenerationMethods", [])}
            token = js.get("nextPageToken")
            if not token:
                return out
    url = {"groq": "https://api.groq.com/openai/v1/models",
           "openrouter": "https://openrouter.ai/api/v1/models"}[provider]
    r = client.get(url, headers={"Authorization": f"Bearer {key}"})
    _raise_for(provider, r)
    return {m["id"] for m in r.json()["data"]}


def openrouter_key_info(client: httpx.Client) -> dict:
    """OpenRouter's view of the key: is_free_tier (no credits bought: 50 free requests / day), usage, limit."""
    r = client.get("https://openrouter.ai/api/v1/key",
                   headers={"Authorization": f"Bearer {os.environ[PROVIDERS['openrouter']['key']]}"})
    _raise_for("openrouter", r)
    d = r.json().get("data", {})
    return {k: d.get(k) for k in ("is_free_tier", "usage", "limit", "limit_remaining")}


def _raise_for(provider: str, r: httpx.Response) -> None:
    if r.status_code != 200:
        raise RuntimeError(redact(f"{provider} HTTP {r.status_code}: {' '.join(r.text.split())[:300]}"))


# --- model factory ----------------------------------------------------------------------------------------------------

def chat_model(provider: str, model: str, **params):
    """The LangChain chat model for one candidate: temperature 0, no library retries, a request timeout."""
    p = PROVIDERS[provider]
    key = os.environ[p["key"]]
    common = {"temperature": 0, "max_retries": 0, "timeout": TIMEOUT_S, **params}
    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=model, google_api_key=key, **common)
    if provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(model=model, api_key=key, **common)
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model=model, api_key=key, base_url=p["base_url"], **common)


# --- error classification -------------------------------------------------------------------------------------------

DAY_RE = re.compile(r"per.?day|PerDay|\bRPD\b|\bTPD\b|daily|free-models-per-day", re.I)


def _chain(exc: BaseException) -> list[BaseException]:
    out, seen = [], set()
    while exc is not None and id(exc) not in seen:
        out.append(exc)
        seen.add(id(exc))
        exc = exc.__cause__ or exc.__context__
    return out


def classify(exc: BaseException) -> tuple[str, float | None]:
    """(kind, provider-requested wait in seconds). Kinds: quota_day, rate_minute, auth, model_missing, bad_request,
    transient, unknown. Looks through the whole exception chain (LangChain wraps the provider SDK errors)."""
    chain = _chain(exc)
    text = " ".join(f"{type(e).__name__}: {e}" for e in chain)
    status = None
    wait = None
    for e in chain:
        for attr in ("status_code", "code", "status"):
            v = getattr(e, attr, None)
            if isinstance(v, int) and 100 <= v < 600:
                status = status or v
        resp = getattr(e, "response", None)
        ra = getattr(getattr(resp, "headers", None), "get", lambda *_: None)("retry-after")
        if ra and wait is None:
            try:
                wait = float(ra)
            except ValueError:
                pass
    m = re.search(r"retryDelay['\"]?:\s*['\"]?(\d+(?:\.\d+)?)s", text)   # Gemini puts the wait in the body
    if m and wait is None:
        wait = float(m.group(1))
    if status is None:
        m = re.search(r"\b(4\d\d|5\d\d)\b", text)
        status = int(m.group(1)) if m and re.search(r"(?i)error|status|code", text) else None
    names = " ".join(type(e).__name__ for e in chain)
    if status == 429 or "RateLimit" in names or "RESOURCE_EXHAUSTED" in text:
        return ("quota_day" if DAY_RE.search(text) else "rate_minute"), wait
    if status in (401, 403) or "Authentication" in names or "PermissionDenied" in names:
        return "auth", None
    if status == 404 or "NotFound" in names:
        return "model_missing", None
    if status in (400, 422) or "InvalidRequest" in names or "BadRequest" in names:
        return "bad_request", None
    if (status and status >= 500) or re.search(r"Timeout|Connect|ServerError|APIConnection|RemoteProtocol", names):
        return "transient", wait
    return "unknown", None


# --- persisted quota state (shared by every model of the run) -------------------------------------------------------

class QuotaState:
    """Daily request counts and exhausted models, persisted so the rules hold across runs and days."""

    def __init__(self, folder: Path = CACHE_DIR):
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)
        self.usage_file, self.state_file = folder / "usage.json", folder / "quota_state.json"
        self.usage = json.loads(self.usage_file.read_text(encoding="utf-8")) if self.usage_file.exists() else {}
        self.state = json.loads(self.state_file.read_text(encoding="utf-8")) if self.state_file.exists() else {}

    @staticmethod
    def scope(provider: str, model: str) -> str:
        return provider if PROVIDERS[provider]["scope"] == "provider" else f"{provider}/{model}"

    def count(self, provider: str, model: str) -> int:
        return self.usage.get(provider_day(provider), {}).get(self.scope(provider, model), 0)

    def check(self, provider: str, model: str) -> None:
        name, day = f"{provider}/{model}", provider_day(provider)
        if self.state.get(name, {}).get("day") == day:
            raise Exhausted(f"{name}: daily quota exhausted on {day} ({self.state[name]['why'][:120]})")
        rpd = PROVIDERS[provider]["rpd"]
        if rpd is not None and self.count(provider, model) >= rpd:
            raise Exhausted(f"{self.scope(provider, model)}: {rpd} requests already sent on {day} (daily limit)")

    def record(self, provider: str, model: str) -> None:
        day = self.usage.setdefault(provider_day(provider), {})
        day[self.scope(provider, model)] = day.get(self.scope(provider, model), 0) + 1
        self._save(self.usage_file, self.usage)

    def exhaust(self, provider: str, model: str, why: str) -> None:
        m = re.search(r"limit:\s*(\d+)", why)          # Gemini names the free daily limit in its 429 text
        self.state[f"{provider}/{model}"] = {"day": provider_day(provider), "why": why,
                                             "limit": int(m.group(1)) if m else None,
                                             "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self._save(self.state_file, self.state)

    def daily_limit(self, provider: str, model: str) -> tuple[int | None, int]:
        """(known daily request limit, most requests seen in one provider day): the registry value, else the limit a
        daily-quota 429 named; the second value is a lower bound when no limit is known."""
        st = self.state.get(f"{provider}/{model}", {})
        m = re.search(r"limit:\s*(\d+)", st.get("why", ""))
        known = PROVIDERS[provider]["rpd"] or st.get("limit") or (int(m.group(1)) if m else None)
        seen = max((d.get(self.scope(provider, model), 0) for d in self.usage.values()), default=0)
        return known, seen

    @staticmethod
    def _save(path: Path, obj: dict) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, indent=1, sort_keys=True), encoding="utf-8", newline="\n")
        tmp.replace(path)


# --- the cached model -----------------------------------------------------------------------------------------------

@dataclass
class Reply:
    key: str
    message: AIMessage | None
    error: dict | None                  # {"kind", "text"} for a cached deterministic failure
    cached: bool
    latency_ms: float | None
    usage: dict | None

    @property
    def ok(self) -> bool:
        return self.message is not None


_BUDGETS: dict[str, Budget] = {}


def message_text(m: BaseMessage) -> str:
    return str(m.text)   # langchain-core 1.x: a property (calling it is deprecated); the text blocks only


def canonical(m: BaseMessage) -> dict:
    """What identifies a message in a cache key. A model reply is reduced to its text and tool calls (name + args):
    ids, metadata and provider extras (e.g. Gemini thought signatures, still sent to the provider) can differ after
    a cache round trip and must not change the key of the next turn; a tool result keeps its text and tool name."""
    if isinstance(m, AIMessage):
        return {"type": "ai", "text": message_text(m),
                "tool_calls": [{"name": c["name"], "args": c["args"]} for c in m.tool_calls]}
    if m.type == "tool":
        return {"type": "tool", "name": getattr(m, "name", None), "text": message_text(m)}
    return {"type": m.type, "text": message_text(m)}


class LLM:
    """One candidate model behind the response cache and the quota rules."""

    def __init__(self, provider: str, model: str, params: dict | None = None, cache_dir: Path = CACHE_DIR,
                 quota: QuotaState | None = None):
        self.provider, self.model, self.params = provider, model, params or {}
        self.name = f"{provider}/{model}"
        self.cache_file = cache_dir / provider / f"{slug(model)}.jsonl"
        self.cache: dict[str, dict] = {}
        if self.cache_file.exists():
            for line in self.cache_file.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self.cache[rec["key"]] = rec
        self.quota = quota or QuotaState(cache_dir)
        scope = QuotaState.scope(provider, model)
        p = PROVIDERS[provider]
        self.budget = _BUDGETS.setdefault(scope, Budget(p["rpm"], p["tpm"]))
        self.stopped: str | None = None
        self.calls = self.hits = 0
        self._chat = None

    def key(self, messages: list[BaseMessage], tools=None, schema: type[BaseModel] | None = None,
            method: str | None = None) -> str:
        payload = {"provider": self.provider, "model": self.model, "params": self.params,
                   "messages": [canonical(m) for m in messages],
                   "tools": [convert_to_openai_tool(t) for t in tools or []],
                   "schema": schema.model_json_schema() if schema else None, "method": method}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
                              .encode("utf-8")).hexdigest()

    def invoke(self, messages: list[BaseMessage], *, data_origin: str, tools=None,
               schema: type[BaseModel] | None = None, method: str | None = None) -> Reply:
        """One request (or its cached reply). With `schema`, the raw AIMessage is returned and cached; parse it with
        `parse_structured` (the same parser for fresh and cached replies)."""
        if data_origin not in FREE_TIER_DATA:
            raise ValueError(f"{self.name} is a free tier: data_origin {data_origin!r} refused (ADR-037 amendment; "
                             f"allowed: {sorted(FREE_TIER_DATA)})")
        assert not (tools and schema), "tools and a structured-output schema are separate requests"
        key = self.key(messages, tools, schema, method)
        if key in self.cache:
            self.hits += 1
            return self._reply(self.cache[key], cached=True)
        if self.stopped:
            raise Exhausted(f"{self.name}: stopped for this run ({self.stopped})")
        self.quota.check(self.provider, self.model)

        if self._chat is None:
            self._chat = chat_model(self.provider, self.model, **self.params)
        runnable = self._chat
        if tools:
            runnable = runnable.bind_tools(tools)
        if schema:
            runnable = runnable.with_structured_output(schema, method=method, include_raw=True)
        est = sum(est_tokens(message_text(m)) for m in messages) + OUTPUT_RESERVE_TOKENS
        if tools:
            est += est_tokens(json.dumps([convert_to_openai_tool(t) for t in tools]))
        est = min(est, self.budget.tpm)  # a larger estimate would wait forever; the provider decides

        for attempt in range(2):
            self.budget.wait(est)
            t0 = time.perf_counter()
            try:
                out = runnable.invoke(messages)
            except Exception as e:  # noqa: BLE001 — classified below, never swallowed silently
                self.budget.record(est)
                self.quota.record(self.provider, self.model)
                kind, wait = classify(e)
                text = redact(" | ".join(f"{type(x).__name__}: {x}" for x in _chain(e)))[:600]
                if kind == "quota_day":
                    self.quota.exhaust(self.provider, self.model, text)
                    raise Exhausted(f"{self.name}: daily quota exhausted — stopped until the provider's day ends "
                                    f"({text[:200]})") from None
                if kind in ("rate_minute", "transient") and attempt == 0 and (wait or 0) <= MAX_RATE_WAIT_S:
                    # a per-minute limit clears with a full window (Groq's output-tokens-per-minute limit came back
                    # after a 20 s wait); a transient server error gets a short wait
                    pause = max(wait or 0.0, MAX_RATE_WAIT_S) if kind == "rate_minute" else (wait or 20.0)
                    print(f"   {self.name}: {kind}, one retry in {pause:.0f} s ({text[:160]})", flush=True)
                    time.sleep(pause)
                    continue
                if kind in ("bad_request", "model_missing"):
                    return self._store(key, None, {"kind": kind, "text": text}, None)
                self.stopped = f"{kind}: {text[:200]}"
                raise Exhausted(f"{self.name}: {self.stopped}") from None
            ms = (time.perf_counter() - t0) * 1000
            msg = out["raw"] if schema else out
            usage = dict(msg.usage_metadata) if getattr(msg, "usage_metadata", None) else None
            self.budget.record((usage or {}).get("total_tokens", est))
            self.quota.record(self.provider, self.model)
            self.calls += 1
            return self._store(key, msg, None, ms, usage)
        raise AssertionError("unreachable")

    def _store(self, key: str, msg: AIMessage | None, error: dict | None, ms: float | None,
               usage: dict | None = None) -> Reply:
        rec = {"key": key, "model": self.name, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "latency_ms": round(ms, 1) if ms is not None else None, "usage": usage,
               "message": message_to_dict(msg) if msg is not None else None, "error": error}
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        with self.cache_file.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        self.cache[key] = json.loads(json.dumps(rec, default=str))
        return self._reply(self.cache[key], cached=False)

    @staticmethod
    def _reply(rec: dict, cached: bool) -> Reply:
        msg = messages_from_dict([rec["message"]])[0] if rec.get("message") else None
        return Reply(rec["key"], msg, rec.get("error"), cached, rec.get("latency_ms"), rec.get("usage"))


def parse_structured(reply: Reply, schema: type[BaseModel]) -> tuple[BaseModel | None, str | None]:
    """The reply as a validated `schema` instance, or the reason it is not one. Tool-call arguments when the model
    answered with a tool call (function_calling), else the text as JSON (json_schema / json_mode; code fences
    tolerated)."""
    if not reply.ok:
        return None, f"no reply: {reply.error}"
    m = reply.message
    try:
        if m.tool_calls:
            data = m.tool_calls[0]["args"]
        else:
            text = message_text(m).strip()
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
            data = json.loads(text)
        return schema.model_validate(data), None
    except Exception as e:  # noqa: BLE001 — the reason is the measurement
        return None, f"{type(e).__name__}: {str(e)[:300]}"
