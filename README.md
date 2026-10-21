# skill-checkup

[![ci](https://github.com/majiayu000/skill-checkup/actions/workflows/ci.yml/badge.svg)](https://github.com/majiayu000/skill-checkup/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A read-only health report for the agent skills on your machine. It reads your installed skills and your local Claude Code and Codex session logs, then tells you which skills are:

- **Broken**: they load but point at missing files, missing commands, or copies that disagree.
- **Competing**: their descriptions are so similar that they fight over the same requests.
- **Heavy**: their descriptions eat the skill-listing budget, so Claude Code drops other skills' descriptions.
- **Unused**: nothing in your logs touched them in the window.

It also lists requests you keep typing that no skill covers, which are candidates for a new skill, and points out when an installed skill's body already handles them but its description doesn't say so.

An appendix lists *silent* skills, ones you seemed to ask for that did not fire. That signal is low-confidence (mentions and requests look alike), so it never feeds the summary or the actions.

```bash
uvx --from git+https://github.com/majiayu000/skill-checkup@v0.1.0 skill-checkup
```

No `uvx`? Use `pipx run --spec git+https://github.com/majiayu000/skill-checkup@v0.1.0 skill-checkup`, or clone the repo and run `python3 -m skill_checkup`. Python 3.10+, no dependencies.

It prints a short summary and writes the full report to `./skill-checkup-report.md`. The first run reads up to 90 days of logs and may take a minute; later runs use a cache.

## Example

This is the summary for a fictional machine with 27 skills (built by `examples/demo/build_demo.py`, run with `--context-tokens 100000`):

```text
Skill checkup · 2026-10-22

| Area | Count | Meaning |
|---|---|---|
| Broken | 2 high-confidence, 4 in total | skills that load but fail, or copies that disagree |
| Competing | 1 | groups of skills whose descriptions fight over the same requests |
| Heavy | ~1 dropped | skill descriptions Claude Code likely drops; 0 are over 500 chars |
| Unused | 14 | skills with no use in the window; archive candidates (emergency-looking ones excluded) |

- [ ] Fix `old-onboarding`: Won't load → remove the link or restore its target (details in section 1)
- [ ] Fix `deploy-preview`: Copies have diverged → compare them, keep one source, make the others identical (details in section 1)
- [ ] Consider merging `release-notes`(4) / `changelog-writer`(0): keep `release-notes`, fold the rest in or sharpen the boundary in each description
- [ ] Add your own wording to the description of `pr-queue`: repeated requests (6) match its body, not its description
- [ ] Archive candidates (move out of the skill directory, keep a copy): `budget-tracker`, `playbook-accessibility-audit`, `playbook-board-deck`, `playbook-customer-escalation`, `playbook-design-review`, `playbook-hiring-loop`, `playbook-load-test`, `playbook-oncall-handoff`, `playbook-pricing-rollout`, `playbook-quarterly-planning`, `screenshot-diff`, `seo-audit`, `test-flake-hunter`, `translate-docs`

Full report: skill-checkup-report.md
```

Try it without touching your own logs:

```bash
git clone https://github.com/majiayu000/skill-checkup && cd skill-checkup
python3 examples/demo/build_demo.py /tmp/skill-checkup-demo
HOME=/tmp/skill-checkup-demo python3 -m skill_checkup --since 36500 --context-tokens 100000
```

## Privacy

- Read-only. It never edits, moves or deletes a skill or a log.
- Offline. Nothing is sent anywhere.
- Your own messages stay out of the report unless you pass `--show-examples`.
- `--summary-json summary.json --anonymize` writes counts only, with skill names replaced, for sharing.
- Cache: `~/.cache/skill-checkup` (delete it any time). Optional config: `~/.config/skill-checkup/config.json`.

## What it reads

| Source | Path |
|---|---|
| Skills | `~/.claude/skills`, `~/.agents/skills`, `~/.codex/skills`, the current project's `.claude/skills` and `.agents/skills`, and skills from Claude Code plugins enabled in `~/.claude/settings.json` |
| Claude Code sessions | `~/.claude/projects/*/*.jsonl` (`$CLAUDE_CONFIG_DIR` respected) |
| Codex sessions | `~/.codex/sessions/**/*.jsonl` (`$CODEX_HOME` respected) |

Claude Code use counts both `Skill` tool calls and an agent opening a skill's `SKILL.md` with the Read tool. Sessions started by programs (`claude -p`, Agent SDK hosts, `codex exec`) count toward usage but are left out of the request analysis, because their "messages" are prompts written by code.

## Commands

```bash
skill-checkup                          # summary + ./skill-checkup-report.md
skill-checkup --show-examples          # include up to three of your requests per item
skill-checkup --lang zh                # Chinese report (auto-selected when LANG starts with zh)
skill-checkup --context-tokens 1000000 # estimate the budget for a 1M-token model
skill-checkup replay my-skill --description "new wording"   # compare old and new descriptions
```

`replay` scores a description against the requests that really triggered the skill (hit@1, hit@3) and against other skills' requests (steals@1). It is a lexical proxy: compare the two rows, not the absolute numbers.

All thresholds are options; see `skill-checkup --help`.

## Use it from your agent

Copy [`skill/SKILL.md`](skill/SKILL.md) into `~/.claude/skills/skill-checkup/` or `~/.agents/skills/skill-checkup/`, start a new session, and ask "check my skills".

## Optional config

```json
{
  "deprecated_roots": ["~/.old-skill-registry"],
  "known_issues": {"dead-path": {"some-skill": "accepted until the March cleanup"}}
}
```

`deprecated_roots` flags skills that still link into or reference an old directory. `known_issues` moves accepted findings into their own section.

## Accuracy

Findings were checked by hand against the author's own machine (106 skills, 90 days of Claude Code and Codex logs), 15 at a time:

| Round | True findings | What changed |
|---|---|---|
| 1 | 3 / 15 | baseline |
| 2 | 7 / 15 | output paths, subcommands, drawn boundaries, injected context |
| 3 | 14 / 15 | Read of SKILL.md counted as use; silent matches moved to the appendix |

Round 3 leans on "Unused" (9 / 9), the most mechanical check; the heuristic sections had only 6 items (5 true). One machine is not a benchmark. False-positive reports are the most useful issues you can open.

## Limits

- Similarity is lexical (Chinese is split into character pairs). It ranks candidates; it is not a verdict. It misses overlap across languages (a Chinese request and an English description) and can flag templated descriptions that share boilerplate.
- Thresholds were tuned on one person's logs.
- The budget estimate follows the rule documented at code.claude.com/docs/en/skills (1% of the context window, least-used descriptions dropped first) and assumes about 4 characters per token.
- macOS and Linux. Windows is untested.

---

## 中文说明

一个只读的 skill 体检工具：读本机已装的 skill 和 Claude Code / Codex 的会话日志，告诉你哪些 skill 坏了、互相抢触发、白占上下文、从没用过，以及有哪些反复手工做、却没有 skill 覆盖的事。“该触发却没触发”放在低置信附录里，不进摘要和动作清单。

```bash
uvx --from git+https://github.com/majiayu000/skill-checkup@v0.1.0 skill-checkup --lang zh
```

只读、不联网；报告默认不包含你的原话，要看例句加 `--show-examples`；`--summary-json s.json --anonymize` 生成只有计数、skill 名已替换的摘要，可以放心发给别人。
