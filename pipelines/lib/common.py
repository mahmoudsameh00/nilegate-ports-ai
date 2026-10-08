"""Project root, `.env` loading and secret redaction, shared by the retrieval scripts."""
import os
import re
from pathlib import Path

SECRET_KEYS = ("JINA_API_KEY", "VOYAGE_API_KEY", "GEMINI_API_KEY", "QDRANT_API_KEY",
               "PGPASSWORD", "PG_RO_PASSWORD", "MONGO_ROOT_PASSWORD", "MONGO_APP_PASSWORD")


def project_root(start: Path | None = None) -> Path:
    """The folder that holds pyproject.toml and Data/, searched upward from `start` (default: the working dir)."""
    start = start or Path.cwd()
    return next(p for p in [start, *start.parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())


def load_env(root: Path | None = None) -> None:
    """KEY=VALUE lines of the project's .env into os.environ (variables already set win)."""
    for line in ((root or project_root()) / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def redact(text: str) -> str:
    """Replace every known secret value, and anything shaped like key=<long token>, with ***."""
    for k in SECRET_KEYS:
        v = os.environ.get(k, "")
        if len(v) >= 8:
            text = text.replace(v, "***")
    return re.sub(r"(?i)(key[=:]\s*)[A-Za-z0-9_\-\.]{8,}", r"\1***", text)
