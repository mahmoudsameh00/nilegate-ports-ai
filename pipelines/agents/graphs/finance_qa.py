"""The finance Q&A agent (Agents plan Phase 7, §5d P7-1; on LangChain `create_agent` since 2026-10-22, plan §5f F2 /
D-P7-6): one question from a NileGate employee → a checked answer.

`create_agent` on the `tools` role (ADR-045) through `RoleChatModel`, a chat-model adapter over `roles.py` — so the
llm.py cache, quota and fallback rules still hold for every call. The agent's tools are `STAGE1_TOOLS` (its tool node
hands the run context — the user and the dataset — to the tools, ADR-049); its answer is a `QaAnswer` returned as a
tool call (`ToolStrategy`); when the model answers in plain text instead, the adapter asks for the `QaAnswer` through
`roles.structured` (the same validated path as before, one retry). Middleware:
- `QaTurn.wrap_model_call` adds the answer brief (the question's language, the evidence ids so far, the slot rules)
  to every model request — not to the stored history — and removes the Stage 1 tools after `MAX_TOOL_ROUNDS`;
- `QaTurn.after_model` checks a returned answer in code (`check_answer`, also used by the evaluation harness: an
  unknown evidence id, a slot that does not resolve, a NileGate number typed as a literal, a refusal that holds a
  number, an "answered" when every structured tool refused access, a direction word against its value) → one patch
  (`jump_to` the model with the problems), then the status `validation_failed`;
- `ModelCallLimitMiddleware` caps the model calls of one question.
The answer writes every NileGate number as a slot (`deck/slots.py`): code fills it from the tool result kept in the
state, so a number is bound to its (result, row, field) by construction. Phase 12 grows this agent into the
Supervisor. Evidence ids: `insight.<tool_call_id>` (the pack's convention, so the slot syntax is the same).
"""
import re
from typing import Annotated, Any, Literal

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, AgentState, ModelCallLimitMiddleware, hook_config
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import ConfigDict, Field, ValidationError
from typing_extensions import NotRequired

from pipelines.agents import skill_loader
from pipelines.agents.deck import slots
from pipelines.agents.graphs import models as m
from pipelines.agents.graphs.weekly_pack import _cap_search, _evidence_id, _tool_evidence, _tool_rounds, evidence_index
from pipelines.agents.roles import StructuredError
from pipelines.agents.tools.context import RunContext
from pipelines.agents.tools.registry import STAGE1_TOOLS

MAX_TOOL_ROUNDS = 3                     # a question needs one or two calls; after three, only the answer tool is bound
MAX_PATCHES = 1
MAX_MODEL_CALLS = 8                     # 3 tool rounds + the answer + a patch, with room for an invalid answer
ANSWER_TOOL = m.QaAnswer.__name__       # the ToolStrategy tool's name
CALLS_KEY = "nilegate_calls"            # usage records on a reply's response_metadata (not in the llm.py cache key)
STOP_KEY = "nilegate_stop"              # a reply that stands for "two invalid QaAnswer objects" (output_invalid)
Status = Literal["running", "answered", "not_in_data", "not_permitted", "validation_failed", "output_invalid"]


def _append(a: list | None, b: list | None) -> list:
    return [*(a or []), *(b or [])]


class QaState(AgentState):
    """The agent's state: `messages` (+ `structured_response`) from `AgentState`, then the checked answer."""
    question: NotRequired[str]
    lang: NotRequired[str]              # "en" / "ar": the answer's language and the |dir words
    evidence: NotRequired[dict[str, dict]]
    calls: NotRequired[dict[str, dict]]  # evidence id → {"tool", "args"} (the harness matches elements on it)
    answer: NotRequired[dict]           # the last QaAnswer
    rendered: NotRequired[str]          # the answer with its slots filled
    bound: NotRequired[list[dict]]      # one per filled slot: evidence id, row label, field, value, text
    problems: NotRequired[list[str]]
    patches: NotRequired[int]
    normalized: NotRequired[Annotated[list[str], _append]]   # slot-form fixes made by code (D-P7-14)
    status: NotRequired[Status]
    stop_reason: NotRequired[str]
    llm_usage: NotRequired[Annotated[list[dict], _append]]


QA_TASK = """You answer one finance question from a NileGate employee. Call the tool that holds the answer (one or two
calls are enough), then return the QaAnswer. The user's identity and access are handled by the system; never ask for
them.

{skills}"""

ANSWER_TASK = """When the evidence holds what you need, return the QaAnswer (call the QaAnswer tool) for the question:
{question}
Status: answered only if the evidence holds what was asked; if it does not (another figure, related context only),
the status is not_in_data — say what is missing, without figures.
Language: {language}. Evidence you may cite (ids; use these ids only, never a tool name):
{ids}
{slot_rules}"""

PATCH_TASK = """Your answer had these problems (code checked it):
{problems}
Return the QaAnswer again with these fixed; keep what was right."""

SLOT_RULES = ("Every NileGate number is a slot: {<id>:<field>|<format>} for a one-row result, {<id>[<row key>]:<field>|"
              "<format>} for lists (row key = category, customer name or invoice number). Formats: money M / k / sdr, "
              "percent %1 / %2, days and counts none; |dir after a change field writes the direction. A slot writes "
              "its own unit and direction. Literal numbers only for the week, year, invoice numbers, dates, numbers "
              "in the question, and figures quoted from a document passage you cite.\n"
              # Phase 7 baseline (D-P7-10): slots were tried on document passages and with [row] on one-row results
              "A result with one row takes no [row]. Slots are only for finance_kpi, invoice_audit, compute_toll and "
              "suez_transits fields: a figure from a search_documents passage is quoted as text with its document "
              "(\"<the figure as the passage writes it> (<document title>)\"), never a slot.")

# literal numbers left in the answer (slots removed): the allowed ones are listed in the module docstring
NUMBER_RE = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
UP_WORDS = r"\b(up|rose|risen|increased?|grew|higher|above)\b|ارتفع|زاد|زادت|فوق"
DOWN_WORDS = r"\b(down|fell|fallen|decreased?|declined?|dropped|lower|below)\b|انخفض|قل|قلت|نزل|نزلت|تحت"


def _plain_numbers(text: str) -> list[str]:
    return [n.replace(",", "") for n in NUMBER_RE.findall(text.translate(ARABIC_DIGITS))]


def _strings(obj) -> list[str]:
    """Every text value of a tool result (nested rows, bands, citations): names and labels with digits in them."""
    if isinstance(obj, str):
        return [obj] if re.search(r"\d", obj) else []
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in _strings(v)]
    if isinstance(obj, list):
        return [s for v in obj for s in _strings(v)]
    return []


def _allowed_number(n: str, question: str, quoted: str) -> bool:
    q = _plain_numbers(question)
    if n in q or n in _plain_numbers(quoted):
        return True
    try:
        v = float(n)
    except ValueError:
        return False
    return (v.is_integer() and (1 <= v <= 53 or 2020 <= v <= 2030))   # week numbers, "13 weeks", "top 10", years


def check_answer(answer: dict, evidence: dict, question: str, lang: str = "en") -> tuple[str, list[dict], list[str]]:
    """(rendered text, bound slots, problems). The deterministic rules of this agent; the harness scores with it too."""
    problems = []
    text = answer["answer"]
    unknown = [e for e in answer.get("evidence_ids") or [] if e not in evidence]
    if unknown:
        problems.append(f"unknown evidence ids {unknown}: cite only ids from the evidence list")
    rendered, bound, errors = slots.render_text(text, evidence, lang)
    problems += [f"slot {e.raw}: {e.message}" for e in errors]
    # literal numbers: identifiers and dates first, then what is left must be allowed
    rest = re.sub(r"INV-\d+|\d{4}-\d{2}-\d{2}|\b20\d{2}-W\d{2}\b|SCNT", " ", slots.SLOT_RE.sub(" ", text))
    # a passage's title counts too ("x EUR 1,000" in a table title, D-P7-12)
    quoted = " ".join(f"{r.get('title', '')} {r.get('text', '')}" for e in answer.get("evidence_ids") or []
                      if e in evidence
                      and evidence[e].get("tool") in ("search_documents", "web_search")
                      for r in evidence[e].get("rows") or [])
    # digits inside a tool's own text values are names, not figures: "Liquefied Voyager 165", a band "first 5,000
    # tons", a citation's page 82 (c3, D-P7-15) — the deck Validator blanks them the same way (`validator._strings`)
    quoted += " " + " ".join(s for res in evidence.values() for s in _strings(res.get("rows") or []))
    typed = [n for n in _plain_numbers(rest) if not _allowed_number(n, question, quoted)]
    if typed:
        problems.append(f"numbers typed as text {typed[:5]}: write each NileGate number as a slot (or quote a cited "
                        "document)")
    status = answer["status"]
    if status != "answered" and (bound or typed):
        problems.append(f"status {status} must hold no number: say what is missing or not permitted, without figures")
    structured = [r for r in evidence.values() if r.get("tool") in slots.NUMERIC_TOOLS]
    if status == "answered" and structured and all(r.get("status") == "not_permitted" for r in structured):
        problems.append("every structured tool refused this user's access: the status is not_permitted")
    for b in bound:                                     # a direction word before a change value must agree (G1)
        if b.slot.direction or not slots.is_change(b.slot.field) or not b.value:
            continue
        before = text[max(0, b.slot.start - 40):b.slot.start].lower()
        up, down = re.search(UP_WORDS, before), re.search(DOWN_WORDS, before)
        if (up and not down and b.value < 0) or (down and not up and b.value > 0):
            problems.append(f"{b.slot.raw}: the direction word before it contradicts its sign; use |dir")
    out = [{"eid": b.slot.eid, "row": b.row, "row_label": (slots._row_label(evidence[b.slot.eid]["rows"][b.row],
                                                                             slots.row_keys(evidence[b.slot.eid]))
                                                          if b.row is not None else None),
            "field": b.slot.field, "value": b.value, "text": b.text} for b in bound]
    return rendered, out, problems


def _tool_name(t) -> str:
    return getattr(t, "name", None) or convert_to_openai_tool(t)["function"]["name"]


def _data_messages(messages: list) -> list:
    """The history without the answer tool's own call / result (they are not evidence)."""
    out = []
    for x in messages:
        if isinstance(x, ToolMessage) and x.name == ANSWER_TOOL:
            continue
        if isinstance(x, AIMessage) and any(c["name"] == ANSWER_TOOL for c in x.tool_calls):
            calls = [c for c in x.tool_calls if c["name"] != ANSWER_TOOL]
            x = x.model_copy(update={"tool_calls": calls})
        out.append(x)
    return out


def _calls(messages: list) -> dict[str, dict]:
    return {_evidence_id(c["id"]): {"tool": c["name"], "args": c["args"]}
            for x in _data_messages(messages) if isinstance(x, AIMessage) for c in x.tool_calls}


class RoleChatModel(BaseChatModel):
    """A LangChain chat model over one role of `roles.py` (`Roles` or `FakeRoles`): every call goes through the
    role's candidates (llm.py cache, quota, fallback). `bind_tools` keeps the tools; `tool_choice` is not sent (the
    role binds tools itself). When the answer tool is bound and the reply holds no tool call, the answer is asked
    for through `role.structured` (validated, one retry) and returned as a call of the answer tool."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    roles: Any
    role: str = "tools"
    bound: list = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "nilegate-role"

    def bind_tools(self, tools, **kwargs):  # noqa: ARG002 — tool_choice / parallel_tool_calls: decided by llm.py
        return self.model_copy(update={"bound": list(tools)})

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:  # noqa: ARG002
        role = self.roles.get(self.role)
        reply = role.invoke(messages, tools=self.bound or None)
        msg, calls = _cap_search(reply.message), list(reply.calls)
        if not msg.tool_calls and any(_tool_name(t) == ANSWER_TOOL for t in self.bound):
            try:
                s = role.structured(messages, m.QaAnswer)
            except StructuredError as exc:
                msg = AIMessage(content="", response_metadata={STOP_KEY: str(exc)[:400]})
                calls += exc.calls
            else:
                calls += s.calls
                msg = AIMessage(content="", tool_calls=[{"name": ANSWER_TOOL, "id": f"answer-{len(messages)}",
                                                         "args": s.parsed.model_dump(mode="json")}])
        msg = msg.model_copy(update={"response_metadata": {**msg.response_metadata, CALLS_KEY: calls}})
        return ChatResult(generations=[ChatGeneration(message=msg)])


class QaTurn(AgentMiddleware):
    """The answer brief on every model request, the tool-round cap, and the code check of a returned answer."""

    state_schema = QaState

    def wrap_model_call(self, request, handler):
        st = request.state
        msgs = _data_messages(request.messages)
        evidence = _tool_evidence(msgs)
        brief = HumanMessage(ANSWER_TASK.format(
            question=st.get("question", ""), language="Egyptian Arabic" if st.get("lang") == "ar" else "English",
            ids=evidence_index(evidence, msgs) or "(none yet: call the tool that holds the answer)",
            slot_rules=SLOT_RULES))
        tools = request.tools if _tool_rounds(msgs) < MAX_TOOL_ROUNDS else []
        return handler(request.override(messages=[*request.messages, brief], tools=tools))

    @hook_config(can_jump_to=["model", "end"])
    def after_model(self, state, runtime) -> dict | None:  # noqa: ARG002
        # with ToolStrategy the model node may add the answer tool's result after the reply: find the reply
        last = next(x for x in reversed(state["messages"]) if isinstance(x, AIMessage))
        out = {"llm_usage": [{"node": "qa_agent", **c} for c in last.response_metadata.get(CALLS_KEY, [])],
               "calls": _calls(state["messages"]), "status": "running"}
        if last.response_metadata.get(STOP_KEY):
            return {**out, "status": "output_invalid", "stop_reason": f"qa_answer: {last.response_metadata[STOP_KEY]}",
                    "jump_to": "end"}
        call = next((c for c in last.tool_calls if c["name"] == ANSWER_TOOL), None)
        if call is None:
            return out                                   # tool calls → the tool node; else the agent's own routing
        try:
            answer = m.QaAnswer.model_validate(call["args"]).model_dump(mode="json")
        except ValidationError:
            return out                     # ToolStrategy sends the error back to the model (within the call limit)
        evidence = _tool_evidence(_data_messages(state["messages"]))
        answer["answer"], fixed = slots.normalize_text(answer["answer"], evidence)   # slot form only (D-P7-14)
        rendered, bound, problems = check_answer(answer, evidence, state.get("question", ""), state.get("lang", "en"))
        out |= {"answer": answer, "evidence": evidence, "normalized": fixed, "rendered": rendered, "bound": bound,
                "problems": problems}
        patches = state.get("patches", 0)
        if problems and patches < MAX_PATCHES:
            # a tool call needs its result before the next turn (added unless ToolStrategy already did), then the
            # problems → the model again
            answered = any(isinstance(x, ToolMessage) and x.tool_call_id == call["id"] for x in state["messages"])
            result = [] if answered else [ToolMessage("Checked by code: not accepted.", tool_call_id=call["id"],
                                                      name=ANSWER_TOOL)]
            return {**out, "patches": patches + 1, "jump_to": "model",
                    "messages": [*result,
                                 HumanMessage(PATCH_TASK.format(problems="\n".join(f"- {p}" for p in problems)))]}
        return {**out, "status": "validation_failed" if problems else answer["status"]}


def build_graph(roles, checkpointer=None):
    """The compiled Q&A agent. Invoke with {"messages", "question", "lang"} and `context=RunContext(user, dataset)`
    (`ask` does it)."""
    skills = "\n\n".join(skill_loader.load(s) for s in ("finance-qa", "untrusted-content"))
    return create_agent(RoleChatModel(roles=roles), STAGE1_TOOLS, system_prompt=QA_TASK.format(skills=skills),
                        # an invalid QaAnswer call goes back to the model with the error (counted by the call limit)
                        response_format=ToolStrategy(m.QaAnswer, handle_errors=True),
                        middleware=[QaTurn(), ModelCallLimitMiddleware(run_limit=MAX_MODEL_CALLS, exit_behavior="end")],
                        context_schema=RunContext, checkpointer=checkpointer, name="finance_qa")


def ask(graph, question: str, user, lang: str = "en", dataset: str = "live", thread: str = "qa") -> dict:
    """One question end to end → the final state (plain data). A run that ends without a checked answer (the call
    limit) is `output_invalid`."""
    cfg = {"configurable": {"thread_id": thread}}
    st = graph.invoke({"messages": [HumanMessage(question)], "question": question, "lang": lang}, cfg,
                      context=RunContext(user, dataset))
    if st.get("status") in (None, "running"):
        st = {**st, "status": "output_invalid", "stop_reason": st.get("stop_reason") or "no checked answer"}
    return st
