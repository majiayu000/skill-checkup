"""Turn session events into per-skill usage, split by how the skill was reached."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from .inventory import Skill
from .sessions import Session

CRITICAL_HINT = re.compile(
    r"doctor|deploy|release|rollback|incident|recover|restore|security|部署|发布|回滚|事故|故障|恢复|诊断|卡了|安全",
    re.I,
)
EXPLICIT_ONLY = re.compile(r"explicitly|只在.{0,6}明确|仅当用户明确|仅在用户明确|明确调用", re.I)


@dataclass
class Usage:
    uses: int = 0
    by_via: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    sessions: set[str] = field(default_factory=set)
    runtimes: set[str] = field(default_factory=set)
    by_runtime: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    read_roots: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))  # runtime -> folders read
    last: str = ""
    audit_reads: int = 0


def aggregate(sessions: list[Session]) -> dict[str, Usage]:
    out: dict[str, Usage] = defaultdict(Usage)
    for s in sessions:
        for e in s.events:
            if e[0] != "skill":
                continue
            u = out[e[2]]
            if e[3] == "audit":
                u.audit_reads += 1
                continue
            u.uses += 1
            u.by_via[e[3]] += 1
            u.sessions.add(s.sid)
            u.runtimes.add(s.runtime)
            u.by_runtime[s.runtime] += 1
            if len(e) > 4 and e[4]:
                u.read_roots[s.runtime].add(e[4])
            u.last = max(u.last, e[1] or "")
    return out


# Copies a person can delete without affecting the runtime that does use the skill. Plugin skills
# can't be removed one by one, and ~/.agents is also read by other agents, which the fix text says.
REMOVABLE_ROOTS = {"claude": {"claude", "project:.claude"}, "codex": {"agents", "codex", "project:.agents"}}
OTHER = {"claude": "codex", "codex": "claude"}


# The folder name a runtime's reads go through, for each removable root label.
ROOT_DIR = {"claude": "claude", "project:.claude": "claude", "agents": "agents", "codex": "codex",
            "project:.agents": "agents"}


@dataclass
class OneSided:
    skill: str
    idle_runtime: str  # loaded here, never used here
    busy_runtime: str
    busy_uses: int
    removable: list[str]  # root labels holding a copy only the idle runtime loads
    shared: bool = False  # the busy side reaches the same files (symlink or direct read): hide, don't delete


def one_sided(skills: dict[str, Skill], use: dict[str, Usage], min_uses: int = 3) -> list[OneSided]:
    """Skills loaded by both Claude Code and Codex but used by only one of them. The idle side
    still pays for the skill's description in every session."""
    out = []
    for name, s in skills.items():
        u = use.get(name)
        if not u or s.runtimes != {"claude", "codex"}:
            continue
        for idle, busy in OTHER.items():
            if u.by_runtime.get(idle, 0) == 0 and u.by_runtime.get(busy, 0) >= min_uses:
                idle_installs = [i for i in s.installs if i.root in REMOVABLE_ROOTS[idle]]
                if not idle_installs:
                    continue
                busy_reals = {i.real for i in s.installs if i.root not in REMOVABLE_ROOTS[idle]}
                # Deleting a symlink is harmless; deleting real files the busy side links to or reads is not.
                shared = any(not i.is_link and i.real in busy_reals for i in idle_installs) or any(
                    not i.is_link and ROOT_DIR[i.root] in u.read_roots.get(busy, set()) for i in idle_installs)
                out.append(OneSided(name, idle, busy, u.by_runtime[busy],
                                    sorted(i.root for i in idle_installs), shared))
    return sorted(out, key=lambda o: -o.busy_uses)


def tier(skill: Skill, u: Usage | None) -> str:
    """active / low / dormant-critical / unused."""
    uses = u.uses if u else 0
    if uses >= 3:
        return "active"
    if uses > 0:
        return "low"
    if CRITICAL_HINT.search(skill.name) or CRITICAL_HINT.search(skill.description):
        return "dormant-critical"
    return "unused"


def explicit_only(skill: Skill) -> bool:
    return bool(EXPLICIT_ONLY.search(skill.description))
