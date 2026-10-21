"""Build a fictional home directory that exercises every section of the report.

    python3 examples/demo/build_demo.py /tmp/skill-checkup-demo
    HOME=/tmp/skill-checkup-demo python3 -m skill_checkup --since 36500 --context-tokens 50000

All skills, paths and requests are invented.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

def long(text: str, detail: str) -> str:
    return f"{text} {detail} " * 3


SKILLS = {
    # name: (description, body, roots)
    "deploy-preview": (long("Deploy a branch to a preview environment and post the URL.",
                            "Handles environment variables, preview database seeding, smoke checks and teardown."),
                       "Run `scripts/deploy.sh` then check `scripts/verify.sh`.\n", ["claude", "agents"]),
    "release-notes": ("Draft release notes from merged pull requests and tags for a version.", "", ["claude"]),
    "changelog-writer": ("Draft changelog entries and release notes from merged pull requests and tags.", "", ["claude"]),
    "pr-queue": ("Work through a repository review queue in parallel lanes. Use when explicitly requested.",
                 "Broad requests such as fix all open issues and PRs are split into small tranches. "
                 "Each lane takes issues and PRs one at a time.\n", ["claude", "agents"]),
    "db-migrate": (long("Plan and run database schema migrations with a dry run first.",
                        "Checks lock times, backfills, index builds and rollback scripts."),
                   "Load `references/migration-checklist.md` before planning.\n", ["claude"]),
    "api-docs": ("Generate API reference pages from OpenAPI specs.", "", ["claude"]),
    "incident-review": ("Write a blameless incident review after a production outage.", "", ["claude"]),
    "screenshot-diff": ("Compare UI screenshots between two builds and flag visual changes.", "", ["agents"]),
    "commit-style": ("Rewrite commit messages to the team's convention.", "", ["claude", "agents"]),
    "translate-docs": (long("Translate product docs between English and Japanese.",
                            "Keeps glossary terms, screenshots captions and UI strings consistent."), "", ["claude"]),
    "seo-audit": ("Audit a marketing site for SEO issues.", "", ["claude"]),
    "test-flake-hunter": (long("Find flaky tests by rerunning suites and comparing failures.",
                               "Groups failures by stack trace, seed and timing to isolate nondeterminism."), "", ["claude"]),
    "budget-tracker": ("Track monthly cloud spend against budget.", "", ["agents"]),
}
PLAYBOOKS = {
    "oncall-handoff": "Hand over the pager at shift change: open alerts, muted monitors, pending follow-ups.",
    "design-review": "Prepare a design doc for review, collect comments, and record the decision.",
    "hiring-loop": "Schedule interview panels, share rubrics, and write the debrief summary.",
    "quarterly-planning": "Turn team goals into quarterly objectives with owners and measurable results.",
    "vendor-security": "Answer vendor security questionnaires from our policy library.",
    "customer-escalation": "Triage an escalated support ticket and coordinate engineering response.",
    "accessibility-audit": "Check pages against WCAG contrast, keyboard and screen reader criteria.",
    "pricing-rollout": "Roll out a pricing change: feature flags, billing migration, customer emails.",
    "mobile-release": "Cut a mobile release branch, run store checklists, and stage the rollout.",
    "load-test": "Run k6 load tests against staging and compare latency percentiles with baseline.",
    "board-deck": "Assemble the monthly board deck from finance and product metrics.",
}
for topic, text in PLAYBOOKS.items():
    SKILLS[f"playbook-{topic}"] = (text + " " + text, "", ["claude"])


def write_skill(root: Path, name: str, description: str, body: str) -> None:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\n{body}", encoding="utf-8")
    if "scripts/" in body:
        (d / "scripts").mkdir(exist_ok=True)
        (d / "scripts" / "deploy.sh").write_text("#!/bin/sh\n")
    if "references/" in body:
        (d / "references").mkdir(exist_ok=True)


def line(**kw) -> str:
    return json.dumps(kw, ensure_ascii=False) + "\n"


def claude_session(day: int, request: str, skill: str | None) -> str:
    ts = f"2099-01-{day:02d}T10:00:00Z"
    out = line(type="user", entrypoint="cli", timestamp=ts, message={"content": request})
    if skill:
        out += line(type="assistant", timestamp=ts, message={"content": [
            {"type": "tool_use", "name": "Skill", "input": {"skill": skill}}]})
    return out


def build(home: Path) -> None:
    if home.exists():
        shutil.rmtree(home)
    roots = {"claude": home / ".claude" / "skills", "agents": home / ".agents" / "skills"}
    for name, (desc, body, where) in SKILLS.items():
        for r in where:
            write_skill(roots[r], name, desc, body)
    # The Codex copy of deploy-preview was edited and never synced back.
    (roots["agents"] / "deploy-preview" / "SKILL.md").write_text(
        (roots["agents"] / "deploy-preview" / "SKILL.md").read_text() + "\nAlso tag the preview with the PR number.\n")
    # A link left behind after a folder was moved.
    (roots["claude"] / "old-onboarding").symlink_to(home / "archive" / "old-onboarding")

    used = ["deploy-preview"] * 6 + ["release-notes"] * 4 + ["commit-style"] * 5 + ["pr-queue"] * 3 + ["api-docs"]
    projects = home / ".claude" / "projects" / "demo"
    projects.mkdir(parents=True)
    for i, skill in enumerate(used):
        (projects / f"use-{i:02d}.jsonl").write_text(claude_session(1 + i % 20, f"please run {skill} for this repo", skill))
    asks = ["fix all the open issues and PRs in this repo", "fix all open issues and PRs in this repo please",
            "please fix the open issues and PRs in this repo", "fix all open issues and PRs in the repo",
            "fix the open issues and PRs in this repo today", "fix all of the open issues and PRs in this repo"]
    for i, ask in enumerate(asks):
        (projects / f"ask-{i:02d}.jsonl").write_text(claude_session(3 + i * 2, ask, None))


if __name__ == "__main__":
    build(Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/skill-checkup-demo").expanduser())
