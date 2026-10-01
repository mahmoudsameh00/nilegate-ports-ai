"""Synthetic EDI generator: one IFTMIN D:12A message per consignment group (vessel) for our containers.

Origin:  Converted from Notebooks/semi_structured/EDI_generator.ipynb (archived in docs/archive/notebooks/).
         Refactored (ADR-036 D3) 2026-10-01: the same four phases as functions; same artifact byte for byte (its
         reviewed SHA-256 is asserted below); same validation lines. The manifest keeps
         "generator": "Notebooks/semi_structured/EDI_generator.ipynb" so the file stays identical.
Run:     uv run python tools/run.py pipelines/scripts/semi_structured/EDI_generator.py  (from the project root)

Reads:   PostgreSQL containers, vessels, invoices, ports (read-only session);
         Data/processed/semi-structured/synthetic/voyages_synthetic.parquet + ais_generation_manifest.json (AIS_generator);
         Data/processed/semi-structured/profiles/iftmin_template.json (AIS_EDI_profiling)
Writes:  Data/processed/semi-structured/synthetic/edi_messages_synthetic.jsonl + edi_generation_manifest.json
Re-run:  safe: fixed seed, rewrites the same files
Final Checkpoint (what was done, problems, fixes): pipelines/checkpoints/semi_structured/EDI_generator.md

Plan: docs/archive/2026-09-27_SemiStructured_MongoDB_plan.md, Phase 7 (ADR-032). Files only: MongoDB_loader is the only
writer to MongoDB (ADR-031).

Decisions applied: D13 one message per consignment group (vessel + origin + destination; every container of a vessel
shares the vessel's ports, so one message per vessel) with one EQD per container; D14 no amounts (no MOA), so
edi_messages stays level 1; D15 the project's own tokenizer, reused for the round-trip check.

Invoice reference (owner decision 2026-09-28): every message of a vessel that has invoices carries RFF+IV with the
vessel's latest invoice (by date, then number). The document flow is mimicked (transport instruction → voyage → Suez
transit dues invoice → toll band), not real values, so dates are not aligned (invoices 2025, voyages 2026).

Mapping rules (Phase 2)
| Item | Rule |
|---|---|
| Interchange / message reference | 000001 … in vessel_id order (the unique index includes `source`, so no clash with the sample) |
| Document date (DTM+137) | 2 days before the voyage's departure (the instruction precedes loading) |
| Estimated arrival (DTM+132) | the voyage's arrival instant (AIS_generator) |
| Vessel (TDT C222) | IMO number, code list 146, agency 11 (Lloyd's Register / IMO), vessel name; voyage number in element 2 |
| Parties (NAD+CZ, NAD+CN) | <country>SHIP / <country>RECV from the port countries, code list 160, agency ZZZ (as in the template) |
| Equipment (EQD) | container number, ISO 6346 size-type code from type + size, status 2 (export), full / empty 5 / 4 |
| Seal (SEL) | full containers only, NG + 6 digits from a fixed stream |
| Gross weight (MEA+AAE) | per-container weights: tare for empty boxes, a seeded draw for full ones (documented default: PostgreSQL has no weights) |
| Invoice (RFF+IV) | the vessel's latest invoice (by date, then number), when the vessel has one |
Text values are escaped with the release character, so a vessel name containing ' + : or ? cannot break the message.
"""
import hashlib
import json
import os
import re
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg


def find_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / "pyproject.toml").exists() and (p / "Data").is_dir():
            return p
    raise FileNotFoundError("project root not found above " + str(start))


ROOT = find_root(Path.cwd())
SEMI = ROOT / "Data" / "processed" / "semi-structured"
OUT = SEMI / "synthetic"
SEED = 42

SIZE_TYPE = {("Dry", 20): "22G1", ("Dry", 40): "42G1", ("Reefer", 20): "22R1", ("Reefer", 40): "42R1",
             ("Open Top", 20): "22U1", ("Open Top", 40): "42U1", ("Flat Rack", 20): "22P1", ("Flat Rack", 40): "42P1"}
TARE_KG = {20: 2200, 40: 3750}
FULL_KG = {20: (8_000, 24_000), 40: (10_000, 28_000)}
SENDER, RECIPIENT = "NILEGATE", "NGCARRIER"

REVIEWED_3 = {"messages": 434, "containers_once": True, "imo_matches_container_vessel": True,  # reviewed 2026-09-27
              "locodes_in_ports": True, "voyage_matches_ais": True, "with_invoice_ref": 376, "invoice_matches_vessel": True,
              "without_seal_all_empty": 24}
REVIEWED_4 = {"edi_messages_synthetic.jsonl": {  # reviewed 2026-09-28 (sea-path voyages, RFF+IV restored)
    "rows": 434, "sha256": "dfa04b1d8eca277d961ed5f7dae014293fbbca85f3ab0ad6d4ad4d35d02ee3ee"}}
REVIEWED_FINAL = {"messages": 434, "containers": 1000, "with_invoice_ref": 376, "problems": 0,  # reviewed 2026-09-27
                  "artifact_sha256": "dfa04b1d8eca277d961ed5f7dae014293fbbca85f3ab0ad6d4ad4d35d02ee3ee"}


def load_env() -> None:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def pg_frame(conn, sql: str) -> pd.DataFrame:
    cur = conn.execute(sql)
    return pd.DataFrame(cur.fetchall(), columns=[d.name for d in cur.description])


# ---------------------------------------------------------------------------------------------------- phase 1

def load_inputs() -> dict:
    env = os.environ
    with psycopg.connect(host=env["PGHOST"], port=env["PGPORT"], dbname=env["PGDATABASE"], user=env["PGUSER"],
                         password=env["PGPASSWORD"], options="-c default_transaction_read_only=on") as conn:
        containers = pg_frame(conn, "SELECT container_id, container_number, container_type, size_ft, status, vessel_id, "
                                    "origin_locode, destination_locode FROM containers ORDER BY container_id")
        vessels = pg_frame(conn, "SELECT vessel_id, imo_number, mmsi, vessel_name, origin_locode, destination_locode "
                                 "FROM vessels ORDER BY vessel_id")
        invoices = pg_frame(conn, "SELECT invoice_number, vessel_id, invoice_date FROM invoices ORDER BY invoice_id")
        port_codes = set(pg_frame(conn, "SELECT locode FROM ports")["locode"])
    voyages = pd.read_parquet(OUT / "voyages_synthetic.parquet")
    template = json.loads((SEMI / "profiles" / "iftmin_template.json").read_text(encoding="utf-8"))
    ais_manifest = json.loads((OUT / "ais_generation_manifest.json").read_text(encoding="utf-8"))
    print("containers:", len(containers), "| vessels:", len(vessels), "| invoices:", len(invoices), "| voyages:", len(voyages))
    print("template tags:", [s["tag"] for s in template["segments"]])

    assert len(containers) == 1000 and len(vessels) == 500 and len(voyages) == 500
    assert template["message_type"] == "IFTMIN:D:12A:UN"
    merged = containers.merge(vessels, on="vessel_id", suffixes=("", "_v"))
    assert (merged["origin_locode"] == merged["origin_locode_v"]).all() and (merged["destination_locode"] == merged["destination_locode_v"]).all()
    print("✅ Phase 1 validation passed.")
    return {"containers": containers, "vessels": vessels, "invoices": invoices, "port_codes": port_codes,
            "voyages": voyages, "template": template, "ais_manifest": ais_manifest}


# ---------------------------------------------------------------------------------------------------- phase 2

def esc(text: str) -> str:
    return re.sub(r"([?'+:])", r"?\1", str(text))


def seg(*elements) -> str:
    """One segment: elements are strings or lists of components (already escaped where needed)."""
    return "+".join(":".join(e) if isinstance(e, (list, tuple)) else e for e in elements).rstrip("+") + "'"


class MessageBuilder:
    """Builds the IFTMIN text of one vessel's containers and the keys it must parse back to."""

    def __init__(self, vessels: pd.DataFrame, voyages: pd.DataFrame, invoices: pd.DataFrame):
        self.latest_invoice = invoices.sort_values(["vessel_id", "invoice_date", "invoice_number"]) \
            .groupby("vessel_id").tail(1).set_index("vessel_id")["invoice_number"]
        self.vv = vessels.set_index("vessel_id")
        self.voy = voyages.set_index("vessel_id")

    def build(self, k: int, vessel_id: int, boxes: pd.DataFrame) -> tuple[str, dict]:
        rng = np.random.default_rng([SEED, vessel_id])
        v, w = self.vv.loc[vessel_id], self.voy.loc[vessel_id]
        ref = f"{k:06d}"
        doc_ts = pd.Timestamp(w["departure_ts"]) - timedelta(days=2)
        arr_ts = pd.Timestamp(w["arrival_ts"])
        o, d = v["origin_locode"], v["destination_locode"]
        weights = [TARE_KG[b.size_ft] if b.status == "Empty" else int(round(rng.uniform(*FULL_KG[b.size_ft]), -1))
                   for b in boxes.itertuples()]
        lines = ["UNA:+.? '",
                 seg("UNB", ["UNOC", "3"], SENDER, RECIPIENT, [doc_ts.strftime("%y%m%d"), doc_ts.strftime("%H%M")], ref),
                 seg("UNH", ref, ["IFTMIN", "D", "12A", "UN"]),
                 seg("BGM", "610", f"IFT-{doc_ts:%Y%m%d}-{ref[-4:]}", "9"),
                 seg("DTM", ["137", doc_ts.strftime("%Y%m%d"), "102"]),
                 seg("FTX", "AAI", "", "", "Transport instruction for containerized sea freight")]
        if vessel_id in self.latest_invoice.index:
            lines.append(seg("RFF", ["IV", esc(self.latest_invoice[vessel_id])]))
        lines += [seg("NAD", "CZ", [f"{o[:2]}SHIP", "160", "ZZZ"]),
                  seg("NAD", "CN", [f"{d[:2]}RECV", "160", "ZZZ"]),
                  seg("LOC", "9", [o, "139", "6"]),
                  seg("LOC", "11", [d, "139", "6"]),
                  seg("TDT", "20", esc(w["voyage_no"]), "1", "", [RECIPIENT, "172", "ZZZ"], "", "",
                      [v["imo_number"], "146", "11", esc(v["vessel_name"])]),
                  seg("DTM", ["132", arr_ts.strftime("%Y%m%d"), "102"]),
                  seg("GID", "1", [str(len(boxes)), "CN"]),
                  seg("FTX", "AAA", "", "", "Containerized cargo - synthetic"),
                  seg("MEA", "AAE", "G", ["KGM", str(sum(weights))])]
        for b in boxes.itertuples():
            lines.append(seg("EQD", "CN", b.container_number, [SIZE_TYPE[(b.container_type, b.size_ft)], "102", "5"], "",
                             "2", "4" if b.status == "Empty" else "5"))
            if b.status != "Empty":
                lines.append(seg("SEL", [f"NG{int(rng.integers(0, 1_000_000)):06d}", "CA"]))
        n_msg = len(lines) - 2 + 1  # UNH..UNT inclusive: everything after UNA and UNB, plus UNT itself
        lines += [seg("UNT", str(n_msg), ref), seg("UNZ", "1", ref)]
        expect = {"interchange_ref": ref, "message_ref": ref, "vessel_imo": v["imo_number"], "voyage": w["voyage_no"],
                  "locodes": {"9": o, "11": d}, "container_numbers": boxes["container_number"].tolist(),
                  "invoice_number": self.latest_invoice.get(vessel_id), "dates": {"137": doc_ts.strftime("%Y%m%d"),
                                                                                 "132": arr_ts.strftime("%Y%m%d")},
                  "gross_kg": sum(weights)}
        return "\n".join(lines) + "\n", expect


def build_messages(inputs: dict, builder: MessageBuilder):
    containers = inputs["containers"]
    groups = containers.groupby("vessel_id", sort=True)
    messages = [builder.build(k, vid, boxes) for k, (vid, boxes) in enumerate(groups, start=1)]
    print("messages:", len(messages), "| containers:", sum(len(e["container_numbers"]) for _, e in messages))
    print(messages[0][0])

    assert len(messages) == containers["vessel_id"].nunique() == 434
    assert esc("O'Neil+1:2?") == "O?'Neil?+1?:2??"
    assert set(SIZE_TYPE) == set(zip(containers["container_type"], containers["size_ft"])) | set(SIZE_TYPE)
    assert all(raw.startswith("UNA:+.? '\nUNB+UNOC:3+") and raw.rstrip().endswith("'") for raw, _ in messages)
    assert [e["interchange_ref"] for _, e in messages] == [f"{k:06d}" for k in range(1, 435)]
    print("✅ Phase 2 validation passed.")
    return messages, [int(vid) for vid, _ in groups]


# ---------------------------------------------------------------------------------------------------- phase 3
# Every message is parsed back with the tokenizer validated by AIS_EDI_profiling (copied here) and must give back the
# keys it was built from; then the envelope (UNT count, matching references), the template order, and the consistency
# rules: every IMO, UN/LOCODE and container number exists in PostgreSQL and matches (container → vessel → IMO), every
# container appears in exactly one message, and the voyage number and dates are the AIS voyage's.

def edi_tokenize(text: str):
    text = text.replace("\r", "").replace("\n", "")
    seps = {"comp": ":", "elem": "+", "dec": ".", "rel": "?", "seg": "'"}
    if text.startswith("UNA"):
        seps = dict(zip(["comp", "elem", "dec", "rel", "_reserved", "seg"], text[3:9]))
        seps.pop("_reserved")
        text = text[9:]
    segments, sg, elem, comp, i = [], [], [], [], 0
    while i < len(text):
        ch = text[i]
        if ch == seps["rel"] and i + 1 < len(text):
            comp.append(text[i + 1]); i += 2; continue
        if ch == seps["comp"]:
            elem.append("".join(comp)); comp = []
        elif ch == seps["elem"]:
            elem.append("".join(comp)); sg.append(elem); elem, comp = [], []
        elif ch == seps["seg"]:
            elem.append("".join(comp)); sg.append(elem); segments.append(sg); sg, elem, comp = [], [], []
        else:
            comp.append(ch)
        i += 1
    assert not (sg or elem or comp), "text after the last segment terminator"
    return seps, segments


def el(s, e, c=0, default=""):
    return s[e][c] if e < len(s) and c < len(s[e]) else default


def parse_keys(raw: str) -> dict:
    _, segs = edi_tokenize(raw)
    tags = [el(s, 0) for s in segs]
    by = {t: [s for s in segs if el(s, 0) == t] for t in dict.fromkeys(tags)}
    unb, unh, unt, unz = (segs[tags.index(t)] for t in ("UNB", "UNH", "UNT", "UNZ"))
    tdt = by["TDT"][0]
    return {"interchange_ref": el(unb, 5), "message_ref": el(unh, 1), "vessel_imo": el(tdt, 8, 0), "voyage": el(tdt, 2),
            "locodes": {el(s, 1): el(s, 2) for s in by["LOC"]},
            "container_numbers": [el(s, 2) for s in by["EQD"] if el(s, 1) == "CN"],
            "invoice_number": {el(s, 1, 0): el(s, 1, 1) for s in by.get("RFF", [])}.get("IV"),
            "dates": {el(s, 1, 0): el(s, 1, 1) for s in by["DTM"]},
            "gross_kg": int(el(by["MEA"][0], 3, 1)),
            "_unt_ok": int(el(unt, 1)) == tags.index("UNT") - tags.index("UNH") + 1,
            "_refs_ok": el(unh, 1) == el(unt, 2) and el(unb, 5) == el(unz, 2) and el(unz, 1) == "1",
            "_tags": tags}


def check_messages(messages, inputs: dict, builder: MessageBuilder):
    containers, invoices, port_codes = inputs["containers"], inputs["invoices"], inputs["port_codes"]
    template_order = [s["tag"] for s in inputs["template"]["segments"]]
    problems = []
    for raw, expect in messages:
        got = parse_keys(raw)
        if {k: got[k] for k in expect} != expect:
            problems.append((expect["message_ref"], "round trip"))
        if not (got["_unt_ok"] and got["_refs_ok"]):
            problems.append((expect["message_ref"], "envelope"))
        # template order: the distinct tags in first-appearance order equal the template's, RFF being the optional
        # addition and SEL absent by rule when every container of the message is empty (no seal on an empty box)
        first_seen = [t for t in dict.fromkeys(got["_tags"]) if t != "RFF"]
        all_empty = (containers.set_index("container_number").loc[expect["container_numbers"], "status"] == "Empty").all()
        expected_order = [t for t in dict.fromkeys(template_order) if not (t == "SEL" and all_empty)]
        if first_seen != expected_order:
            problems.append((expect["message_ref"], "template order"))
    all_boxes = [c for _, e in messages for c in e["container_numbers"]]
    cont_v = containers.set_index("container_number")["vessel_id"]
    imo_of = builder.vv["imo_number"]
    voy = builder.voy
    consistency = {
        "messages": len(messages), "containers_once": len(all_boxes) == len(set(all_boxes)) == len(containers),
        "imo_matches_container_vessel": all(imo_of[cont_v[c]] == e["vessel_imo"] for _, e in messages for c in e["container_numbers"]),
        "locodes_in_ports": all(set(e["locodes"].values()) <= port_codes for _, e in messages),
        "voyage_matches_ais": all(e["voyage"] == voy.loc[cont_v[e["container_numbers"][0]], "voyage_no"] for _, e in messages),
        "with_invoice_ref": sum(e["invoice_number"] is not None for _, e in messages),
        "invoice_matches_vessel": all(invoices.set_index("invoice_number").loc[e["invoice_number"], "vessel_id"]
                                      == cont_v[e["container_numbers"][0]] for _, e in messages if e["invoice_number"]),
        "without_seal_all_empty": sum("SEL" not in parse_keys(raw)["_tags"] for raw, _ in messages),
    }
    print("problems:", problems[:5], "| consistency:", consistency)

    assert not problems, problems[:10]
    assert consistency["containers_once"] and consistency["imo_matches_container_vessel"]
    assert consistency["locodes_in_ports"] and consistency["voyage_matches_ais"]
    assert all("MOA" not in parse_keys(raw)["_tags"] for raw, _ in messages), "D14: no amounts"
    assert consistency["invoice_matches_vessel"], "an invoice reference belongs to another vessel"
    assert consistency["with_invoice_ref"] == invoices["vessel_id"].isin(containers["vessel_id"]).groupby(invoices["vessel_id"]).any().sum()
    if REVIEWED_3:
        assert consistency == REVIEWED_3, f"EDI consistency changed: {consistency}"
    else:
        print("snapshot pending review:", json.dumps(consistency))
    print("✅ Phase 3 validation passed.")
    return problems, consistency, all_boxes


# ---------------------------------------------------------------------------------------------------- phase 4
# One JSON line per message (interchange_ref, vessel_id, raw): the loader stores the raw text exactly as generated and
# parses it with its own copy of the tokenizer; a manifest records the seed, the inputs and a content hash.

def save(messages, vessel_of_msg: list[int], inputs: dict) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"interchange_ref": e["interchange_ref"], "vessel_id": vid, "raw": raw}, ensure_ascii=False)
             for (raw, e), vid in zip(messages, vessel_of_msg)]
    payload = "\n".join(lines) + "\n"
    (OUT / "edi_messages_synthetic.jsonl").write_text(payload, encoding="utf-8", newline="\n")
    manifest = {"generator": "Notebooks/semi_structured/EDI_generator.ipynb", "seed": SEED,
                "inputs": {"containers": len(inputs["containers"]), "vessels": len(inputs["vessels"]),
                           "invoices": len(inputs["invoices"]),
                           "voyages_content_sha256":
                               inputs["ais_manifest"]["outputs"]["voyages_synthetic.parquet"]["content_sha256"],
                           "template": "profiles/iftmin_template.json"},
                "outputs": {"edi_messages_synthetic.jsonl": {"rows": len(lines),
                                                             "sha256": hashlib.sha256(payload.encode()).hexdigest()}}}
    (OUT / "edi_generation_manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")

    back = [json.loads(l) for l in (OUT / "edi_messages_synthetic.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [b["raw"] for b in back] == [raw for raw, _ in messages]
    assert hashlib.sha256((OUT / "edi_messages_synthetic.jsonl").read_bytes()).hexdigest() == \
        manifest["outputs"]["edi_messages_synthetic.jsonl"]["sha256"]
    if REVIEWED_4:
        assert manifest["outputs"] == REVIEWED_4, f"EDI artifact changed: {manifest['outputs']}"
    else:
        print("snapshot pending review:", json.dumps(manifest["outputs"]))
    print("✅ Phase 4 validation passed.")
    return manifest


def main() -> None:
    load_env()
    inputs = load_inputs()
    builder = MessageBuilder(inputs["vessels"], inputs["voyages"], inputs["invoices"])
    messages, vessel_of_msg = build_messages(inputs, builder)
    problems, consistency, all_boxes = check_messages(messages, inputs, builder)
    manifest = save(messages, vessel_of_msg, inputs)
    final = {"messages": len(messages), "containers": len(all_boxes), "with_invoice_ref": consistency["with_invoice_ref"],
             "problems": len(problems), "artifact_sha256": manifest["outputs"]["edi_messages_synthetic.jsonl"]["sha256"]}
    assert final == REVIEWED_FINAL, f"final summary changed: {final}"
    print(json.dumps(final, indent=1))
    print("✅ Final Checkpoint validation passed.")


if __name__ == "__main__":
    main()
