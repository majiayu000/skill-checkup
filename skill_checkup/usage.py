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
            u.last = max(u.last, e[1] or "")
    return out


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
