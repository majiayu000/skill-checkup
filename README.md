# skill-checkup

[![ci](https://github.com/majiayu000/skill-checkup/actions/workflows/ci.yml/badge.svg)](https://github.com/majiayu000/skill-checkup/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

`/skill-doctor` tells you which Claude Code skills you don't use. **skill-checkup tells you which skills are wrong, across Claude Code and Codex.**

It reads your installed skill folders and your local Claude Code and Codex session logs, read-only, and reports:

- **Broken**: links to nowhere, missing referenced files or commands, and same-name copies in `~/.claude/skills` and `~/.agents/skills` that have drifted apart.
- **Competing**: skills whose descriptions are so alike that they fight over the same requests.
- **Description gaps**: requests you keep typing that a skill's body already handles but its description never mentions, so it doesn't fire. `replay` checks a reworded description against your real requests.
- **One-sided**: skills both Claude Code and Codex load but only one of them uses; the idle copy still costs context every session. It tells you which copy is safe to delete and which one the busy side reads.

It also lists skills unused in the window, repeated requests no skill covers, and an estimate of the skill-listing budget. If you only use Claude Code, `/skill-doctor` and `/context` show unused skills and the measured listing size directly; start there.

An appendix lists *silent* skills, ones you seemed to ask for that did not fire. That signal is low-confidence (mentions and requests look alike), so it never feeds the summary or the actions.

```bash
uvx --from git+https://github.com/majiayu000/skill-checkup@v0.2.0 skill-checkup
```

No `uvx`? Use `pipx run --spec git+https://github.com/majiayu000/skill-checkup@v0.2.0 skill-checkup`, or clone the repo and run `python3 -m skill_checkup`. Python 3.10+, no dependencies.

It prints a short summary and writes the full report to `./skill-checkup-report.md`. The first run reads up to 90 days of logs and may take a minute; later runs use a cache.

## Example

This is the summary for a fictional machine with 27 skills and both Claude Code and Codex logs (built by `examples/demo/build_demo.py`):

```text
Skill checkup · 2026-10-22

| Area | Count | Meaning |
|---|---|---|
| Broken | 2 high-confidence, 4 in total | skills that load but fail, or copies that disagree |
| Competing | 1 | groups of skills whose descriptions fight over the same requests |
| Description gaps | 1 | repeated requests a skill's body handles but its description never mentions |
| One-sided | 3 | skills loaded by both Claude Code and Codex but used by only one; the other copy costs context |
| Unused | 14 | skills with no use in the window; archive candidates (emergency-looking ones excluded) |
| Heavy | none | at 200,000 tokens the skill list fits the listing budget |

- [ ] Fix `old-onboarding`: Won't load → remove the link or restore its target (details in section 1)
- [ ] Fix `deploy-preview`: Copies have diverged → compare them, keep one source, make the others identical (details in section 1)
- [ ] Add your own wording to the description of `pr-queue`: repeated requests (6) match its body, not its description
- [ ] Consider merging `release-notes`(4) / `changelog-writer`(0): keep `release-notes`, fold the rest in or sharpen the boundary in each description
- [ ] Remove the Codex copy of `deploy-preview` (agents): used 6× in Claude Code, never in Codex

Full report: skill-checkup-report.md
```

Try it without touching your own logs:

```bash
git clone https://github.com/majiayu000/skill-checkup && cd skill-checkup
python3 examples/demo/build_demo.py /tmp/skill-checkup-demo
HOME=/tmp/skill-checkup-demo python3 -m skill_checkup --since 36500
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

Use is counted per runtime. Claude Code use is a `Skill` tool call, a `/name` command, or the agent opening a skill's `SKILL.md` with the Read tool; Codex use is reading a `SKILL.md` or a typed `$name`. Reads record which folder they came from, so "remove this copy" never points at the copy the other agent reads. Sessions started by programs (`claude -p`, Agent SDK hosts, `codex exec`) count toward usage but are left out of the request analysis, because their "messages" are prompts written by code.

## Commands

```bash
skill-checkup                          # summary + ./skill-checkup-report.md
skill-checkup --show-examples          # include up to three of your requests per item
skill-checkup --lang zh                # Chinese report (auto-selected when LANG starts with zh)
skill-checkup --context-tokens 1000000 # budget estimate for a 1M-token model (default assumes 200k)
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

Round 3 leans on "Unused" (9 / 9), the most mechanical check; the heuristic sections had only 6 items (5 true). The one-sided list was cross-checked against `/skill-doctor`: every skill it called "used only in Codex" is one `/skill-doctor` lists as never invoked in Claude Code. One machine is not a benchmark. False-positive reports are the most useful issues you can open.

## Limits

- Similarity is lexical (Chinese is split into character pairs). It ranks candidates; it is not a verdict. It misses overlap across languages (a Chinese request and an English description) and can flag templated descriptions that share boilerplate.
- Thresholds were tuned on one person's logs.
- The budget estimate follows the rule documented at code.claude.com/docs/en/skills (1% of the context window, least-used descriptions dropped first) and assumes about 4 characters per token. On a 1M-token model most setups fit; `/context` shows the measured figure.
- Usage counts only this machine's logs. A skill used on another machine looks unused here.
- macOS and Linux. Windows is untested.

---

## 中文说明

`/skill-doctor` 告诉你 Claude Code 里哪些 skill 没在用；**skill-checkup 告诉你哪些 skill 有毛病，并且同时看 Claude Code 和 Codex**：

- **坏了的**：链接失效、引用的文件或命令不存在、`~/.claude/skills` 和 `~/.agents/skills` 里同名副本内容已经不一样。
- **互相抢的**：描述太像，抢同一类请求。
- **描述缺口**：你反复说的事，某个 skill 的正文能做、描述却没写，所以从不触发；`replay` 可以拿真实请求检验改写后的描述。
- **只在一边用**：Claude Code 和 Codex 都加载、只有一边在用；告诉你哪份副本能删，哪份是另一边正在读的。

只读、不联网；报告默认不包含你的原话，要看例句加 `--show-examples`；`--summary-json s.json --anonymize` 生成只有计数、skill 名已替换的摘要，可以放心发给别人。只用 Claude Code 的话，先跑 `/skill-doctor` 和 `/context`。

```bash
uvx --from git+https://github.com/majiayu000/skill-checkup@v0.2.0 skill-checkup --lang zh
```
