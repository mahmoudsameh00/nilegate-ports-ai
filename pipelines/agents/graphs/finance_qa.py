"""The finance Q&A agent (Agents plan Phase 7, §5d P7-1): one question from a NileGate employee → a checked answer.

A small LangGraph agent on the `tools` role (ADR-045: flash-lite + gpt-oss-20b): `qa_llm` ⇄ `qa_tools`
(`ToolNode(STAGE1_TOOLS)`, which hands the run context — the user and the dataset — to the tools, ADR-049), then
`qa_answer` (one structured `QaAnswer`) and `qa_check` (code). The answer writes every NileGate number as a slot
(`deck/slots.py`, the deck's syntax): code fills it from the tool result kept in the state, so a number is bound to
its (result, row, field) by construction. `check_answer` (also used by the evaluation harness) refuses: an unknown
evidence id, a slot that does not resolve, a NileGate number typed as a literal, a refusal that holds a number, an
"answered" when every structured tool refused access, a direction word that contradicts its value. One patch, then
the status `validation_failed`. Phase 12 grows this agent into the Supervisor.

Evidence ids: `insight.<tool_call_id>` (the pack's convention, so the slot syntax is the same).
"""
import operator
import re
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from pipelines.agents import skill_loader
from pipelines.agents.deck import slots
from pipelines.agents.graphs import models as m
from pipelines.agents.graphs.weekly_pack import (_cap_search, _tool_evidence, _tool_rounds, _usage, after_agent_step,
                                                 _stop, evidence_index, _evidence_id)
from pipelines.agents.roles import StructuredError
from pipelines.agents.tools.context import RunContext
from pipelines.agents.tools.registry import STAGE1_TOOLS

MAX_TOOL_ROUNDS = 3                     # a question needs one or two calls; the last round has no tools bound
MAX_PATCHES = 1
Status = Literal["running", "answered", "not_in_data", "not_permitted", "validation_failed", "output_invalid"]


class QaState(TypedDict, total=False):
    question: str
    lang: str                           # "en" / "ar": the answer's language and the |dir words
    messages: Annotated[list[AnyMessage], add_messages]
    evidence: dict[str, dict]
    calls: dict[str, dict]              # evidence id → {"tool", "args"} (the harness matches elements on it)
    answer: dict                        # the last QaAnswer
    rendered: str                       # the answer with its slots filled
    bound: list[dict]                   # one per filled slot: evidence id, row label, field, value, text
    problems: list[str]
    patches: int
    status: Status
    stop_reason: str
    llm_usage: Annotated[list[dict], operator.add]


QA_TASK = """You answer one finance question from a NileGate employee. Call the tool that holds the answer (one or two
calls are enough), then stop calling tools and say in one line what you found. The user's identity and access are
handled by the system; never ask for them.

{skills}"""

ANSWER_TASK = """Now return the QaAnswer for the question: {question}
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


def _calls(messages: list) -> dict[str, dict]:
    return {_evidence_id(c["id"]): {"tool": c["name"], "args": c["args"]}
            for x in messages if isinstance(x, AIMessage) for c in x.tool_calls}


def make_qa_llm(roles):
    def qa_llm(state: QaState) -> dict:
        msgs = list(state.get("messages") or [])
        new = []
        if not msgs:
            skills = "\n\n".join(skill_loader.load(s) for s in ("finance-qa", "untrusted-content"))
            new = [SystemMessage(QA_TASK.format(skills=skills)), HumanMessage(state["question"])]
            msgs = new
        tools = STAGE1_TOOLS if _tool_rounds(msgs) < MAX_TOOL_ROUNDS else None
        reply = roles.get("tools").invoke(msgs, tools=tools)
        return {"messages": [*new, _cap_search(reply.message)], "llm_usage": _usage("qa_llm", reply),
                "status": "running"}
    return qa_llm


def after_qa_llm(state: QaState) -> str:
    last = state["messages"][-1]
    return "qa_tools" if isinstance(last, AIMessage) and last.tool_calls else "qa_answer"


def make_qa_answer(roles):
    def qa_answer(state: QaState) -> dict:
        evidence = _tool_evidence(state["messages"])
        lang = state.get("lang", "en")
        ask = [HumanMessage(ANSWER_TASK.format(
            question=state["question"], language="Egyptian Arabic" if lang == "ar" else "English",
            ids=evidence_index(evidence, state["messages"]) or "(none: no tool was called)", slot_rules=SLOT_RULES))]
        if state.get("problems"):
            ask.append(AIMessage(content=str(state["answer"])))
            ask.append(HumanMessage(PATCH_TASK.format(problems="\n".join(f"- {p}" for p in state["problems"]))))
        try:
            reply = roles.get("tools").structured([*state["messages"], *ask], m.QaAnswer)
        except StructuredError as exc:
            return {**_stop("qa_answer", exc), "evidence": evidence}
        return {"answer": reply.parsed.model_dump(mode="json"), "evidence": evidence,
                "calls": _calls(state["messages"]), "llm_usage": _usage("qa_answer", reply)}
    return qa_answer


def qa_check(state: QaState) -> dict:
    rendered, bound, problems = check_answer(state["answer"], state["evidence"], state["question"],
                                             state.get("lang", "en"))
    patches = state.get("patches", 0)
    if problems and patches < MAX_PATCHES:
        return {"rendered": rendered, "bound": bound, "problems": problems, "patches": patches + 1}
    return {"rendered": rendered, "bound": bound, "problems": problems,
            "status": "validation_failed" if problems else state["answer"]["status"]}


def after_check(state: QaState) -> str:
    return "qa_answer" if state.get("status") == "running" else END


def build_graph(roles, checkpointer=None):
    """The compiled Q&A graph. Invoke with {"question", "lang"} and `context=RunContext(user, dataset)`."""
    g = StateGraph(QaState, context_schema=RunContext)
    g.add_node("qa_llm", make_qa_llm(roles))
    g.add_node("qa_tools", ToolNode(STAGE1_TOOLS))
    g.add_node("qa_answer", make_qa_answer(roles))
    g.add_node("qa_check", qa_check)
    g.add_edge(START, "qa_llm")
    g.add_conditional_edges("qa_llm", after_qa_llm, ["qa_tools", "qa_answer"])
    g.add_edge("qa_tools", "qa_llm")
    g.add_conditional_edges("qa_answer", after_agent_step("qa_check"), ["qa_check", END])
    g.add_conditional_edges("qa_check", after_check, ["qa_answer", END])
    return g.compile(checkpointer=checkpointer)


def ask(graph, question: str, user, lang: str = "en", dataset: str = "live", thread: str = "qa") -> dict:
    """One question end to end → the final state (plain data)."""
    cfg = {"configurable": {"thread_id": thread}}
    return graph.invoke({"question": question, "lang": lang}, cfg, context=RunContext(user, dataset))
