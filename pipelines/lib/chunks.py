"""The chunk layer contract (ARCHITECTURE §5, ADR-009, ADR-041): 16 columns, integer sensitivity level 1-3,
departments that exist, MIN / MAX lengths, and ONE title / text rule for the whole corpus:

- `title` = the chunk's full location label (document, section path, caption, clause number, ...);
- `text`  = the body only: it never starts with its heading (no header line, no repeated caption / clause title);
- the unit that is embedded and handed to a model is `compose(title, text)` = title + "\\n" + text, built only here.

`split_heading` moves a leading heading out of `text` (the owning chunking scripts call `normalize_chunk_file` as
their last phase); `check` refuses a corpus where any chunk still has one. Used by every reader of the chunk files and
by the PDF ingestion script before anything is embedded or loaded.
"""
import re
from pathlib import Path

import pandas as pd

COLUMNS = ["page", "unit_type", "logical_unit", "chunk_id", "parent_chunk", "sub_chunk", "title", "text",
           "char_count", "filename", "source", "real_or_synthetic", "document_type", "department",
           "sensitivity_level", "version_date"]
REQUIRED = ["unit_type", "logical_unit", "chunk_id", "title", "text", "char_count", "filename", "source",
            "real_or_synthetic", "document_type", "department", "sensitivity_level"]  # never null
DEPARTMENTS = {"Operations", "Customs", "Finance", "HR", "IT"}  # rows of `departments` (ARCHITECTURE §4)
MIN_CHARS, MAX_CHARS = 50, 2000  # composed unit >= 50 characters; text <= 2,000 (the safety cap)
# Header lines composed by the chunking scripts (ADR-023 IMO document path, ADR-024 USCG header): always a heading.
HEADER_PREFIXES = ("USCG ROI ", "IMO MSC-MEPC.3/Circ.4/Rev.1, annex — ")
LABEL_SLACK = 12  # letters a heading line may add to its title: "Table", "Figure 2.3", a clause number "17"


def _letters(s: str | None) -> str:
    return re.sub(r"[^0-9a-z]", "", (s or "").lower())


def compose(title: str, text: str) -> str:
    """The one way a chunk becomes a single string (embedding input, context for a model, fact judging)."""
    return f"{title}\n{text}"


def split_heading(title: str, text: str) -> tuple[str, str, str]:
    """(title, text, kind) with a leading heading moved out of the text. Kinds:
    - header_line:    the first line is a composed header (USCG, IMO annex) -> it becomes the title;
    - heading_line:   the first line is the title, possibly with a label or number ("Table: <title>",
                      "17. <title>") -> it becomes the title (it carries more than the old title, never less);
    - run_in_heading: the text starts with "<title>. " (a heading run into the first sentence) -> removed;
    - unchanged:      anything else, including prose that merely starts with the title's words ("Road
                      infrastructure plays ..." under the title "Road"): content is preserved.
    Lossless by construction: the old text equals new_title + "\\n" (or ". ") + new text, up to whitespace."""
    first, sep, rest = text.partition("\n")
    if sep and rest.strip():
        if first.startswith(HEADER_PREFIXES):
            return first.strip(), rest.lstrip(), "header_line"
        lf, lt = _letters(first), _letters(title)
        if lt and lf.endswith(lt) and len(lf) - len(lt) <= LABEL_SLACK:
            return first.strip(), rest.lstrip(), "heading_line"
    if title and text.startswith(title + ". "):
        return title, text[len(title) + 2:].lstrip(), "run_in_heading"
    return title, text, "unchanged"


def normalize(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Apply split_heading to every chunk; prove it lossless and idempotent; recompute char_count.
    Chunk ids, order and every other column are unchanged."""
    out = df.copy()
    kinds = {}
    titles, texts = [], []
    for t, x in zip(df["title"], df["text"]):
        nt, nx, k = split_heading(t, x)
        sep = ". " if k == "run_in_heading" else "\n"
        assert " ".join((nt + sep + nx).split()) == " ".join(x.split()) or k == "unchanged", f"lossy split: {t!r}"
        assert split_heading(nt, nx)[2] == "unchanged", f"not idempotent: {t!r}"
        kinds[k] = kinds.get(k, 0) + 1
        titles.append(nt)
        texts.append(nx)
    out["title"] = pd.Series(titles, index=df.index, dtype=df["title"].dtype)
    out["text"] = pd.Series(texts, index=df.index, dtype=df["text"].dtype)
    out["char_count"] = pd.array(out["text"].str.len(), dtype="Int64")
    untouched = [c for c in COLUMNS if c not in ("title", "text", "char_count")]
    assert out[untouched].equals(df[untouched]), "normalization may change title / text / char_count only"
    return out, dict(sorted(kinds.items()))


def normalize_chunk_file(path: Path, reviewed: dict) -> dict:
    """The last phase of an owning chunking script (ADR-041): normalize its saved chunk file in place, assert the
    reviewed counts, the contract, and an exact reload. Returns the counts."""
    df = pd.read_parquet(path)
    norm, kinds = normalize(df)
    assert kinds == reviewed, f"{path.name}: normalization counts {kinds} != reviewed {reviewed}"
    check(norm)
    norm.to_parquet(path, index=False)
    back = pd.read_parquet(path)
    assert list(back.columns) == COLUMNS and back.dtypes.astype(str).equals(df.dtypes.astype(str))
    for c in COLUMNS:
        assert [plain_value(v) for v in back[c]] == [plain_value(v) for v in norm[c]], f"{path.name}: {c} changed on disk"
    return kinds


def plain_value(v):
    """A comparable plain value: NA -> None, arrays / lists (sub_chunk) -> list, numpy scalars -> Python."""
    if v is None or v is pd.NA or (isinstance(v, float) and v != v):
        return None
    if hasattr(v, "tolist") and not isinstance(v, str):
        return v.tolist()
    return v


def load(chunk_dir: Path) -> pd.DataFrame:
    """All chunk files of a folder, concatenated in file-name order, then checked."""
    files = sorted(chunk_dir.glob("*.parquet"))
    assert files, f"no chunk files in {chunk_dir}"
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    check(df)
    return df


def check(df: pd.DataFrame, departments: set[str] = DEPARTMENTS) -> dict:
    """Assert the contract; return a small summary (counts) for the caller's reviewed snapshot."""
    assert list(df.columns) == COLUMNS, f"columns differ from the 16-column schema: {list(df.columns)}"
    nulls = {c: int(df[c].isna().sum()) for c in REQUIRED if df[c].isna().any()}
    assert not nulls, f"nulls in required columns: {nulls}"
    assert df.chunk_id.is_unique, "duplicate chunk_id"
    assert str(df.sensitivity_level.dtype) == "Int64" and df.sensitivity_level.between(1, 3).all(), \
        "sensitivity_level must be Int64 in 1-3"
    lengths = df.text.str.len()
    assert (df.char_count == lengths).all(), "char_count differs from len(text)"
    assert (lengths > 0).all() and (lengths <= MAX_CHARS).all(), f"text empty or over {MAX_CHARS} characters"
    composed = [len(compose(t, x)) for t, x in zip(df.title, df.text)]
    assert min(composed) >= MIN_CHARS, f"a composed chunk (title + text) is under {MIN_CHARS} characters"
    headed = [c for c, t, x in zip(df.chunk_id, df.title, df.text) if split_heading(t, x)[2] != "unchanged"]
    assert not headed, f"{len(headed)} chunks still start with their heading (ADR-041), e.g. {headed[:3]}"
    unknown = set(df.department) - departments
    assert not unknown, f"departments not in `departments`: {unknown}"
    assert set(df.real_or_synthetic) <= {"real", "synthetic"}
    return {"chunks": len(df), "files": int(df.filename.nunique()),
            "by_level": {int(k): int(v) for k, v in df.sensitivity_level.value_counts().sort_index().items()}}
