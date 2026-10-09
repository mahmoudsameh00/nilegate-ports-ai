"""Retrieval evaluation at three levels (ADR-040): retrieval quality, ranking quality, context quality.

Inputs per query: the full ranking of the corpus (chunk positions, best first), the expected chunk ids of the frozen
golden set, and the facts of golden_facts.jsonl (claims judged on the chunk text, so any chunk that states a fact
counts, labelled or not).

| Dimension | Primary            | Diagnostics                                          |
|-----------|--------------------|------------------------------------------------------|
| retrieval | fact_recall@10     | hit@10 (any expected id), complete@10                |
| ranking   | nDCG@10            | MRR (first expected id), hit@1, hit@5                |
| context   | sufficiency@8      | precision@8, redundancy@8, facts per 1,000 chars     |

- Relevance (nDCG, precision): a chunk is relevant if it states >= 1 fact of the question or is an expected id;
  nDCG's ideal ranking uses the corpus-wide relevant set (computable because facts are text patterns).
- Context = the first K_CONTEXT chunks: what `search_documents(k=8)` hands to the answering model.
- Redundancy@8: share of the relevant context chunks that add no fact not already given by a higher chunk.
- Balanced score = mean of the three primaries, each the mean of its English and Arabic values (equal weight, as D1).
"""
import math
import re
from collections.abc import Iterable

import numpy as np
import pandas as pd

K_RETRIEVAL, K_CONTEXT = 10, 8
PRIMARY = {"retrieval": "fact_recall@10", "ranking": "ndcg@10", "context": "sufficiency@8"}


class FactMatcher:
    """The facts of one question: which of them a text states."""

    def __init__(self, facts: list[dict]):
        self.ids = [f["id"] for f in facts]
        self.rules = [(f["id"], [re.compile("|".join(f"(?:{a})" for a in group), re.IGNORECASE)
                                 for group in f["all"]]) for f in facts]

    def facts_in(self, text: str) -> set[str]:
        return {fid for fid, groups in self.rules if all(g.search(text) for g in groups)}

    def corpus_counts(self, texts: Iterable[str]) -> dict[str, int]:
        counts = dict.fromkeys(self.ids, 0)
        for t in texts:
            for fid in self.facts_in(t):
                counts[fid] += 1
        return counts

    def relevant_positions(self, texts: Iterable[str]) -> set[int]:
        return {i for i, t in enumerate(texts) if self.facts_in(t)}


class QueryJudge:
    """Everything needed to score one question's ranking, precomputed once over the corpus."""

    def __init__(self, facts: list[dict], expected_positions: set[int], texts: list[str]):
        m = FactMatcher(facts)
        self.all_facts = set(m.ids)
        self.expected = set(expected_positions)
        self.facts_at = {i: f for i, t in enumerate(texts) if (f := m.facts_in(t))}
        self.relevant = set(self.facts_at) | self.expected
        self.lengths = [len(t) for t in texts]

    def score(self, ranking: np.ndarray) -> dict:
        top = [int(i) for i in ranking[:K_RETRIEVAL]]
        ctx = top[:K_CONTEXT]
        # a full corpus ranking always holds an expected id; a tool's truncated list may not (rank = inf, rr = 0)
        first_expected = next((r for r, i in enumerate(ranking, 1) if int(i) in self.expected), math.inf)

        def covered(chunk_positions):
            return set().union(*(self.facts_at.get(i, set()) for i in chunk_positions))

        rel = [1.0 if i in self.relevant else 0.0 for i in top]
        dcg = sum(g / math.log2(r + 1) for r, g in enumerate(rel, 1))
        idcg = sum(1 / math.log2(r + 1) for r in range(1, min(len(self.relevant), K_RETRIEVAL) + 1))
        seen, novel, relevant_ctx = set(), 0, 0
        for i in ctx:
            if i in self.relevant:
                relevant_ctx += 1
                new = self.facts_at.get(i, set()) - seen
                novel += bool(new)
                seen |= new
        n_facts = len(self.all_facts)
        return {
            "hit@1": float(first_expected <= 1), "hit@5": float(first_expected <= 5),
            "hit@10": float(first_expected <= 10), "rr": 1 / first_expected,
            "first_expected_rank": first_expected if first_expected != math.inf else None,
            "fact_recall@10": len(covered(top)) / n_facts, "complete@10": float(covered(top) == self.all_facts),
            "ndcg@10": dcg / idcg,
            "sufficiency@8": float(covered(ctx) == self.all_facts), "precision@8": relevant_ctx / K_CONTEXT,
            "redundancy@8": (1 - novel / relevant_ctx) if relevant_ctx else 0.0,
            "facts_per_1k_chars@8": len(covered(ctx)) / (sum(self.lengths[i] for i in ctx) / 1000),
            "missing_facts@8": sorted(self.all_facts - covered(ctx)),
        }


def judges(queries: list[dict], facts_by_qid: dict[str, list[dict]], chunk_ids: list[str],
           texts: list[str]) -> dict[str, QueryJudge]:
    """One judge per query (Arabic twins use the facts of their English question)."""
    pos = {c: i for i, c in enumerate(chunk_ids)}
    out = {}
    for q in queries:
        base = q["twin_of"] or q["qid"]
        out[q["qid"]] = QueryJudge(facts_by_qid[base], {pos[c] for c in q["expected_chunk_ids"]}, texts)
    return out


METRICS = ["hit@1", "hit@5", "hit@10", "rr", "fact_recall@10", "complete@10", "ndcg@10",
           "sufficiency@8", "precision@8", "redundancy@8", "facts_per_1k_chars@8"]


def aggregate(per_query: pd.DataFrame) -> dict:
    """Mean of every metric overall / per language / per source / per type, the three primaries and the balanced
    score. `per_query` has one row per query with the metric columns plus lang, source, type, identifier."""
    def block(d: pd.DataFrame) -> dict:
        r = {m.replace("rr", "mrr") if m == "rr" else m: round(float(d[m].mean()), 4) for m in METRICS}
        r["n"] = int(len(d))
        return r

    out = {"all": block(per_query), "en": block(per_query[per_query.lang == "en"]),
           "ar": block(per_query[per_query.lang == "ar"]), "identifier": block(per_query[per_query.identifier]),
           "by_source": {k: block(g) for k, g in per_query.groupby("source")},
           "by_type": {k: block(g) for k, g in per_query.groupby("type")}}
    dims = {d: round((out["en"][m] + out["ar"][m]) / 2, 4) for d, m in PRIMARY.items()}
    out["dimensions"] = dims
    out["balanced"] = round(sum(dims.values()) / len(dims), 4)
    out["primary_d1"] = round((out["en"]["hit@10"] + out["ar"]["hit@10"]) / 2, 4)  # the D1 rule (ADR-037)
    return out
