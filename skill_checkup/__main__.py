"""skill-checkup: a read-only health report for the agent skills installed on this machine.

Run with no arguments to print a summary and write the full report to ./skill-checkup-report.md.
Nothing is changed and nothing leaves the machine.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import behavior, config, inventory, report, sessions, turns
from .i18n import T

DEFAULT_OUT = "skill-checkup-report.md"


def _default_lang() -> str:
    env = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or ""
    return "zh" if env.lower().startswith("zh") else "en"


def _load(args):
    roots = inventory.default_roots(cwd=Path.cwd())
    skills = inventory.discover(roots)
    sess = list(sessions.iter_sessions(args.since, claude=not args.no_claude, codex=not args.no_codex,
                                       sweep_reads=args.sweep_reads))
    typed = [t for s in sess if not s.automated for t in turns.split(s)]
    return roots, skills, sess, typed


def cmd_report(args) -> int:
    behavior.MISS_THRESHOLD = args.miss_threshold
    roots, skills, sess, typed = _load(args)
    if not skills:
        home = Path.home()
        looked = [home / ".claude/skills", home / ".agents/skills", home / ".codex/skills",
                  Path.cwd() / ".claude/skills", Path.cwd() / ".agents/skills"]
        print(T(args.lang)("no_skills", paths="\n".join(f"  {p}" for p in looked)))
        return 0
    budget_chars = args.listing_budget_chars or int(args.context_tokens * 0.01 * 4)
    result = report.build(report.Inputs(
        skills=skills, roots=roots, turns=typed, sessions=sess, since_days=args.since,
        budget_chars=budget_chars, context_tokens=args.context_tokens, config=config.load(),
        lang=args.lang, show_examples=args.show_examples, overlap_threshold=args.overlap_threshold,
    ))
    if args.out == "-":
        sys.stdout.write(result.markdown)
    else:
        out = Path(args.out).expanduser()
        out.write_text(result.markdown, encoding="utf-8")
        sys.stdout.write(result.terminal + "\n" + T(args.lang)("summary_written", path=out) + "\n")
    if args.json:
        Path(args.json).expanduser().write_text(json.dumps(result.data, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.summary_json:
        data = report.anonymize(result.data) if args.anonymize else result.data
        Path(args.summary_json).expanduser().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def cmd_replay(args) -> int:
    t = T(args.lang)
    _, skills, _, typed = _load(args)
    if args.skill not in skills:
        print(f"unknown skill: {args.skill}", file=sys.stderr)
        return 2
    new = args.description
    if args.description_file:
        new = Path(args.description_file).expanduser().read_text(encoding="utf-8").strip()
    rows = [(t("replay_current"), behavior.replay(skills, typed, args.skill))]
    if new:
        rows.append((t("replay_new"), behavior.replay(skills, typed, args.skill, new)))
    print(t("replay_head", name=args.skill, n=rows[0][1].positives))
    print("{:10} {:>9} {:>9} {:>9}".format(*t("replay_cols")))
    for label, r in rows:
        print(f"{label:10} {r.hit_at_1:9.0%} {r.hit_at_3:9.0%} {r.false_top1:9.1%}")
    if args.show_examples:
        for label, r in rows:
            if r.examples_missed:
                print(t("replay_missed", label=label))
                for e in r.examples_missed:
                    print(f"  - {e}")
    print(t("replay_note"))
    return 0


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--since", type=int, default=90, help="days of session logs to read (default 90)")
    common.add_argument("--no-claude", action="store_true", help="skip Claude Code logs")
    common.add_argument("--no-codex", action="store_true", help="skip Codex logs")
    common.add_argument("--lang", choices=["en", "zh"], default=_default_lang(), help="report language")
    common.add_argument("--show-examples", action="store_true",
                        help="include up to three of your own requests per item (local only)")
    common.add_argument("--sweep-reads", type=int, default=sessions.AUDIT_DISTINCT_READS,
                        help="skills read in one Codex turn that count as an inventory sweep (default 8)")

    p = argparse.ArgumentParser(prog="skill-checkup", description=__doc__, parents=[common],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default=DEFAULT_OUT, help=f"Markdown report path, or - for stdout (default {DEFAULT_OUT})")
    p.add_argument("--json", help="also write the full data as JSON")
    p.add_argument("--summary-json", help="write counts only, safe to share")
    p.add_argument("--anonymize", action="store_true", help="replace skill names in --summary-json")
    p.add_argument("--context-tokens", type=int, default=200_000, help="model context window (default 200000)")
    p.add_argument("--listing-budget-chars", type=int, help="override the estimated skill-listing budget")
    p.add_argument("--overlap-threshold", type=float, default=0.32, help="similarity that groups skills (default 0.32)")
    p.add_argument("--miss-threshold", type=float, default=behavior.MISS_THRESHOLD,
                   help="similarity that counts a request as a missed trigger (default 0.38)")
    p.set_defaults(func=cmd_report)

    sub = p.add_subparsers(dest="cmd")
    rp = sub.add_parser("replay", parents=[common], help="score a skill description against your real requests")
    rp.add_argument("skill")
    rp.add_argument("--description", help="candidate description text")
    rp.add_argument("--description-file", help="file containing the candidate description")
    rp.set_defaults(func=cmd_replay)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
