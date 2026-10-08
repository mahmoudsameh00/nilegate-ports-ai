"""Export a local embedding model to ONNX (fp32 + int8) for the upload path (RAG plan Phase 8 §d).

The project runtime needs only `onnxruntime` + `tokenizers`; torch / transformers are needed once, to export. So this
tool runs in a throwaway environment and adds no dependency to the project:

    uv run --no-project --with torch==2.9.0 --with transformers==4.57.1 --with onnx==1.19.1 \
        --with onnxruntime==1.30.0 --with safetensors==0.6.2 --with sentencepiece==0.2.1 \
        python tools/export_onnx.py <name>

(On this Windows machine `uv run --with` could not unpack sympy — a file lock in uv's build cache — so the same
packages were installed with `uv pip install` into a throwaway venv in the scratchpad, UV_LINK_MODE=copy, plus
`onnx-ir` for the quantizer.)

Models (MODELS below): the weights are read from models/hf/<name>/ (downloaded beforehand), written to
models/onnx/<name>/ (git-ignored): model.onnx (+ model.onnx.data when over 2 GB), model_int8.onnx and
model_int4.onnx (weight-only quantization of the MatMul weights, MatMulNBits, block 32, symmetric; activations stay
float), tokenizer.json and manifest.json (source, pooling, dimension, prefixes, max tokens, file hashes, and the
export check: the ONNX output equals the PyTorch output on sample sentences in English and Arabic, min cosine
>= 0.9999 fp32, >= 0.995 int8; int4 reported only). The fp32 export is kept between runs (`--reexport` redoes it).

No remote code is executed: the mesolitica model's custom class (`modeling.py`, trust_remote_code) is re-built here
from its published definition — a Llama encoder, a Linear(4096 -> 1536) applied to every token, mean pooling over the
attention mask, L2 normalization.
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import torch

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
MODELS = {
    "llama2-embedding-600m-8k": {"repo": "mesolitica/llama2-embedding-600m-8k", "kind": "llama_dense_mean",
                                 "dim": 1536, "max_tokens": 2048, "query_prefix": "", "passage_prefix": ""},
    "multilingual-e5-base": {"repo": "intfloat/multilingual-e5-base", "kind": "encoder_mean",
                             "dim": 768, "max_tokens": 512, "query_prefix": "query: ", "passage_prefix": "passage: "},
    # BGE-M3 dense output = the normalized [CLS] state (its sentence-transformers pooling config); no prefixes.
    # Weights are pytorch_model.bin: transformers loads it with torch.load(weights_only=True) (no code is unpickled).
    "bge-m3": {"repo": "BAAI/bge-m3", "kind": "encoder_cls", "dim": 1024, "max_tokens": 2048, "query_prefix": "",
               "passage_prefix": ""},
}
SAMPLES = ["Reefer containers are inspected before every loading.",
           "Customs hold release requires the broker's signed declaration.",
           "الحاويات المبردة بتتفحص قبل كل تحميل؟",
           "ما هي شروط الإفراج عن الشحنة المحجوزة في الجمارك؟"]


class Wrapped(torch.nn.Module):
    """input_ids, attention_mask -> L2-normalized sentence embedding [batch, dim]."""

    def __init__(self, encoder, dense=None, causal: bool = False, pooling: str = "mean"):
        super().__init__()
        self.encoder, self.dense, self.causal, self.pooling = encoder, dense, causal, pooling

    def forward(self, input_ids, attention_mask):
        mask = attention_mask
        if self.causal:
            # The 4D additive mask (causal AND not padding) built here: transformers >= 4.5x builds it with vmap,
            # which the ONNX exporter cannot trace, and uses a ready 4D mask as is. Same values as its own mask.
            s = attention_mask.shape[1]
            causal = torch.tril(torch.ones(s, s, dtype=torch.bool, device=input_ids.device))
            keep = causal[None, None, :, :] & attention_mask[:, None, None, :].bool()
            mask = torch.zeros(keep.shape, dtype=torch.float32).masked_fill(~keep, torch.finfo(torch.float32).min)
        h = self.encoder(input_ids=input_ids, attention_mask=mask).last_hidden_state
        if self.dense is not None:
            h = self.dense(h)                      # mesolitica: projection on every token, then pooling
        if self.pooling == "cls":
            pooled = h[:, 0]
        else:
            m = attention_mask.unsqueeze(-1).to(h.dtype)
            pooled = (h * m).sum(dim=1) / m.sum(dim=1).clamp(min=1e-9)
        return torch.nn.functional.normalize(pooled, dim=-1)


def build(name: str, spec: dict, src: Path):
    from transformers import AutoModel

    if spec["kind"] == "llama_dense_mean":
        from safetensors import safe_open
        from transformers import LlamaModel

        enc = LlamaModel.from_pretrained(src, attn_implementation="eager", torch_dtype=torch.float32)
        dense = torch.nn.Linear(enc.config.hidden_size, spec["dim"])
        with safe_open(src / "model.safetensors", "pt") as f:
            dense.weight.data = f.get_tensor("dense_layer.weight")
            dense.bias.data = f.get_tensor("dense_layer.bias")
        return Wrapped(enc, dense, causal=True).eval()
    enc = AutoModel.from_pretrained(src, attn_implementation="eager", torch_dtype=torch.float32)
    return Wrapped(enc, pooling="cls" if spec["kind"] == "encoder_cls" else "mean").eval()


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main(name: str) -> None:
    import onnx
    import onnxruntime as ort
    from onnxruntime.quantization import QuantType, quantize_dynamic
    from tokenizers import Tokenizer

    spec = MODELS[name]
    src, dst = ROOT / "models" / "hf" / name, ROOT / "models" / "onnx" / name
    dst.mkdir(parents=True, exist_ok=True)
    tok = Tokenizer.from_file(str(src / "tokenizer.json"))
    pad_id = tok.token_to_id("<pad>") if tok.token_to_id("<pad>") is not None else 0
    tok.enable_padding(pad_id=pad_id, pad_token=tok.id_to_token(pad_id), direction="right")
    tok.enable_truncation(spec["max_tokens"])
    enc = tok.encode_batch([spec["passage_prefix"] + s for s in SAMPLES])
    ids = torch.tensor([e.ids for e in enc], dtype=torch.int64)
    mask = torch.tensor([e.attention_mask for e in enc], dtype=torch.int64)

    model = build(name, spec, src)
    with torch.no_grad():
        ref = model(ids, mask).numpy()
        # the published model's own path (transformers builds the mask from the 2D attention mask) must give the
        # same vectors as the export path with the hand-built 4D mask
        native = Wrapped(model.encoder, model.dense, causal=False, pooling=model.pooling).eval()(ids, mask).numpy()
    same = float((ref * native).sum(axis=1).min())
    print(f"torch output {ref.shape}, norms {np.linalg.norm(ref, axis=1).round(4).tolist()}, "
          f"min cosine to the native mask path {same:.6f}")
    assert same >= 0.99999, "the export wrapper changes the model's output"

    fp32 = dst / "model.onnx"
    if fp32.exists() and "--reexport" not in sys.argv:
        print("fp32 export kept (pass --reexport to redo it)")
    else:
        for old in dst.iterdir():
            if old.suffix != ".json":
                old.unlink()
        torch.onnx.export(model, (ids, mask), str(fp32), input_names=["input_ids", "attention_mask"],
                          output_names=["embedding"], opset_version=17, dynamo=False,
                          dynamic_axes={"input_ids": {0: "batch", 1: "seq"},
                                        "attention_mask": {0: "batch", 1: "seq"}, "embedding": {0: "batch"}})
        big = len([f for f in dst.iterdir() if f.suffix != ".json"]) > 1
        if big:  # protobuf's 2 GB limit: torch wrote one file per tensor; gather them into one external data file
            m = onnx.load(str(fp32))
            for f in dst.iterdir():
                if f.suffix != ".json":
                    f.unlink()
            onnx.save_model(m, str(fp32), save_as_external_data=True, all_tensors_to_one_file=True,
                            location="model.onnx.data", size_threshold=1024)
        print(f"fp32 exported ({'external data' if big else 'single file'})")

    # Weight-only quantization of the MatMul weights (MatMulNBits): activations stay float. The usual dynamic int8
    # quantization (weights AND activations) was measured on the Llama model at min cosine 0.809 to torch: its
    # activations have outliers that 8-bit activation scales cannot hold (2026-10-08).
    from onnxruntime.quantization.matmul_nbits_quantizer import MatMulNBitsQuantizer

    variants = {}
    for bits in (8, 4):
        out = dst / f"model_int{bits}.onnx"
        q = MatMulNBitsQuantizer(onnx.load(str(fp32)), bits=bits, block_size=32, is_symmetric=True)
        q.process()
        q.model.save_model_to_file(str(out), use_external_data_format=False)
        variants[f"int{bits}"] = out
    shutil.copy(src / "tokenizer.json", dst / "tokenizer.json")

    check = {}
    feeds = {"input_ids": ids.numpy(), "attention_mask": mask.numpy()}
    # int4 is reported, not required (bge-m3: 0.952): its retrieval quality is judged by Upload_eval.py
    for label, path, floor in (("fp32", fp32, 0.9999), ("int8", variants["int8"], 0.995),
                               ("int4", variants["int4"], 0.0)):
        sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        out = sess.run(None, feeds)[0]
        cos = (out * ref).sum(axis=1) / (np.linalg.norm(out, axis=1) * np.linalg.norm(ref, axis=1))
        check[label] = round(float(cos.min()), 6)
        assert cos.min() >= floor, f"{label}: min cosine to torch {cos.min():.6f} < {floor}"
    print(f"export check (min cosine to torch): {check}")

    files = {f.name: {"bytes": f.stat().st_size, "sha256": sha256(f)} for f in sorted(dst.iterdir())
             if f.name != "manifest.json"}
    meta = src / ".cache" / "huggingface" / "download" / "config.json.metadata"  # huggingface_hub local_dir record
    revision = meta.read_text().splitlines()[0].strip() if meta.exists() else None
    manifest = {"name": name, **spec, "pad_id": pad_id, "padding": "right", "export_check_min_cosine": check,
                "samples": SAMPLES, "files": files, "exported_with": {"torch": torch.__version__,
                                                                      "onnx": onnx.__version__,
                                                                      "onnxruntime": ort.__version__},
                "source_revision": revision}
    (dst / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✅ {name}: {', '.join(f'{k} {v['bytes'] / 2**20:.0f} MB' for k, v in files.items())}")


if __name__ == "__main__":
    main(sys.argv[1])
