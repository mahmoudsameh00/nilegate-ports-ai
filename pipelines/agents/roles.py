"""LLM per agent role (ADR-045) for the graphs (Agents plan §5b): main + fallback, structured output, usage records.

- Every call goes through `pipelines/agents/llm.py` (response cache, per-minute budget, daily quota, no library
  retries); this module only chooses **which** model answers.
- **Availability → fallback:** the main model is skipped when it is `Exhausted` (quota, stopped for the run, refused
  key), has no key in `.env`, or returns a cached deterministic failure; then the fallback (another provider) answers.
- **Validity → one retry, then stop** (§3 "Structured outputs"): a structured reply that does not validate is asked
  again once on the same model with the error; a second invalid reply raises `StructuredError` — an available model
  that writes invalid output is a result to report, not a reason to switch silently.
- **Usage:** each call returns its records (role, model, cached, tokens), which the graph keeps in its state — the
  Phase 5 token budget (P5-8) and the requests per pack are measured from them. Stateless otherwise, so a node that
  re-runs after a crash reads the same cached replies.
- `FakeRoles` has the same interface and answers from a script (the check script's evidence-based replies), so the
  graph runs on all 52 weeks without spending the free quota (P5-7).
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel

from pipelines.agents import llm
from pipelines.lib.common import load_env
from pipelines.lib.embeddings import est_tokens


@dataclass(frozen=True)
class Candidate:
    provider: str
    model: str
    method: str                     # structured-output method: the model's best T3 method (ADR-045)

    @property
    def name(self) -> str:
        return f"{self.provider}/{self.model}"


QWEN = Candidate("groq", "qwen/qwen3.8-27b", "function_calling")
FLASH_LITE = Candidate("gemini", "gemini-3.5-flash-lite", "function_calling")
GPT_OSS_20B = Candidate("groq", "openai/gpt-oss-20b", "json_schema")
NEMOTRON = Candidate("openrouter", "nvidia/nemotron-3.5-super-vl:free", "function_calling")

# ADR-045: Tools / routing = flash-lite + gpt-oss-20b (Groq). Writer / Insight was qwen (Groq) + flash-lite; the
# weekly pack's real prompts (9.7K–17K tokens, Phase 5 S6) do not fit Groq's 8K tokens per minute, so the pack's
# Insight / Writer run on flash-lite (250K TPM, tied with qwen in the bake-off) with OpenRouter nemotron (1M TPM,
# 50 requests / day) as the fallback from another provider (owner 2026-10-19, ADR-045 amendment 1). Amendment 2
# (2026-10-23, §5f F7): nemotron-3-super was retired upstream (404 on every request) → nemotron-3.5-super-vl, the
# only candidate that published a forced-fallback pack (1 / 2; dots-3-note-preview 0 / 2).
ROLES: dict[str, tuple[Candidate, ...]] = {
    "insight": (FLASH_LITE, NEMOTRON),
    "writer": (FLASH_LITE, NEMOTRON),
    "tools": (FLASH_LITE, GPT_OSS_20B),
}


class StructuredError(RuntimeError):
    """The model answered twice, and neither reply validated against the schema. `calls` = the usage records."""

    def __init__(self, message: str, calls: list[dict] | None = None):
        super().__init__(message)
        self.calls = calls or []


@dataclass
class RoleReply:
    message: AIMessage | None                  # invoke(): the reply (text and / or tool calls)
    parsed: BaseModel | None                   # structured(): the validated object
    model: str                                 # "<provider>/<model>" that answered
    calls: list[dict] = field(default_factory=list)


def _input_tokens(messages: list[BaseMessage], tools=None, schema: type[BaseModel] | None = None) -> int:
    n = sum(est_tokens(llm.message_text(m)) for m in messages)
    if tools:
        n += est_tokens(str([convert_to_openai_tool(t) for t in tools]))
    if schema:
        n += est_tokens(str(schema.model_json_schema()))
    return n


def _record(role: str, model: str, kind: str, reply: llm.Reply | None, est_in: int, outcome: str) -> dict:
    usage = (reply.usage if reply else None) or {}
    return {"role": role, "model": model, "kind": kind, "outcome": outcome,
            "cached": bool(reply and reply.cached), "est_input_tokens": est_in,
            "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "latency_ms": reply.latency_ms if reply else None}


def _retry_messages(messages: list[BaseMessage], why: str) -> list[BaseMessage]:
    # the invalid reply itself is not sent back: a tool call without its tool result is refused by some providers
    return [*messages, HumanMessage(f"Your previous answer did not match the required schema: {why[:400]}. "
                                    "Answer again, using exactly the schema's fields.")]


class Role:
    def __init__(self, name: str, candidates: tuple[Candidate, ...], quota: llm.QuotaState, cache_dir: Path):
        self.name = name
        self.candidates = candidates
        self._llms: dict[str, llm.LLM] = {}
        self.quota, self.cache_dir = quota, cache_dir

    def _llm(self, c: Candidate) -> llm.LLM:
        if c.name not in self._llms:
            self._llms[c.name] = llm.LLM(c.provider, c.model, cache_dir=self.cache_dir, quota=self.quota)
        return self._llms[c.name]

    def invoke(self, messages: list[BaseMessage], tools=None) -> RoleReply:
        """One chat turn (with tools bound, the reply may hold tool calls)."""
        calls, est_in = [], _input_tokens(messages, tools)
        for c in self.candidates:
            if not llm.has_key(c.provider):
                calls.append(_record(self.name, c.name, "chat", None, est_in, "no_key"))
                continue
            try:
                reply = self._llm(c).invoke(messages, tools=tools)
            except llm.Exhausted as exc:
                calls.append(_record(self.name, c.name, "chat", None, est_in, f"exhausted: {str(exc)[:120]}"))
                continue
            if not reply.ok:
                calls.append(_record(self.name, c.name, "chat", reply, est_in, f"failed: {reply.error['kind']}"))
                continue
            calls.append(_record(self.name, c.name, "chat", reply, est_in, "ok"))
            return RoleReply(reply.message, None, c.name, calls)
        raise llm.Exhausted(f"role {self.name}: no model available ({[r['outcome'] for r in calls]})")

    def structured(self, messages: list[BaseMessage], schema: type[BaseModel]) -> RoleReply:
        """A validated `schema` instance: the first available model, one retry with the error, then stop."""
        calls, est_in = [], _input_tokens(messages, schema=schema)
        for c in self.candidates:
            if not llm.has_key(c.provider):
                calls.append(_record(self.name, c.name, "structured", None, est_in, "no_key"))
                continue
            msgs = messages
            for attempt in range(2):
                try:
                    reply = self._llm(c).invoke(msgs, schema=schema, method=c.method)
                except llm.Exhausted as exc:
                    calls.append(_record(self.name, c.name, "structured", None, est_in,
                                         f"exhausted: {str(exc)[:120]}"))
                    break                                   # availability → the next candidate
                if not reply.ok:
                    calls.append(_record(self.name, c.name, "structured", reply, est_in,
                                         f"failed: {reply.error['kind']}"))
                    break
                obj, why = llm.parse_structured(reply, schema)
                if obj is not None:
                    calls.append(_record(self.name, c.name, "structured", reply, est_in, "ok"))
                    return RoleReply(reply.message, obj, c.name, calls)
                calls.append(_record(self.name, c.name, "structured", reply, est_in, f"invalid: {why[:120]}"))
                if attempt == 1:
                    raise StructuredError(f"role {self.name}, {c.name}: two invalid replies for "
                                          f"{schema.__name__} ({why[:200]})", calls)
                msgs = _retry_messages(messages, why)
        raise llm.Exhausted(f"role {self.name}: no model available ({[r['outcome'] for r in calls]})")


class Roles:
    """The real models of every role (one shared quota state, the llm.py cache)."""

    def __init__(self, cache_dir: Path = llm.CACHE_DIR, quota: llm.QuotaState | None = None):
        load_env()
        self.quota = quota or llm.QuotaState(cache_dir)
        self._roles = {name: Role(name, cands, self.quota, cache_dir) for name, cands in ROLES.items()}

    def get(self, name: str) -> Role:
        return self._roles[name]


# --- fake models for the checks -------------------------------------------------------------------------------------

Script = Callable[[str, list[BaseMessage], list | None, type[BaseModel] | None], AIMessage | BaseModel]


class FakeRole:
    """Same interface as `Role`; the reply comes from `script(role, messages, tools, schema)`: an AIMessage for
    `invoke`, a schema instance (or a dict to validate) for `structured`. A structured reply goes through the same
    parser as a real one (as a function call), so the graph code cannot tell the difference."""

    def __init__(self, name: str, script: Script, counter: dict):
        self.name, self.script, self.counter = name, script, counter

    def _count(self) -> int:
        self.counter[self.name] = self.counter.get(self.name, 0) + 1
        return self.counter[self.name]

    def invoke(self, messages: list[BaseMessage], tools=None) -> RoleReply:
        n = self._count()
        msg = self.script(self.name, messages, tools, None)
        if not isinstance(msg, AIMessage):
            raise TypeError(f"fake {self.name}: invoke() script must return an AIMessage, got {type(msg).__name__}")
        reply = llm.Reply(f"fake-{self.name}-{n}", msg, None, False, 0.0, None)
        return RoleReply(msg, None, f"fake/{self.name}",
                         [_record(self.name, f"fake/{self.name}", "chat", reply, _input_tokens(messages, tools), "ok")])

    def structured(self, messages: list[BaseMessage], schema: type[BaseModel]) -> RoleReply:
        n = self._count()
        out = self.script(self.name, messages, None, schema)
        args = out.model_dump(mode="json") if isinstance(out, BaseModel) else out
        msg = AIMessage(content="", tool_calls=[{"name": schema.__name__, "args": args, "id": f"fake-{n}"}])
        reply = llm.Reply(f"fake-{self.name}-{n}", msg, None, False, 0.0, None)
        obj, why = llm.parse_structured(reply, schema)
        est_in = _input_tokens(messages, schema=schema)
        if obj is None:
            raise StructuredError(f"fake {self.name}: script reply is not a valid {schema.__name__} ({why})",
                                  [_record(self.name, f"fake/{self.name}", "structured", reply, est_in, "invalid")])
        return RoleReply(msg, obj, f"fake/{self.name}",
                         [_record(self.name, f"fake/{self.name}", "structured", reply, est_in, "ok")])


class FakeRoles:
    def __init__(self, script: Script):
        self.script = script
        self.calls: dict[str, int] = {}             # calls per role in this process (the crash test reads it)
        self._roles = {name: FakeRole(name, script, self.calls) for name in ROLES}

    def get(self, name: str) -> FakeRole:
        return self._roles[name]
