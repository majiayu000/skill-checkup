"""Discover installed skills across agent roots and parse their SKILL.md frontmatter."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

SKIP_DIRS = {"__pycache__", ".pytest_cache", "node_modules", ".git", ".venv"}


@dataclass(frozen=True)
class Root:
    label: str  # shown in reports, e.g. "claude", "project:.agents", "plugin:superpowers"
    path: Path
    runtimes: frozenset[str]  # which agents load skills from here: "claude", "codex"


def default_roots(home: Path | None = None, cwd: Path | None = None) -> list[Root]:
    """User roots, the current project's roots, and skills from enabled Claude Code plugins."""
    home = home or Path.home()
    roots = [
        Root("claude", home / ".claude" / "skills", frozenset({"claude"})),
        Root("agents", home / ".agents" / "skills", frozenset({"codex"})),
        Root("codex", home / ".codex" / "skills", frozenset({"codex"})),
    ]
    if cwd and cwd.resolve() != home.resolve():
        roots.append(Root("project:.claude", cwd / ".claude" / "skills", frozenset({"claude"})))
        roots.append(Root("project:.agents", cwd / ".agents" / "skills", frozenset({"codex"})))
    roots.extend(plugin_roots(home))
    return [r for r in roots if r.path.is_dir()]


def plugin_roots(home: Path) -> list[Root]:
    """Skills shipped by Claude Code plugins that are enabled in ~/.claude/settings.json."""
    try:
        settings = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
        installed = json.loads((home / ".claude" / "plugins" / "installed_plugins.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    enabled = {k for k, v in (settings.get("enabledPlugins") or {}).items() if v is True}
    out = []
    for key, entries in (installed.get("plugins") or {}).items():
        if key not in enabled or not isinstance(entries, list):
            continue
        for entry in entries:
            path = Path(entry.get("installPath", "")) / "skills"
            if entry.get("installPath") and path.is_dir():
                out.append(Root(f"plugin:{key.split('@')[0]}", path, frozenset({"claude"})))
                break
    return out


@dataclass
class Install:
    root: str
    runtimes: frozenset[str]
    path: Path  # path inside the root (may be a symlink)
    real: Path
    is_link: bool
    digest: str


@dataclass
class Skill:
    name: str
    description: str
    frontmatter: dict[str, str]
    body: str
    skill_md: Path
    installs: list[Install] = field(default_factory=list)
    problems: list[tuple[str, dict]] = field(default_factory=list)  # (code, params)

    @property
    def roots(self) -> list[str]:
        return [i.root for i in self.installs]

    @property
    def runtimes(self) -> set[str]:
        return set().union(*(i.runtimes for i in self.installs))

    @property
    def diverged(self) -> bool:
        """Several physical copies whose content differs (symlinks to one source don't count)."""
        return len({i.digest for i in self.installs}) > 1


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Minimal YAML subset: scalar keys, quoted strings and `>`/`|` blocks."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    head, body = text[3:end], text[end + 4 :].lstrip("\n")
    data: dict[str, str] = {}
    key, block, buf = None, False, []
    for line in head.splitlines():
        if block and (line.startswith((" ", "\t")) or not line.strip()):
            buf.append(line.strip())
            continue
        if block and key:
            data[key] = " ".join(x for x in buf if x)
            block, buf = False, []
        if ":" not in line or line.startswith((" ", "\t", "#")):
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if val in (">", "|", ">-", "|-", ">+", "|+"):
            block, buf = True, []
            continue
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        data[key] = val
    if block and key:
        data[key] = " ".join(x for x in buf if x)
    return data, body


def dir_digest(path: Path) -> str:
    h = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(path, followlinks=True):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if name.endswith(".pyc") or name == ".DS_Store":
                continue
            fp = Path(dirpath, name)
            h.update(str(fp.relative_to(path)).encode())
            try:
                h.update(fp.read_bytes())
            except OSError:
                h.update(b"<unreadable>")
    return h.hexdigest()[:16]


def discover(roots: list[Root]) -> dict[str, Skill]:
    skills: dict[str, Skill] = {}
    for root in roots:
        if not root.path.is_dir():
            continue
        plugin = root.label.startswith("plugin:")
        for entry in sorted(root.path.iterdir()):
            skill_md = entry / "SKILL.md"
            if entry.name.startswith(".") or not skill_md.is_file():
                continue
            try:
                text = skill_md.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            fm, body = parse_frontmatter(text)
            key = entry.name
            if plugin and key in skills and not skills[key].roots[0].startswith("plugin:"):
                key = f"{root.label[len('plugin:'):]}:{entry.name}"  # plugin copy shadowing a personal skill
            install = Install(
                root=root.label,
                runtimes=root.runtimes,
                path=entry,
                real=entry.resolve(),
                is_link=entry.is_symlink(),
                digest=dir_digest(entry.resolve()),
            )
            skill = skills.get(key)
            if skill is None:
                skill = Skill(name=key, description=fm.get("description", ""), frontmatter=fm,
                              body=body, skill_md=skill_md)
                skill.problems.extend(_frontmatter_problems(entry.name, fm.get("name") or entry.name, fm, text))
                skills[key] = skill
            skill.installs.append(install)
    return skills


def _frontmatter_problems(dirname: str, name: str, fm: dict[str, str], text: str) -> list[tuple[str, dict]]:
    """Checks from the agentskills.io SKILL.md spec."""
    if not text.startswith("---"):
        return [("fm_missing", {})]
    out = []
    if not fm.get("description"):
        out.append(("fm_no_description", {}))
    elif len(fm["description"]) > 1024:
        out.append(("fm_description_long", {"n": len(fm["description"])}))
    if name != dirname:
        out.append(("fm_name_mismatch", {"name": name, "dir": dirname}))
    if len(name) > 64:
        out.append(("fm_name_long", {}))
    return out
