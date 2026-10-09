"""Golden facts: the information each golden question needs, so retrieval can be judged at the information level.

Plan:    docs/archive/2026-10-08_RAG_Embeddings_Qdrant_plan.md (evaluation framework, ADR-040). Complements the frozen golden set
         (Golden_set.py), which it never changes.
Run:     uv run python tools/run.py pipelines/scripts/retrieval/Golden_facts.py  (from the project root)

Reads:   Data/processed/rag/chunks/*.parquet; Data/processed/rag/eval/golden_set.jsonl (frozen)
Writes:  Data/processed/rag/eval/golden_facts.jsonl (one line per English question; the Arabic twins use the facts of
         their English question: the corpus is English)
Re-run:  safe: rewrites the same file byte for byte (asserted by its SHA-256 once frozen)

Why: the golden set labels 1-3 equivalent chunks per question, which tells whether ONE right chunk was found
(hit@k) but not whether the context holds everything the answer needs (q22 needs three incidents: hit@10 counted a
context with two of them as a success), nor how much of the context is useful. Facts fix that: they are judged on
the text itself, so any chunk that states the fact counts, labelled or not.

Facts are judged on the delivered unit `compose(title, text)` (ADR-041: the location label is in `title`).
A fact is a claim, not a word: `all` is a list of groups that must ALL match the same chunk (case-insensitive regex),
each group a list of alternatives. USCG chunks all carry their vessel name in their title, so a USCG fact is always
(vessel) AND (the claim): "BIG STICK" alone would make all 51 chunks of that report relevant.

Validation (Phase 2)
- every pattern compiles; every fact is stated by at least one expected chunk of its question (attainable);
- the expected chunks of a question together state ALL its facts (a perfect retrieval is sufficient);
- specificity: no fact is stated by more than MAX_CHUNKS_PER_FACT chunks of the corpus (a broader pattern is not a
  claim); the corpus-wide relevant set per question (chunks stating >= 1 fact, plus the expected ids) is what nDCG
  uses as its ideal ranking.
"""
# %% Setup
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from pipelines.lib import chunks as chunk_contract  # noqa: E402
from pipelines.lib import evaluation  # noqa: E402

GOLDEN = ROOT / "Data" / "processed" / "rag" / "eval" / "golden_set.jsonl"
GOLDEN_SHA256 = "a187b4966f250211d7498b87d34d56b518af41d851cf8570716fce01f2dbb8bc"
OUT = ROOT / "Data" / "processed" / "rag" / "eval" / "golden_facts.jsonl"
# Frozen after the owner's review (2026-10-02): any change to the facts stops the script.
REVIEWED_SHA256 = "09b5f5b6892133806a9c11a006490c31c63782e560cb9a038977b1d2f5998d25"
MAX_CHUNKS_PER_FACT = 40

# %% Phase 1 — Facts per English question: qid -> [(fact id, description, [[alternatives], [alternatives], ...])]
BS, CA, CO, CU = r"BIG STICK", r"CAROL ANN", r"CONCH.?RD", r"CUYAHOGA"
GM, KL, LA, LE = r"GENERAL MACARTHUR", r"KIM LY", r"LA6893ER", r"LADY ELLEN"
NC, QW, SB, WB = r"NC3250BW", r"QUEEN OF THE WEST|AMERICAN WEST", r"SPIRIT OF BOSTON", r"WAYMON BOYD"
F = {
    "q01": [("f1", "under the influence of alcohol", [[BS], [r"alcohol"]]),
            ("f2", "a solo fishing trip", [[BS], [r"\bsolo\b", r"\balone\b"]])],
    "q02": [("f1", "the vessel lost stability", [[CA], [r"los(t|ing|s) (its )?stability"]]),
            ("f2", "inadequate freeing port area", [[CA], [r"(inadequate|lack of|no clear)[^.]{0,60}freeing port"]]),
            ("f3", "master proceeded despite sea conditions", [[CA], [r"quartering seas", r"prudent seamanship",
                                                                      r"decision to proceed"]])],
    "q03": [("f1", "recommendation: AIS on all commercial fishing vessels", [[CA], [r"equipped with (AIS|Automatic Information)"]]),
            ("f2", "the Coast Guard did not concur", [[CA], [r"\bAIS\b"], [r"do not concur", r"non-?concur"]])],
    "q04": [("f1", "overloading / improper loading with conch pots", [[CO], [r"overload"]]),
            ("f2", "no stability test or instructions", [[CO], [r"stability test", r"stability instructions"]]),
            ("f3", "the owner/operator's inexperience", [[CO], [r"inexperience", r"lack of experience"]])],
    "q05": [("f1", "an electrical arc from the welder or extension cord", [[CU], [r"electrical arc"]]),
            ("f2", "nut coke residue with the epoxy coating", [[CU], [r"nut coke"], [r"epoxy", r"Amerthane"]])],
    "q06": [("f1", "rubber conveyor belts are a fire-spread risk", [[CU], [r"rubber conveyor belt"], [r"fire"]]),
            ("f2", "earlier belt fires (ROGER BLOUGH, ST. CLAIR)", [[r"Roger Blough"], [r"St\.? Clair"]])],
    "q07": [("f1", "reached into the impeller opening for the hammer", [[GM], [r"impeller"], [r"hammer"]]),
            ("f2", "an unidentified, unlabelled confined space", [[GM], [r"confined space"]])],
    "q08": [("f1", "decompression stops not followed", [[r"H2O BELOW"], [r"decompression stop"]])],
    "q09": [("f1", "no safety guard on the winch", [[KL], [r"guard"], [r"winch"]]),
            ("f2", "no auxiliary-stop device", [[KL], [r"auxiliary.stop"]]),
            ("f3", "deteriorated cable guide", [[KL], [r"cable guide"]])],
    "q10": [("f1", "recommendation: extend 46 CFR 28.200 inside the boundary line", [[KL], [r"28\.200"], [r"boundary line"]]),
            ("f2", "the Commandant did not concur", [[KL], [r"do not concur"]])],
    "q11": [("f1", "recommendation: mandatory engine cut-off switches", [[LA], [r"engine cut-?off switch", r"\bECOS\b"],
                                                                          [r"single occupant", r"\bsolo\b"]]),
            ("f2", "Coast Guard prefers voluntary use", [[LA], [r"\bECOS\b", r"cut-?off switch"], [r"voluntary"]])],
    "q12": [("f1", "under the influence of cocaine", [[LE], [r"cocaine"]]),
            ("f2", "no perimeter railing", [[LE], [r"railing", r"guardrail"]]),
            ("f3", "not wearing a PFD", [[LE], [r"not wearing a PFD", r"to wear a personal flo"]])],
    "q13": [("f1", "flooding over the stern", [[r"LITTLE G\b"], [r"flooding over the stern"]]),
            ("f2", "improper ship handling", [[r"LITTLE G\b"], [r"improper ship handling"]])],
    "q14": [("f1", "chronic overstressing", [[r"MICHIPICOTEN"], [r"overstress"]]),
            ("f2", "cargo loading software / procedures", [[r"MICHIPICOTEN"], [r"loading software"]]),
            ("f3", "no maximum bending moment policy", [[r"MICHIPICOTEN"], [r"bending moment polic"]])],
    "q15": [("f1", "acute ethanol intoxication (BAC 0.15%)", [[NC], [r"ethanol intoxication", r"\bBAC\b"]]),
            ("f2", "fishing alone, no witnesses", [[NC], [r"\balone\b", r"isolation"]])],
    "q16": [("f1", "no additional / proper lookout on either vessel", [[r"PROWLER"], [r"ATTESS"], [r"lookout"]]),
            ("f2", "failed to use all available means to assess risk of collision", [[r"PROWLER"], [r"risk of collision"]])],
    "q17": [("f1", "lighted life rings and searchlights recommended", [[QW], [r"searchlight"], [r"life ?(ring|buoy)"]]),
            ("f2", "only partially concurred", [[QW], [r"partially concur"]])],
    "q18": [("f1", "a heating fuel canister", [[SB], [r"fuel canister"]]),
            ("f2", "no safe handling / storage procedures for flammables", [[SB], [r"safe handling"]])],
    "q19": [("f1", "the cutterhead struck pipeline TX219", [[WB], [r"TX219"], [r"cutterhead"]]),
            ("f2", "pipeline missing from dredge plans / software",
             [[WB], [r"(lack of inclusion|failure)[^.]{0,60}(dredge plans|DREDGEPACK|dredging software)"]])],
    "q20": [("f1", "failure to proceed at safe speed", [[r"Wilderness I\b"], [r"safe speed"]]),
            ("f2", "inadequate lookout, operating close to shore", [[r"Wilderness I\b"], [r"close to shore"]])],
    "q21": [("f1", "attention failure by the test crew", [[r"VICAR 602"], [r"attention failure"]]),
            ("f2", "collision avoidance system disabled", [[r"VICAR 602"], [r"collision avoidance system"], [r"disabled"]])],
    "q22": [("f1", "BIG STICK: alcohol", [[BS], [r"alcohol"]]),
            ("f2", "NC3250BW: ethanol intoxication", [[NC], [r"ethanol", r"\bBAC\b"]]),
            ("f3", "LADY ELLEN: cocaine", [[LE], [r"cocaine"]])],
    "q23": [("f1", "SOLAS regulation I/21 and MARPOL articles 8 and 12", [[r"SOLAS regulation I/21"]]),
            ("f2", "when it may show changes to the regulations are desirable", [[r"changes in the present regulations"]]),
            ("f3", "or a major deleterious effect on the marine environment", [[r"deleterious effect"]])],
    "q24": [("f1", "a marine safety investigation report, in addition to the data",
             [[r"very serious marine casualty"], [r"submit a marine safety investigation report"]])],
    "q25": [("f1", "replaces the forms of MSC-MEPC.3/Circ.3", [[r"MSC-MEPC\.3/Circ\.3\b"], [r"replace"]]),
            ("f2", "does not replace MSC/Circ.539/Add.2 or MSC/Circ.802", [[r"MSC/Circ\.539", r"MSC/Circ\.802"]])],
    "q26": [("f1", "very serious marine casualty / marine casualty / marine incident",
             [[r"Casualty event severity"], [r"Very serious marine casualty"], [r"Marine incident"]])],
    "q27": [("f1", "the indicator is container import dwell time", [[r"container import dwell time"]]),
            ("f2", "measured from arrival (ship unloading) to departure from the port",
             [[r"arrival \(ship unloading\)", r"from arrival"], [r"departure from the port"]])],
    "q28": [("f1", "MarineTraffic port call dataset", [[r"MarineTraffic"], [r"port call"]]),
            ("f2", "derived from AIS messages", [[r"MarineTraffic"], [r"Automatic Identification System"]]),
            ("f3", "turnaround: latest arrival to earliest departure", [[r"latest arrival"], [r"earliest departure"]])],
    "q29": [("f1", "cargo transits coastal countries, crossing borders", [[r"landlocked", r"LLDC"], [r"transit"],
                                                                          [r"more than one border", r"border"]]),
            ("f2", "time idling at ports, borders and checkpoints, not distance", [[r"idling"], [r"checkpoint"]]),
            ("f3", "corridor lead time and port-of-arrival dwell time are the largest parts",
             [[r"landlocked", r"LLDC"], [r"corridor lead time"], [r"dwell time at (the )?port of arrival"]])],
    "q30": [("f1", "about half of containers are transshipped", [[r"transship"], [r"51%", r"about half",
                                                                                  r"nearly half"]]),
            ("f2", "about 18 extra days per transshipment", [[r"transship"], [r"17\.75", r"18 extra days"]])],
    "q31": [("f1", "666.67 SDR per package or unit", [[r"666\.67 SDR"]]),
            ("f2", "or 2 SDR per kilogram, whichever is higher", [[r"2 SDR per kilogram"]])],
    "q32": [("f1", "suit within 9 months of delivery", [[r"9 months"], [r"suit"]])],
    "q33": [("f1", "the accepted currencies (USD, Euro, Yen ... Chinese Yuan)",
             [[r"transit dues"], [r"US dollar"], [r"Euro"], [r"Chinese Yuan"]])],
    "q34": [("f1", "yachts, dredgers and tugboats are Special Floating Units",
             [[r"Special Floating Units"], [r"Yachts"], [r"Dredgers"], [r"Tugboats"]])],
    "q35": [("f1", "net result 2025: EUR 266.0 million (265,977 thousand)", [[r"266\.0 million", r"265,977"]])],
    "q36": [("f1", "gross investments 2025: EUR 291.4 million", [[r"291\.4"]])],
    "q37": [("f1", "428.4 million tonnes in 2025", [[r"428[.,]4", r"428,372"]]),
            ("f2", "down 1.7% on 2024", [[r"428[.,]4", r"428,372"], [r"1[.,]7\s?%"]])],
    "q38": [("f1", "shore power the standard for most shipping by 2030", [[r"shore power"], [r"2030"]]),
            ("f2", "full zero-emission mooring by 2050", [[r"shore power"], [r"zero emission mooring"]]),
            ("f3", "the cruise terminal connected in 2025", [[r"shore power"], [r"Cruise (Terminal|Port)"]])],
    "q39": [("f1", "LTIFR target < 0.5, achieved 1.15: missed",
             [[r"Lost Time Injury Frequency", r"LITFR"], [r"0\.5"], [r"1[.,]15"]])],
    "q40": [("f1", "zero major nautical incidents in 2025",
             [[r"nautical incidents"], [r"Achieved 2025: 0", r"2025: 0", r"no major nautical incidents"]])],
}


def build() -> list[dict]:
    return [{"qid": qid, "facts": [{"id": f"{qid}.{fid}", "desc": d, "all": groups} for fid, d, groups in facts]}
            for qid, facts in F.items()]


# %% Phase 2 — Validation against the golden set and the corpus
def validate(rows: list[dict], golden: list[dict], df, units: list[str]) -> dict:
    en = {q["qid"]: q for q in golden if q["kind"] == "query" and q["lang"] == "en"}
    assert [r["qid"] for r in rows] == list(en), "one facts line per English question, in order"
    pos = {c: i for i, c in enumerate(df.chunk_id)}
    stats = {"facts": 0, "max_chunks_per_fact": 0, "relevant_per_question": {}}
    for r in rows:
        q = en[r["qid"]]
        assert 1 <= len(r["facts"]) <= 4, f"{r['qid']}: 1-4 facts"
        matcher = evaluation.FactMatcher(r["facts"])
        exp_texts = [units[pos[c]] for c in q["expected_chunk_ids"]]
        silent = [c for c, t in zip(q["expected_chunk_ids"], exp_texts) if not matcher.facts_in(t)]
        assert not silent, f"{r['qid']}: expected chunks that state no fact: {silent}"
        covered = set().union(*(matcher.facts_in(t) for t in exp_texts))
        assert covered == {f["id"] for f in r["facts"]}, \
            f"{r['qid']}: expected chunks miss {sorted({f['id'] for f in r['facts']} - covered)}"
        per_fact = matcher.corpus_counts(units)
        broad = {k: v for k, v in per_fact.items() if v > MAX_CHUNKS_PER_FACT}
        assert not broad, f"{r['qid']}: facts too broad (chunks stating them): {broad}"
        relevant = matcher.relevant_positions(units) | {pos[c] for c in q["expected_chunk_ids"]}
        stats["facts"] += len(r["facts"])
        stats["max_chunks_per_fact"] = max(stats["max_chunks_per_fact"], *per_fact.values())
        stats["relevant_per_question"][r["qid"]] = len(relevant)
    return stats


# %% Phase 3 — Save, reload, re-validate, hash
def main() -> None:
    assert hashlib.sha256(GOLDEN.read_bytes()).hexdigest() == GOLDEN_SHA256, "golden set is not the frozen one"
    golden = [json.loads(line) for line in GOLDEN.read_text(encoding="utf-8").splitlines()]
    df = chunk_contract.load(ROOT / "Data" / "processed" / "rag" / "chunks")
    rows = build()
    for r in rows:  # every pattern compiles
        for f in r["facts"]:
            for group in f["all"]:
                for alt in group:
                    re.compile(alt)
    units = [chunk_contract.compose(t, x) for t, x in zip(df.title, df.text)]  # the delivered unit (ADR-041)
    stats = validate(rows, golden, df, units)
    rel = stats["relevant_per_question"]
    print(f"✅ Phase 2 validation passed: {len(rows)} questions, {stats['facts']} facts, all attainable from the "
          f"expected chunks; broadest fact stated by {stats['max_chunks_per_fact']} chunks (cap {MAX_CHUNKS_PER_FACT}); "
          f"relevant chunks per question: min {min(rel.values())}, median {sorted(rel.values())[len(rel) // 2]}, "
          f"max {max(rel.values())}.")

    OUT.write_bytes("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode("utf-8"))
    reloaded = [json.loads(line) for line in OUT.read_text(encoding="utf-8").splitlines()]
    assert reloaded == rows and validate(reloaded, golden, df, units) == stats
    sha = hashlib.sha256(OUT.read_bytes()).hexdigest()
    if REVIEWED_SHA256 is not None:
        assert sha == REVIEWED_SHA256, f"golden facts changed after freezing: {sha}"
    status = "FROZEN" if REVIEWED_SHA256 else "NOT FROZEN (owner review pending)"
    print(f"✅ Phase 3 validation passed: {len(rows)} lines reloaded and re-validated; sha256 {sha} — {status}")


if __name__ == "__main__":
    main()
