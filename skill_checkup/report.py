"""Assemble every check into one Markdown report, a terminal summary, and a shareable summary."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date

from . import behavior, broken, budget, overlap, usage
from .config import Config
from .i18n import T
from .inventory import Root, Skill
from .turns import Turn

KINDS = ["dead-link", "frontmatter", "diverged", "deprecated-root", "dead-path", "missing-tool", "known"]
HIGH = {"dead-link", "frontmatter", "diverged", "deprecated-root"}
TIERS = ["active", "low", "dormant-critical", "unused"]


@dataclass
class Inputs:
    skills: dict[str, Skill]
    roots: list[Root]
    turns: list[Turn]
    sessions: list
    since_days: int
    budget_chars: int
    context_tokens: int
    config: Config
    lang: str = "en"
    show_examples: bool = False
    overlap_threshold: float = 0.32


@dataclass
class Result:
    markdown: str
    terminal: str
    data: dict


def build(inp: Inputs) -> Result:
    t = T(inp.lang)
    sep = t.list_sep()
    skills, turns = inp.skills, inp.turns
    use = usage.aggregate(inp.sessions)
    auto = [s for s in inp.sessions if s.automated]
    findings = broken.check(skills, inp.roots, inp.config)
    clusters = overlap.find(skills, inp.overlap_threshold)
    misses = {k: v for k, v in behavior.missed(skills, turns).items() if k in skills}
    uses = {k: (use[k].uses if k in use else 0) for k in skills}
    budgets = budget.analyze(skills, uses, inp.budget_chars)
    fat = budget.fattest(skills)
    # Silent matches measured 0/6 in a hand check, so they stay out of tiers, totals and actions.
    tiers = {k: usage.tier(s, use.get(k)) for k, s in skills.items()}
    effects = behavior.effect(turns)
    cands = behavior.mine(skills, turns)

    claude_budget = next(b for b in budgets if b.runtime == "claude")
    big_dropped = next(b for b in budget.analyze(skills, uses, inp.budget_chars * 5) if b.runtime == "claude").dropped
    in_cluster = {m for c in clusters for m in c.members}
    archive = sorted(k for k, v in tiers.items() if v == "unused" and k not in in_cluster)
    hi = [f for f in findings if f.kind in HIGH]
    root_counts = Counter(r for s in skills.values() for r in set(s.roots))

    glance = [
        t("glance_head"),
        t("row_broken", hi=len(hi), total=len(findings)),
        t("row_overlap", n=len(clusters)),
        t("row_fat", fat=len(fat), chars=budget.FAT_CHARS, dropped=len(claude_budget.dropped)),
        t("row_unused", n=sum(1 for v in tiers.values() if v == "unused")),
    ]

    acts = []
    per_skill: dict[str, list] = {}
    for f in hi:
        per_skill.setdefault(f.skill, []).append(f)
    for name, fs in per_skill.items():
        kinds = Counter(t("kind." + f.kind)[0] for f in fs)
        what = sep.join(f"{k}{' ×' + str(n) if n > 1 else ''}" for k, n in kinds.items())
        acts.append(t("act_fix", name=name, what=what, fix=fs[0].fix(t)))
    for c in clusters[:8]:
        ranked = sorted(c.members, key=lambda m: -uses.get(m, 0))
        members = " / ".join(f"`{m}`({uses.get(m, 0)})" for m in ranked)
        acts.append(t("act_merge", members=members, keep=ranked[0]))
    for c in cands:
        if c.covered_by:
            acts.append(t("act_cover", name=c.covered_by, n=len(c.turns)))
    for name, n in fat[:5]:
        acts.append(t("act_trim", name=name, n=n))
    if archive:
        acts.append(t("act_archive", names=", ".join(f"`{a}`" for a in archive)))

    L: list[str] = []
    w = L.append
    w(f"# {t('title', date=date.today().isoformat())}\n")
    w(t("scope", skills=len(skills), roots=", ".join(f"{k}={v}" for k, v in root_counts.items()),
        days=inp.since_days, sessions=len(inp.sessions), auto=len(auto), turns=len(turns)) + "\n")
    w(f"## {t('glance')}\n")
    w("\n".join(glance) + "\n")
    w(f"## {t('actions')}\n")
    w("\n".join(acts) or t("act_none"))
    w("")

    w(f"## {t('sec_broken')}\n")
    for kind in KINDS:
        items = [f for f in findings if f.kind == kind]
        if not items:
            continue
        label, conf = t("kind." + kind)
        w(f"### {t('group_head', label=label, n=len(items), conf=conf)}\n")
        for f in items:
            w(f"- `{f.skill}`: {f.detail(t)}" + (f" ({f.accepted_reason})" if kind == "known" else ""))
        w("")

    w(f"## {t('sec_overlap')}\n")
    w(t("overlap_note") + "\n")
    for c in clusters:
        w("- " + " / ".join(f"`{m}`({uses.get(m, 0)})" for m in c.members))
        for a, b, sim, terms in c.pairs[:3]:
            w(t("overlap_pair", a=a, b=b, sim=sim, terms=sep.join(terms)))
    w("")

    w(f"## {t('sec_budget')}\n")
    w(t("budget_note", ctx=inp.context_tokens, chars=inp.budget_chars) + "\n")
    for b in budgets:
        line = t("budget_line", runtime=b.runtime, n=len(b.entries), total=b.total_chars)
        if b.runtime == "claude" and b.dropped:
            line += t("budget_over", over=b.total_chars - b.budget_chars, dropped=len(b.dropped))
        w(line)
    w(t("budget_big", chars=inp.budget_chars * 5, dropped=len(big_dropped)))
    if claude_budget.dropped:
        w("\n" + t("budget_dropped", ctx=inp.context_tokens,
                   names=", ".join(f"`{e.skill}`" for e in claude_budget.dropped)))
    if fat:
        w("\n" + t("budget_fat") + "\n")
        for name, n in fat:
            w(t("fat_line", name=name, n=n))
    w("")

    w(f"## {t('sec_tiers')}\n")
    for tier in TIERS:
        names = sorted((k for k, v in tiers.items() if v == tier), key=lambda k: -uses.get(k, 0))
        if names:
            w(f"- **{t('tier.' + tier)}** ({len(names)}): "
              + ", ".join(f"`{n}`" + (f"({uses[n]})" if uses.get(n) else "") for n in names))
    extra = sorted((k for k in use if k not in skills and use[k].uses >= 3), key=lambda k: -use[k].uses)
    if extra:
        w(t("tiers_extra", names=", ".join(f"`{k}`({use[k].uses})" for k in extra[:20])))
    w("")

    w(f"## {t('sec_effect')}\n")
    w(t("effect_note") + "\n")
    w(t("effect_head"))
    for e in effects[:15]:
        w(f"| `{e.skill}` | {e.runs} | {e.interrupted} | {e.corrected} | {e.bad_rate:.0%} |")
    w("")

    w(f"## {t('sec_mine')}\n")
    w(t("mine_note") + "\n")
    for c in cands[:10]:
        tag = t("mine_auto") if c.automated else ""
        if c.covered_by:
            tag += t("mine_covered", name=c.covered_by)
        w(t("mine_line", terms=sep.join(c.terms), sessions=c.sessions, n=len(c.turns), tag=tag))
        if inp.show_examples:
            for turn in c.turns[:3]:
                w(f"  - {turn.ts[:10]} {turn.session.runtime}: “{behavior.snippet(turn.text)}”")
    if not cands:
        w(t("mine_none"))
    elif not inp.show_examples:
        w("\n" + t("examples_hidden"))
    w("")

    w(f"## {t('sec_appendix_mute')}\n")
    w(t("appendix_note") + "\n")
    w(t("mute_note") + "\n")
    for k in sorted(misses, key=lambda k: -len(misses[k])):
        kinds = Counter(m.kind for m in misses[k])
        w(t("mute_line", name=k, tier=t("tier." + tiers[k]), n=len(misses[k]),
            kinds=", ".join(f"{a} {b}" for a, b in kinds.items())))
        if inp.show_examples:
            for m in misses[k][:3]:
                w(f"  - {m.turn.ts[:10]} {m.turn.session.runtime}: “{behavior.snippet(m.turn.text)}”")
    if misses and not inp.show_examples:
        w("\n" + t("examples_hidden"))
    w("")

    w(f"## {t('sec_method')}\n")
    w("\n".join(t("method")))

    terminal = "\n".join([t("title", date=date.today().isoformat()), "", *glance, "", *(acts[:5] or [t("act_none")])])
    data = {
        "date": date.today().isoformat(),
        "window_days": inp.since_days,
        "skills": len(skills),
        "sessions": len(inp.sessions),
        "automated_sessions": len(auto),
        "typed_messages": len(turns),
        "findings": [{"skill": f.skill, "kind": f.kind, "code": f.code} for f in findings],
        "clusters": [c.members for c in clusters],
        "missed": {k: len(v) for k, v in misses.items()},
        "tiers": tiers,
        "uses": uses,
        "budget": [{"runtime": b.runtime, "skills": len(b.entries), "total_chars": b.total_chars,
                    "budget_chars": b.budget_chars, "dropped": [e.skill for e in b.dropped]} for b in budgets],
        "effects": [{"skill": e.skill, "runs": e.runs, "interrupted": e.interrupted, "corrected": e.corrected}
                    for e in effects],
        "candidates": [{"sessions": c.sessions, "requests": len(c.turns), "covered_by": c.covered_by} for c in cands],
    }
    return Result("\n".join(L) + "\n", terminal + "\n", data)


def anonymize(data: dict) -> dict:
    """Replace every skill name with a stable placeholder so the summary can be shared."""
    names: dict[str, str] = {}

    def alias(name: str) -> str:
        if name not in names:
            names[name] = f"skill-{len(names) + 1:03d}"
        return names[name]

    out = dict(data)
    out["findings"] = [{**f, "skill": alias(f["skill"])} for f in data["findings"]]
    out["clusters"] = [[alias(m) for m in c] for c in data["clusters"]]
    out["missed"] = {alias(k): v for k, v in data["missed"].items()}
    out["tiers"] = {alias(k): v for k, v in data["tiers"].items()}
    out["uses"] = {alias(k): v for k, v in data["uses"].items()}
    out["budget"] = [{**b, "dropped": [alias(s) for s in b["dropped"]]} for b in data["budget"]]
    out["effects"] = [{**e, "skill": alias(e["skill"])} for e in data["effects"]]
    out["candidates"] = [{**c, "covered_by": alias(c["covered_by"]) if c.get("covered_by") else ""}
                         for c in data.get("candidates", [])]
    return out
