"""Golden set (RAG plan Phase 1): the questions every retrieval setting is measured on, written BEFORE any model runs.

Plan:    docs/plans/RAG_Embeddings_Qdrant_plan.md, Phase 1 (decision D7).
Run:     uv run python tools/run.py pipelines/scripts/retrieval/Golden_set.py  (from the project root)

Reads:   Data/processed/rag/chunks/*.parquet; Data/processed/rag/documents.csv; PostgreSQL through the read-only user
         (PG_RO_*; employees, roles, departments for the RBAC cases)
Writes:  Data/processed/rag/eval/golden_set.jsonl (64 queries + 8 RBAC cases, one JSON object per line)
Re-run:  safe: read-only on the database; rewrites the same file byte for byte (asserted by its SHA-256 once frozen)

What it is
- 40 English questions written from the chunks as a user would ask them (no copying of distinctive chunk phrases,
  except in identifier questions), each with 1-3 expected `chunk_id`s. Several ids mean the same fact is stated in
  several chunks (e.g. a USCG cause in the Conclusions and in the Executive Summary, a recommendation repeated in the
  Commandant's action, the District endorsement and the Investigating Officer's report). The metric is therefore
  hit-based: a query is found at k if ANY expected id is in the top k (recall@k = share of queries found).
- 24 Egyptian Arabic twins of 24 of them, with the same expected ids (paired, D7): 64 queries, 62.5 % / 37.5 %.
- Question types of docs/RETRIEVAL_FLOW.md §3: 1 definition / procedure / rule, 2 incident analysis, 3 benchmark /
  policy, 5 money (the document part: tariff / liability rules), 9 protected (level-3 chunks).
- >= 6 identifier questions (vessel name, MISLE number, circular number): the BM25 test.
- 8 RBAC cases on the level-3 HbR chunks: a question + an employee + visible / hidden. The expected outcome is
  written by hand AND recomputed from the database with the ADR-006 rule; both must agree.
- Coverage per source: USCG 22, HbR 6, IMO 4, LPI 4 (2 Methodology + 2 Connecting to Compete), FBL 2, Suez 2.
  USCG is below its corpus share (71 % of chunks -> 55 % of questions) so that every source has >= 2 questions.

Phases
1. Questions, twins and RBAC cases (reviewed by the owner before freezing).
2. Validation against the chunks, the registry and the database.
3. Save, reload from disk, re-validate; SHA-256 (frozen after review).
"""
# %% Setup
import hashlib
import json
import os
from collections import Counter
from pathlib import Path

import pandas as pd
import psycopg

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
CHUNKS = ROOT / "Data" / "processed" / "rag" / "chunks"
REGISTRY = ROOT / "Data" / "processed" / "rag" / "documents.csv"
OUT = ROOT / "Data" / "processed" / "rag" / "eval" / "golden_set.jsonl"

# Frozen after the owner's review (2026-10-02): any change to the set stops the script.
REVIEWED_SHA256 = "a187b4966f250211d7498b87d34d56b518af41d851cf8570716fce01f2dbb8bc"


def load_env() -> None:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


# %% Phase 1 — Questions
# One entry per English question: (qid, type, identifier?, question, expected chunk ids, Egyptian Arabic twin or None).
# Types: definition (1), incident (2), benchmark (3), money (5), protected (9) — docs/RETRIEVAL_FLOW.md §3.
Q = [
    # --- United States Coast Guard (22) -----------------------------------------------------------------------------
    ("q01", "incident", True,
     "What caused the operator of the recreational boat BIG STICK to go overboard?",
     ["uscg_big_stick_047"],
     "إيه اللي خلّى سواق المركب BIG STICK يقع في البحر؟"),
    ("q02", "incident", False,
     "Why did the fishing boat that left Brunswick, Georgia in October 2023 sink with its whole crew?",
     ["uscg_carol_ann_102", "uscg_carol_ann_039"],
     "مركب الصيد اللي طلعت من برونزويك في جورجيا في أكتوبر 2023 غرقت هي وطاقمها كله ليه؟"),
    ("q03", "definition", False,
     "Did the Coast Guard agree that every commercial fishing vessel should be required to carry AIS?",
     ["uscg_carol_ann_006", "uscg_carol_ann_021", "uscg_carol_ann_022"],
     "خفر السواحل وافق إن كل مراكب الصيد التجارية يبقى عليها جهاز AIS إجباري ولا لأ؟"),
    ("q04", "incident", False,
     "What made the conch fishing boat from Cape May capsize in December 2020?",
     ["uscg_conchrd_130", "uscg_conchrd_013"],
     "إيه اللي قلب مركب صيد القواقع اللي من كيب ماي في ديسمبر 2020؟"),
    ("q05", "incident", False,
     "How did a fire break out in a cargo hold of a Great Lakes bulk carrier during welding work in 2024?",
     ["uscg_cuyahoga_088", "uscg_cuyahoga_021"],
     "الحريقة اللي قامت في عنبر شحن سفينة بضاعة صب في البحيرات العظمى وقت شغل اللحام سنة 2024 بدأت إزاي؟"),
    ("q06", "definition", False,
     "What did investigators recommend about the fire danger of rubber conveyor belts on self-unloading ships?",
     ["uscg_cuyahoga_003", "uscg_cuyahoga_009", "uscg_cuyahoga_014"],
     None),
    ("q07", "incident", False,
     "How did a newly hired worker drown inside a pump on a vessel in dry dock?",
     ["uscg_general_macarthur_037", "uscg_general_macarthur_012"],
     "إزاي عامل لسه متعين جديد غرق جوه طلمبة في سفينة في الحوض الجاف؟"),
    ("q08", "incident", False,
     "Why did a technical diver die on a dive trip out of Pensacola in 2020?",
     ["uscg_h20_below_037"],
     None),
    ("q09", "incident", False,
     "How was the operator of a shrimp boat from Aransas Pass killed by the winch?",
     ["uscg_kim_ly_038", "uscg_kim_ly_021"],
     "سواق مركب الجمبري اللي من أرانساس باس مات من الونش إزاي؟"),
    ("q10", "definition", False,
     "Should the machinery guarding rules be extended to fishing vessels that operate inside the boundary line?",
     ["uscg_kim_ly_003", "uscg_kim_ly_006", "uscg_kim_ly_009"],
     None),
    ("q11", "definition", False,
     "Should commercial fishermen be required to use an engine kill switch when they fish alone?",
     ["uscg_la6893er_005", "uscg_la6893er_014", "uscg_la6893er_020"],
     "المفروض نلزم صيادين المراكب التجارية يستخدموا مفتاح فصل الموتور لما يكونوا بيصطادوا لوحدهم؟"),
    ("q12", "incident", False,
     "Why did a crew member of a crab boat fall into the water and drown in 2024?",
     ["uscg_lady_ellen_052", "uscg_lady_ellen_027"],
     "بحّار على مركب صيد كابوريا وقع في المية وغرق سنة 2024، ليه؟"),
    ("q13", "incident", False,
     "What caused the workboat tied up on the Alabama River to flood?",
     ["uscg_little_g_037", "uscg_little_g_013"],
     None),
    ("q14", "incident", True,
     "What were the contributing factors of the hull failure in MISLE case 7971638?",
     ["uscg_michipicoten_053"],
     "إيه العوامل اللي ساهمت في شرخ البدن في قضية MISLE رقم 7971638؟"),
    ("q15", "incident", True,
     "What were the causal factors behind the NC3250BW operator falling overboard?",
     ["uscg_nc3250bw_030", "uscg_nc3250bw_011"],
     None),
    ("q16", "incident", False,
     "Why did a passenger boat and a large yacht collide off San Diego in 2018?",
     ["uscg_prowler_attessa_iv_043"],
     "ليه مركب ركاب ويخت كبير خبطوا في بعض قدام سان دييجو سنة 2018؟"),
    ("q17", "definition", False,
     "Did the Coast Guard agree to require lighted life rings and searchlights in rescue boats on passenger vessels?",
     ["uscg_queen_of_the_west_003"],
     None),
    ("q18", "incident", False,
     "What most likely started the fire on the dinner cruise boat moored in Boston Harbor?",
     ["uscg_spirit_of_boston_173", "uscg_spirit_of_boston_032"],
     "إيه غالبًا اللي ولّع الحريقة في مركب العشا اللي كانت راسية في ميناء بوسطن؟"),
    ("q19", "incident", True,
     "Why did the dredge in MISLE case 7039383 strike a pipeline?",
     ["uscg_waymon_boyd_099", "uscg_waymon_boyd_024"],
     "الكراكة اللي في قضية MISLE رقم 7039383 خبطت خط الأنابيب ليه؟"),
    ("q20", "incident", False,
     "What caused the swamp tour airboat to crash into trees?",
     ["uscg_wilderness_i_053"],
     None),
    ("q21", "incident", True,
     "What caused the VICAR 602 to collide with a rowing boat?",
     ["uscg_vicar_602_032"],
     None),
    ("q22", "incident", False,
     "In which fatal falls overboard was alcohol or drug use found to be a causal factor?",
     ["uscg_big_stick_047", "uscg_nc3250bw_030", "uscg_lady_ellen_052"],
     "في أنهي حوادث وقوع من المركب انتهت بوفاة كان شرب الكحول أو المخدرات سبب فيها؟"),
    # --- International Maritime Organization (4) --------------------------------------------------------------------
    ("q23", "definition", False,
     "When does a flag State have to investigate a casualty to one of its ships and send the findings to IMO?",
     ["imo_mci_para_02_chunk_1"],
     "الدولة اللي السفينة رافعة علمها لازم تحقق في الحادثة وتبعت النتايج للـ IMO إمتى؟"),
    ("q24", "definition", False,
     "What has to be submitted to IMO after a very serious marine casualty?",
     ["imo_mci_para_06_chunk_1"],
     "إيه اللي لازم يتبعت للـ IMO بعد حادثة بحرية خطيرة جدًا؟"),
    ("q25", "definition", True,
     "Which earlier reporting forms does circular MSC-MEPC.3/Circ.4/Rev.1 replace?",
     ["imo_mci_para_04_chunk_1"],
     None),
    ("q26", "definition", False,
     "What severity levels can be used to classify a casualty event?",
     ["imo_mci_table_05_chunk_1"],
     None),
    # --- The World Bank: LPI Methodology (2) + Connecting to Compete 2025 (2) -----------------------------------------
    ("q27", "benchmark", False,
     "How does the World Bank measure how long containers stay in the port when they are imported?",
     ["lpi_table_1_row_01_chunk_1", "lpi2025_paragraph_027_chunk_1"],
     "البنك الدولي بيقيس إزاي الحاويات المستوردة بتقعد قد إيه في الميناء؟"),
    ("q28", "benchmark", False,
     "Which data is used to calculate how long ships stay in port?",
     ["lpi_paragraph_038_039_chunk_1", "lpi_figure_6_chunk_1"],
     None),
    ("q29", "benchmark", False,
     "Why does it take landlocked developing countries so long to import a container?",
     ["lpi2025_paragraph_047_chunk_1", "lpi2025_paragraph_048_chunk_1", "lpi2025_figure_2_5_chunk_1"],
     "ليه الدول النامية اللي ملهاش بحر بتاخد وقت طويل أوي عشان تستورد حاوية؟"),
    ("q30", "benchmark", False,
     "What share of container shipments is transshipped, and how much time does that add?",
     ["lpi2025_figure_2_3_chunk_1", "lpi2025_paragraph_042_chunk_1"],
     "قد إيه من شحنات الحاويات بتتنقل من سفينة لسفينة في الطريق، وده بيزوّد الوقت قد إيه؟"),
    # --- FIATA (2) ----------------------------------------------------------------------------------------------------
    ("q31", "money", False,
     "Up to how much is a freight forwarder liable per package under the FIATA multimodal bill of lading?",
     ["liability_limits_chunk_1", "clause_8_chunk_1"],
     "الفريت فورواردر مسؤول لحد كام عن كل طرد في بوليصة الشحن متعددة الوسائط بتاعة FIATA؟"),
    ("q32", "definition", False,
     "How long does a merchant have to sue the freight forwarder under the FBL conditions?",
     ["clause_17_chunk_1"],
     None),
    # --- Suez Canal Authority (2) --------------------------------------------------------------------------------------
    ("q33", "money", False,
     "In which currencies can Suez Canal transit dues be paid?",
     ["suez_notes_transit_conditions_payment_currencies"],
     "رسوم العبور في قناة السويس ممكن تتدفع بأنهي عملات؟"),
    ("q34", "money", False,
     "Are yachts, tugboats and dredgers charged as special floating units in the Suez Canal?",
     ["suez_notes_special_floating_units"],
     None),
    # --- Port of Rotterdam Authority (6; q35-q36 target the level-3 Finance chunks) ----------------------------------
    ("q35", "protected", False,
     "What was the Port of Rotterdam Authority's net profit in 2025?",
     ["hbr2025_paragraph_030_033_chunk_1", "hbr2025_tab_p82b_r01_r13_chunk_1", "hbr2025_tab_p82a_r11_r19_chunk_1"],
     "صافي ربح هيئة ميناء روتردام سنة 2025 كان كام؟"),
    ("q36", "protected", False,
     "How much did the Port of Rotterdam Authority invest in 2025?",
     ["hbr2025_fig_p13_chunk_1", "hbr2025_paragraph_030_033_chunk_1"],
     "هيئة ميناء روتردام استثمرت كام سنة 2025؟"),
    ("q37", "benchmark", False,
     "How much cargo went through the port of Rotterdam in 2025?",
     ["hbr2025_paragraph_034_035_chunk_1", "hbr2025_tab_p13_r01_r09_chunk_1", "hbr2025_tab_p83b_r01_r13_chunk_1"],
     "ميناء روتردام عدّى فيه بضاعة قد إيه سنة 2025؟"),
    ("q38", "benchmark", False,
     "What is Rotterdam's plan to let ships at berth plug into electricity instead of running their engines?",
     ["hbr2025_box_p28_chunk_1", "hbr2025_milestone_p6_3_chunk_1"],
     None),
    ("q39", "benchmark", False,
     "Did the Port of Rotterdam Authority meet its lost-time injury target in 2025?",
     ["hbr2025_tab_p54_r01_r02_chunk_1"],
     None),
    ("q40", "benchmark", False,
     "Were there any major nautical incidents in the port of Rotterdam in 2025?",
     ["hbr2025_tab_p64_r01_chunk_1", "hbr2025_paragraph_327_328_chunk_1", "hbr2025_tab_p83b_r01_r13_chunk_1"],
     None),
]

# RBAC cases (ADR-006): (case id, query id, employee_id, written expectation). The role ceiling and department come from
# PostgreSQL; the expectation is recomputed in Phase 2. "_ar" = the Egyptian Arabic twin.
RBAC = [
    ("r1", "q35", 1, "visible"),      # CEO (ceiling 3)
    ("r2", "q35", 6, "hidden"),       # Finance manager: the department never unlocks level 3
    ("r3", "q35", 13, "hidden"),      # Finance employee
    ("r4", "q36_ar", 1, "visible"),   # CEO, Arabic question
    ("r5", "q36", 7, "hidden"),       # Finance manager
    ("r6", "q35", 2, "hidden"),       # Operations manager (same department as the CEO)
    ("r7", "q36", 10, "hidden"),      # IT manager
    ("r8", "q35_ar", 24, "hidden"),   # Finance employee, Arabic question
]

REVIEWED_1 = {  # reviewed 2026-10-01 (counts written in the plan, D7)
    "en": 40, "ar": 24, "identifier_queries": 9, "rbac": 8,
    "en_by_source": {"United States Coast Guard": 22, "Port of Rotterdam Authority": 6,
                     "International Maritime Organization (IMO)": 4, "The World Bank": 4, "FIATA": 2,
                     "Suez Canal Authority": 2},
    "en_by_type": {"incident": 17, "definition": 10, "benchmark": 8, "money": 3, "protected": 2},
}


def build_queries(chunks: pd.DataFrame, file_to_doc: dict[str, str]) -> list[dict]:
    meta = chunks.set_index("chunk_id")
    rows = []
    for qid, qtype, ident, en, ids, ar in Q:
        docs = sorted({file_to_doc[meta.loc[i, "filename"]] for i in ids})
        sources = sorted({meta.loc[i, "source"] for i in ids})
        base = {"type": qtype, "identifier": ident, "expected_chunk_ids": ids, "document_ids": docs,
                "sources": sources}
        rows.append({"kind": "query", "qid": qid, "lang": "en", "twin_of": None, "question": en, **base})
        if ar:
            rows.append({"kind": "query", "qid": f"{qid}_ar", "lang": "ar", "twin_of": qid, "question": ar, **base})
    return rows


# %% Phase 2 — Validation against the chunks, the registry and the database
def employees_from_db(ids: list[int]) -> dict[int, dict]:
    e = os.environ
    with psycopg.connect(host=e["PGHOST"], port=e["PGPORT"], dbname=e["PGDATABASE"], user=e["PG_RO_USER"],
                         password=e["PG_RO_PASSWORD"], options="-c default_transaction_read_only=on") as conn:
        rows = conn.execute(
            "SELECT e.employee_id, r.role_name, r.allowed_sensitivity_level, d.department_name "
            "FROM employees e JOIN roles r USING (role_id) JOIN departments d USING (department_id) "
            "WHERE e.employee_id = ANY(%s)", (ids,)).fetchall()
    return {r[0]: {"role": r[1], "ceiling": r[2], "department": r[3]} for r in rows}


def allowed(user: dict, level: int, department: str) -> bool:
    """ADR-006: role ceiling, or own department up to level 2 (level 3 is never unlocked by department)."""
    return level <= user["ceiling"] or (department == user["department"] and level <= 2)


def build_rbac(queries: list[dict], chunks: pd.DataFrame) -> list[dict]:
    meta = chunks.set_index("chunk_id")
    by_qid = {q["qid"]: q for q in queries}
    users = employees_from_db(sorted({c[2] for c in RBAC}))
    rows = []
    for cid, qid, emp, written in RBAC:
        q, u = by_qid[qid], users[emp]
        level3 = [i for i in q["expected_chunk_ids"] if meta.loc[i, "sensitivity_level"] == 3]
        computed = {allowed(u, int(meta.loc[i, "sensitivity_level"]), meta.loc[i, "department"]) for i in level3}
        assert len(computed) == 1, f"{cid}: mixed visibility among the level-3 ids"
        got = "visible" if computed.pop() else "hidden"
        assert got == written, f"{cid}: written {written}, ADR-006 on the database says {got} ({u})"
        rows.append({"kind": "rbac", "case": cid, "qid": qid, "employee_id": emp, "role": u["role"],
                     "department": u["department"], "expect": written, "level3_chunk_ids": level3})
    return rows


def validate(rows: list[dict], chunks: pd.DataFrame) -> dict:
    meta = chunks.set_index("chunk_id")
    qs = [r for r in rows if r["kind"] == "query"]
    rb = [r for r in rows if r["kind"] == "rbac"]
    en = [q for q in qs if q["lang"] == "en"]
    ar = [q for q in qs if q["lang"] == "ar"]
    assert len({q["qid"] for q in qs}) == len(qs), "duplicate qid"
    assert len({q["question"].strip().lower() for q in qs}) == len(qs), "duplicate question text"
    for q in qs:
        ids = q["expected_chunk_ids"]
        assert 1 <= len(ids) <= 3 and len(set(ids)) == len(ids), f"{q['qid']}: 1-3 distinct ids"
        missing = [i for i in ids if i not in meta.index]
        assert not missing, f"{q['qid']}: unknown chunk ids {missing}"
        levels = {int(meta.loc[i, "sensitivity_level"]) for i in ids}
        assert (q["type"] == "protected") == (levels == {3}), f"{q['qid']}: protected <=> all expected ids level 3"
    en_by_id = {q["qid"]: q for q in en}
    for a in ar:  # paired twins: same expected ids, same type
        t = en_by_id[a["twin_of"]]
        assert (a["expected_chunk_ids"], a["type"]) == (t["expected_chunk_ids"], t["type"]), a["qid"]
        assert any("؀" <= ch <= "ۿ" for ch in a["question"]), f"{a['qid']}: not Arabic script"
    assert {"definition", "incident", "benchmark", "money", "protected"} <= {q["type"] for q in en}
    assert any(r["department"] == "Finance" and r["role"] == "employee" for r in rb), "Finance employee case"
    assert {r["expect"] for r in rb} == {"visible", "hidden"}
    assert {r["role"] for r in rb if r["expect"] == "visible"} == {"ceo"}, "level 3: CEO only"
    return {
        "en": len(en), "ar": len(ar), "identifier_queries": sum(q["identifier"] for q in qs), "rbac": len(rb),
        "en_by_source": dict(Counter(s for q in en for s in q["sources"][:1])),
        "en_by_type": dict(Counter(q["type"] for q in en)),
    }


# %% Phase 3 — Save, reload, re-validate, hash
def save(rows: list[dict]) -> str:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    OUT.write_bytes(text.encode("utf-8"))  # LF line endings on every platform: a stable hash
    return hashlib.sha256(OUT.read_bytes()).hexdigest()


def main() -> None:
    load_env()
    chunks = pd.concat([pd.read_parquet(f) for f in sorted(CHUNKS.glob("*.parquet"))], ignore_index=True)
    assert len(chunks) == 2163 and chunks.chunk_id.is_unique
    registry = pd.read_csv(REGISTRY)
    # the registry stores the path under Data/raw/, the chunks the bare file name (basenames are unique, ADR-035)
    file_to_doc = dict(zip(registry.filename.map(lambda p: Path(p).name), registry.document_id))
    assert len(file_to_doc) == len(registry) == 29

    queries = build_queries(chunks, file_to_doc)
    print(f"Phase 1: {len(queries)} queries ({sum(q['lang'] == 'en' for q in queries)} en), {len(RBAC)} RBAC cases")

    rows = queries + build_rbac(queries, chunks)
    actual = validate(rows, chunks)
    assert actual == REVIEWED_1, f"snapshot changed:\n{actual}"
    print("✅ Phase 2 validation passed (ids exist, twins paired, types covered, RBAC = ADR-006 on the database).")

    sha = save(rows)
    reloaded = [json.loads(line) for line in OUT.read_text(encoding="utf-8").splitlines()]
    assert reloaded == rows and validate(reloaded, chunks) == REVIEWED_1
    if REVIEWED_SHA256 is not None:
        assert sha == REVIEWED_SHA256, f"golden set changed after freezing: {sha}"
    status = "FROZEN" if REVIEWED_SHA256 else "NOT FROZEN (owner review pending)"
    print(f"✅ Phase 3 validation passed: {len(rows)} lines reloaded and re-validated; sha256 {sha} — {status}")
    print(f"✅ Golden set: {actual['en']} en + {actual['ar']} ar queries, {actual['identifier_queries']} identifier, "
          f"{actual['rbac']} RBAC cases.")


if __name__ == "__main__":
    main()
