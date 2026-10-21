"""How much context the skill listing costs, and which descriptions Claude Code will drop.

Documented Claude Code behaviour (code.claude.com/docs/en/skills, checked 2026-10-21):
- the listing budget is 1% of the model's context window (`skillListingBudgetFraction`
  or `SLASH_COMMAND_TOOL_CHAR_BUDGET` override it);
- every skill name is always listed, but descriptions are dropped starting with the
  least-invoked skills;
- description + when_to_use is cut at 1,536 characters per skill (`skillListingMaxDescChars`).
Skills from enabled Claude Code plugins are included; skills from MCP servers and other
sources are not, so the drop list is a lower bound.
"""

from __future__ import annotations

from dataclasses import dataclass

from .inventory import Skill
from .text import approx_tokens

PER_SKILL_CAP = 1536
FAT_CHARS = 500  # descriptions above this are the first place to trim

RUNTIMES = ("claude", "codex")


@dataclass
class Entry:
    skill: str
    chars: int
    tokens: int
    uses: int
    dropped: bool = False


@dataclass
class RuntimeBudget:
    runtime: str
    budget_chars: int
    total_chars: int
    entries: list[Entry]

    @property
    def dropped(self) -> list[Entry]:
        return [e for e in self.entries if e.dropped]


def listing_text(s: Skill) -> str:
    text = s.description
    if s.frontmatter.get("when_to_use"):
        text = f"{text} {s.frontmatter['when_to_use']}"
    return text[:PER_SKILL_CAP]


def analyze(skills: dict[str, Skill], uses: dict[str, int], budget_chars: int) -> list[RuntimeBudget]:
    out = []
    for runtime in RUNTIMES:
        visible = [s for s in skills.values() if runtime in s.runtimes]
        entries = [
            Entry(s.name, len(t), approx_tokens(t), uses.get(s.name, 0))
            for s in visible
            for t in [listing_text(s)]
        ]
        # Names are always listed; only descriptions compete for the budget.
        total = sum(e.chars for e in entries) + sum(len(e.skill) + 4 for e in entries)
        over = total - budget_chars
        if runtime == "claude" and over > 0:
            for e in sorted(entries, key=lambda e: (e.uses, -e.chars)):
                if over <= 0:
                    break
                e.dropped = True
                over -= e.chars
        out.append(RuntimeBudget(runtime, budget_chars, total, sorted(entries, key=lambda e: -e.chars)))
    return out


def fattest(skills: dict[str, Skill], limit: int = 12) -> list[tuple[str, int]]:
    ranked = sorted(((s.name, len(listing_text(s))) for s in skills.values()), key=lambda x: -x[1])
    return [r for r in ranked if r[1] >= FAT_CHARS][:limit]
