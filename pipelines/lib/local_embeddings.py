"""Local embedding model on ONNX Runtime for uploads that may hold non-public data (RAG plan Phase 8 §d; ADR-037:
never send non-public or personal data to Gemini's free tier). The text never leaves the machine.

A model folder `models/onnx/<name>/` (git-ignored, built by `tools/export_onnx.py`) holds `model.onnx` /
`model_int8.onnx`, `tokenizer.json` and `manifest.json` (pooling is inside the graph: the output is the normalized
sentence embedding). Runtime settings are measured by `Upload_eval.py` and fixed in DEFAULTS.
"""
import json
import os
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

from pipelines.lib.common import project_root

MODELS_DIR = project_root() / "models" / "onnx"
# Measured defaults (Upload_eval.py); overridable per call. Batches are sorted by length so padding stays small.
# 2026-10-08, i7-9750H (6 cores / 12 threads), bge-m3 fp32 (the session-lane model), 32 chunks: 12 threads 4.6-4.9 s
# (batch 1 / 8 within 6 %), a question 60-65 ms; weight-only int8 / int4 are smaller but slower on this CPU. DirectML
# (GTX 1660 Ti, measured in a throwaway venv): the 32 chunks in 1.1 s (6x), identical vectors, but a single question
# 107 ms; adopting it means replacing `onnxruntime` by `onnxruntime-directml` for the whole project (owner decision).
# Threads = physical cores: on a quiet machine 12 logical threads were ~5 % faster than 6, on a busy one (an editor
# indexing the project) 12 threads were 30 % slower (8.4 s vs 6.5 s, contention); 6 is near the best in both.
DEFAULTS = {"precision": "fp32", "threads": max(1, (os.cpu_count() or 2) // 2), "batch_size": 8,
            "providers": ["CPUExecutionProvider"]}


class LocalEmbedder:
    """`embed(texts, kind)` -> float32 [n, dim], L2-normalized; kind = "query" | "passage" (model prefixes)."""

    def __init__(self, name: str, precision: str | None = None, threads: int | None = None,
                 batch_size: int | None = None, providers: list | None = None):
        folder = MODELS_DIR / name
        if not (folder / "manifest.json").exists():
            raise FileNotFoundError(f"local model {name} is not exported: run tools/export_onnx.py {name}")
        self.name = name
        self.manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        self.precision = precision or DEFAULTS["precision"]
        self.batch_size = batch_size or DEFAULTS["batch_size"]
        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        so.intra_op_num_threads = threads or DEFAULTS["threads"]
        so.inter_op_num_threads = 1
        so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        so.log_severity_level = 3
        assert self.precision in ("fp32", "int8", "int4"), self.precision
        path = folder / ("model.onnx" if self.precision == "fp32" else f"model_{self.precision}.onnx")
        t0 = time.perf_counter()
        self.session = ort.InferenceSession(str(path), sess_options=so,
                                            providers=providers or DEFAULTS["providers"])
        self.load_ms = (time.perf_counter() - t0) * 1000
        self.tok = Tokenizer.from_file(str(folder / "tokenizer.json"))
        self.tok.enable_truncation(self.manifest["max_tokens"])
        self.tok.no_padding()
        self.dim = self.manifest["dim"]
        self.calls = 0
        self.truncated = 0

    def embed(self, texts: list[str], kind: str = "passage") -> np.ndarray:
        prefix = self.manifest["query_prefix"] if kind == "query" else self.manifest["passage_prefix"]
        enc = self.tok.encode_batch([prefix + t for t in texts])
        self.truncated += sum(1 for e in enc if e.overflowing)
        order = np.argsort([len(e.ids) for e in enc])
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        pad = self.manifest["pad_id"]
        for i in range(0, len(order), self.batch_size):
            idx = order[i:i + self.batch_size]
            width = max(len(enc[j].ids) for j in idx)
            ids = np.full((len(idx), width), pad, dtype=np.int64)
            mask = np.zeros((len(idx), width), dtype=np.int64)
            for r, j in enumerate(idx):  # right padding, as at export
                n = len(enc[j].ids)
                ids[r, :n], mask[r, :n] = enc[j].ids, 1
            out[idx] = self.session.run(None, {"input_ids": ids, "attention_mask": mask})[0]
            self.calls += 1
        return out


_loaded: dict = {}


def get(name: str, **settings) -> LocalEmbedder:
    """One loaded model per (name, settings) per process: loading takes seconds, a query milliseconds."""
    key = (name, repr(sorted(settings.items())))
    if key not in _loaded:
        _loaded[key] = LocalEmbedder(name, **settings)
    return _loaded[key]
