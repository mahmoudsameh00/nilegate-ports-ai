"""LLM provider smoke test (Agents plan Phase 0): each key present -> live model list + one tool-calling request.

Plan:    docs/plans/Agents_plan.md, Phase 0 and §7a (before the bake-off: prove each key, the model ids and tool calling).
Run:     uv run python tools/run.py pipelines/scripts/agents/LLM_smoke_test.py  (from the project root)

Reads:   .env (GEMINI_API_KEY, GROQ_API_KEY, OPENROUTER_API_KEY; a missing key = that provider is skipped, reported);
         the network (model lists cost no generation quota)
Writes:  Data/processed/agents/eval/llm_cache/ (git-ignored): the cached replies + usage.json / quota_state.json
Re-run:  safe; replies come from the cache (0 generation calls after the first run). Not part of `tools/run.py all`.

Data:    the prompt is a public arithmetic question (data_origin "public", ADR-037 amendment).

Checks per provider
1. live model list: how many models, which §7a candidates are served (a vanished one is reported, not called);
2. tool calling: the first served candidate (the next one if it refuses tools) must call `add` with a = 17.5,
   b = 24.25 — the request only, the tool is not executed;
3. OpenRouter only: the key's tier (is_free_tier = no credits bought: 50 free requests / day).
"""
import sys
from pathlib import Path

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from pipelines.agents import llm  # noqa: E402
from pipelines.lib import common  # noqa: E402

common.load_env(ROOT)


@tool
def add(a: float, b: float) -> float:
    """Add two numbers and return the sum.

    Args:
        a: the first number
        b: the second number
    """
    return a + b


MESSAGES = [SystemMessage("You are a calculator assistant. Always use the add tool for additions; never add in your "
                          "head."),
            HumanMessage("What is 17.5 + 24.25?")]
MODELS: list[llm.LLM] = []   # every model touched this run (call / cache-hit counters)


def tool_call_ok(reply: llm.Reply) -> tuple[bool, str]:
    if not reply.ok:
        return False, f"error {reply.error['kind']}: {reply.error['text'][:160]}"
    calls = reply.message.tool_calls
    if not calls:
        return False, f"no tool call; text: {llm.message_text(reply.message)[:120]!r}"
    c = calls[0]
    args = {k: float(v) for k, v in c["args"].items()}
    ok = c["name"] == "add" and sorted(args.values()) == [17.5, 24.25]
    return ok, f"{c['name']}({c['args']})"


def check_provider(provider: str, client: httpx.Client, quota: llm.QuotaState) -> dict:
    served = llm.available_models(provider, client)
    cands = llm.PROVIDERS[provider]["candidates"]
    present = [m for m in cands if m in served]
    missing = [m for m in cands if m not in served]
    print(f"{provider}: {len(served)} models served; candidates present {present}; missing {missing}")
    out = {"served": len(served), "present": present, "missing": missing, "passed": None, "tried": []}
    if provider == "openrouter":
        out["key_info"] = llm.openrouter_key_info(client)
        print(f"   key: {out['key_info']}")
    for model in present:
        m = llm.LLM(provider, model, quota=quota)
        MODELS.append(m)
        try:
            reply = m.invoke(MESSAGES, data_origin="public", tools=[add])
        except llm.Exhausted as e:
            print(f"   {model}: not called — {e}")
            out["tried"].append((model, "exhausted"))
            continue
        ok, what = tool_call_ok(reply)
        src = "cache" if reply.cached else f"{reply.latency_ms:.0f} ms"
        print(f"   {model}: {'tool call OK' if ok else 'FAILED'} — {what} ({src}; usage {reply.usage})")
        out["tried"].append((model, "ok" if ok else "failed"))
        if ok:
            out["passed"] = model
            break
    return out


def main() -> None:
    quota = llm.QuotaState()
    results, skipped = {}, []
    with httpx.Client(timeout=30.0) as client:
        for provider in llm.PROVIDERS:
            if not llm.has_key(provider):
                skipped.append(provider)
                print(f"{provider}: skipped — {llm.PROVIDERS[provider]['key']} is not in .env")
                continue
            try:
                results[provider] = check_provider(provider, client, quota)
            except Exception as e:  # noqa: BLE001 — one provider's failure must not hide the others
                print(f"{provider}: FAILED — {common.redact(f'{type(e).__name__}: {e}')[:300]}")
                results[provider] = {"passed": None, "error": True}

    for provider, r in results.items():
        if r.get("passed"):
            print(f"✅ {provider}: key works, tool calling OK with {r['passed']}")
    print(f"generation calls this run: {sum(m.calls for m in MODELS)}; cache hits: {sum(m.hits for m in MODELS)}")
    used = {p: {k: v for k, v in quota.usage.get(llm.provider_day(p), {}).items() if k.split("/")[0] == p}
            for p in results}
    print(f"requests sent today (provider day): {used}")
    failed = [p for p, r in results.items() if not r.get("passed")]
    assert not failed, f"providers with a key that did not pass: {failed}"
    assert results, "no provider key in .env"
    print(f"✅ Smoke test passed: {sorted(results)} OK; skipped (no key): {skipped or 'none'}")


if __name__ == "__main__":
    main()
