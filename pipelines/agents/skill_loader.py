"""Agent Skills loader (Agents plan §3 "Skills", D13, §5a P4-8): `pipelines/agents/skills/<name>/SKILL.md`.

A skill = a flat YAML-style frontmatter (`name`, `description`, `stage`, `reviewed_by_owner`) between `---` lines and
a Markdown body of instructions; optional `references/*.md` loaded only on request. No scripts, no other files.
Budgets (free tiers are small: Groq 8K TPM): description ≤ DESCRIPTION_MAX chars (always visible to the supervisor),
body ≤ BODY_MAX_TOKENS (`est_tokens`, the conservative estimate of the embedding budget). A broken skill raises
SkillError at load time, never a silent half-prompt.

- Workflow nodes load their fixed skill: `load(name)` (no discovery call).
- The Q&A supervisor sees `descriptions()` and gets the `load_skill` tool.
Named `skill_loader` (not `skills`) so the module never shadows the `skills/` folder.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

from langchain.tools import tool
from pydantic import BaseModel, Field

from pipelines.lib.embeddings import est_tokens

SKILLS_DIR = Path(__file__).resolve().parent / "skills"
DESCRIPTION_MAX = 250
BODY_MAX_TOKENS = 1_200
KEYS = {"name", "description", "stage", "reviewed_by_owner"}
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class SkillError(ValueError):
    pass


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    stage: str
    reviewed_by_owner: str
    body: str
    path: Path
    references: tuple[str, ...] = field(default=())

    @property
    def body_tokens(self) -> int:
        return est_tokens(self.body)


def parse(folder: Path) -> Skill:
    path = folder / "SKILL.md"
    if not path.is_file():
        raise SkillError(f"{folder.name}: no SKILL.md")
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text.replace("\r\n", "\n"), re.S)
    if not m:
        raise SkillError(f"{folder.name}: SKILL.md must start with a --- frontmatter --- block")
    meta = {}
    for line in m.group(1).splitlines():
        if not line.strip():
            continue
        if ":" not in line:
            raise SkillError(f"{folder.name}: frontmatter line without 'key: value': {line!r}")
        k, v = line.split(":", 1)
        meta[k.strip()] = v.strip()
    if set(meta) != KEYS:
        raise SkillError(f"{folder.name}: frontmatter keys {sorted(meta)} != {sorted(KEYS)}")
    if meta["name"] != folder.name or not NAME_RE.match(meta["name"]):
        raise SkillError(f"{folder.name}: name must equal the folder name (lowercase-hyphen)")
    if not 20 <= len(meta["description"]) <= DESCRIPTION_MAX:
        raise SkillError(f"{folder.name}: description must be 20–{DESCRIPTION_MAX} chars")
    if meta["stage"] not in {"1", "2"}:
        raise SkillError(f"{folder.name}: stage must be 1 or 2")
    if not re.match(r"^(no|\d{4}-\d{2}-\d{2})$", meta["reviewed_by_owner"]):
        raise SkillError(f"{folder.name}: reviewed_by_owner must be 'no' or a date")
    body = m.group(2).strip()
    if not body:
        raise SkillError(f"{folder.name}: empty body")
    if est_tokens(body) > BODY_MAX_TOKENS:
        raise SkillError(f"{folder.name}: body {est_tokens(body)} tokens > {BODY_MAX_TOKENS}")
    extra = [p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()
             and p != path and not (p.parent.name == "references" and p.suffix == ".md")]
    if extra:
        raise SkillError(f"{folder.name}: only SKILL.md and references/*.md are allowed, found {extra}")
    refs = tuple(sorted(p.stem for p in (folder / "references").glob("*.md")))
    return Skill(meta["name"], meta["description"], meta["stage"], meta["reviewed_by_owner"], body, path, refs)


_catalog: dict[str, Skill] | None = None


def catalog(folder: Path = SKILLS_DIR) -> dict[str, Skill]:
    global _catalog
    if _catalog is None or folder != SKILLS_DIR:
        skills = {p.name: parse(p) for p in sorted(folder.iterdir()) if p.is_dir() and not p.name.startswith(("_",
                                                                                                             "."))}
        if folder != SKILLS_DIR:
            return skills
        _catalog = skills
    return _catalog


def load(name: str) -> str:
    """The body of one skill, for a workflow node's prompt."""
    skills = catalog()
    if name not in skills:
        raise SkillError(f"unknown skill {name!r}; available: {sorted(skills)}")
    return skills[name].body


def load_reference(name: str, reference: str) -> str:
    s = catalog()[name]
    if reference not in s.references:
        raise SkillError(f"{name}: no reference {reference!r}; available: {list(s.references)}")
    return (s.path.parent / "references" / f"{reference}.md").read_text(encoding="utf-8")


def descriptions(stage: str | None = None) -> str:
    """One line per skill for the supervisor's prompt."""
    return "\n".join(f"- {s.name}: {s.description}" for s in catalog().values() if stage in (None, s.stage))


class LoadSkillArgs(BaseModel):
    name: str = Field(description="the skill's name, as listed in the available skills")


@tool("load_skill", args_schema=LoadSkillArgs)
def load_skill_tool(name: str) -> str:
    """Load the full instructions of one skill (a procedure or company knowledge) before doing that kind of task."""
    try:
        return load(name)
    except SkillError as exc:
        return f"error: {exc}"
