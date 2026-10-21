import json
from pathlib import Path

from skill_checkup import behavior, broken, budget, config, inventory, sessions, turns
from skill_checkup.i18n import T
from skill_checkup.inventory import Root

BOTH = frozenset({"claude", "codex"})


def roots_of(**paths):
    return [Root(label, path, BOTH) for label, path in paths.items()]


def make_skill(root: Path, name: str, description: str, body: str = "") -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\n{body}", encoding="utf-8")
    return d


def test_frontmatter_block_scalar():
    fm, body = inventory.parse_frontmatter("---\nname: a\ndescription: >\n  line one\n  line two\n---\nBody")
    assert fm == {"name": "a", "description": "line one line two"}
    assert body == "Body"


def test_diverged_copies_and_dead_link(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    make_skill(a, "x", "does x")
    make_skill(b, "x", "does x differently")
    (b / "gone").symlink_to(tmp_path / "missing")
    roots = roots_of(a=a, b=b)
    skills = inventory.discover(roots)
    assert skills["x"].diverged
    kinds = {f.kind for f in broken.check(skills, roots)}
    assert {"diverged", "dead-link"} <= kinds


def test_dead_path_ignores_outputs_and_foreign_projects(tmp_path):
    d = make_skill(tmp_path, "y", "does y", body=(
        "Run `scripts/run.py` then `scripts/missing.py`.\n"
        "Write `--out ~/report-YYYY.md`.\n"
        "Project file `templates/node.md` lives in the knowledge base.\n"
        "Read `/opt/definitely-not-here/file`.\n"
    ))
    (d / "scripts").mkdir()
    (d / "scripts" / "run.py").write_text("")
    roots = roots_of(t=tmp_path)
    skills = inventory.discover(roots)
    details = [f.detail(T()) for f in broken.check(skills, roots) if f.kind == "dead-path"]
    assert any("scripts/missing.py" in x for x in details)
    assert any("/opt/definitely-not-here/file" in x for x in details)
    assert not any("run.py" in x or "templates/node.md" in x or "report-" in x for x in details)


def test_missing_tool_skips_heredoc_and_quoted_python(tmp_path):
    body = "```bash\nnotarealtool-xyz --flag\npython3 - <<'EOF'\nimport os\nEOF\npython3 -c \"\nfoo = 1\n\"\n```\n"
    make_skill(tmp_path, "z", "does z", body=body)
    roots = roots_of(t=tmp_path)
    skills = inventory.discover(roots)
    tools = [f.detail(T()) for f in broken.check(skills, roots) if f.kind == "missing-tool"]
    assert len(tools) == 1 and "notarealtool-xyz" in tools[0]


def _claude_line(**kw):
    return json.dumps(kw, ensure_ascii=False) + "\n"


def test_claude_parse_turns_and_filters(tmp_path):
    f = tmp_path / "s.jsonl"
    f.write_text(
        _claude_line(type="user", entrypoint="cli", timestamp="2026-10-01T00:00:00Z",
                     message={"role": "user", "content": "帮我做竞品分析"})
        + _claude_line(type="assistant", timestamp="2026-10-01T00:00:01Z",
                       message={"content": [{"type": "tool_use", "name": "Skill", "input": {"skill": "peerscope"}}]})
        + _claude_line(type="user", timestamp="2026-10-01T00:01:00Z",
                       message={"content": "<command-name>/model</command-name>"})
        + _claude_line(type="user", timestamp="2026-10-01T00:02:00Z",
                       message={"content": "This session is being continued from a previous conversation"})
        + _claude_line(type="user", timestamp="2026-10-01T00:03:00Z",
                       message={"content": "[Request interrupted by user]"})
        + _claude_line(type="user", timestamp="2026-10-01T00:04:00Z", message={"content": "不对，重来"}),
        encoding="utf-8",
    )
    s = sessions.parse_claude(f)
    assert not s.automated
    assert ["skill", "2026-10-01T00:00:01Z", "peerscope", "tool"] in s.events
    assert not any(e[0] == "skill" and e[2] == "model" for e in s.events)
    ts = turns.split(s)
    assert ts[0].skills == ["peerscope"]
    assert ts[-2].interrupted and ts[-2].corrected_next


def test_codex_audit_sweep(tmp_path):
    f = tmp_path / "rollout-2026-10-01T00-00-00-00000000-0000-0000-0000-000000000000.jsonl"
    lines = [json.dumps({"type": "session_meta", "payload": {"id": "abc", "originator": "codex_exec"}})]
    lines.append(json.dumps({"type": "event_msg", "timestamp": "2026-10-01T00:00:00Z",
                             "payload": {"type": "user_message", "message": "inventory all skills"}}))
    for i in range(sessions.AUDIT_DISTINCT_READS):
        lines.append(json.dumps({"type": "response_item", "timestamp": "2026-10-01T00:00:01Z", "payload": {
            "type": "function_call", "arguments": json.dumps({"cmd": f"cat ~/.agents/skills/s{i}/SKILL.md"})}}))
    f.write_text("\n".join(lines) + "\n")
    s = sessions.parse_codex(f)
    sessions._mark_audit_sweeps(s, sessions.AUDIT_DISTINCT_READS)
    assert s.automated
    assert all(e[3] == "audit" for e in s.events if e[0] == "skill")


def test_named_miss_and_path_mention(tmp_path):
    make_skill(tmp_path, "peerscope", "竞品分析 对比 市场调研")
    skills = inventory.discover(roots_of(t=tmp_path))
    s = sessions.Session("claude", "1", "", "")
    s.events = [["user", "t1", "用 peerscope 跑一下"], ["user", "t2", "按 peerscope/evals/x.md 跑 eval"]]
    misses = behavior.missed(skills, turns.split(s))
    assert [m.turn.text for m in misses["peerscope"]] == ["用 peerscope 跑一下"]


def test_budget_drops_least_used_first(tmp_path):
    root = tmp_path / "claude"
    make_skill(root, "busy", "x" * 300)
    make_skill(root, "idle", "y" * 300)
    skills = inventory.discover([Root("claude", root, frozenset({"claude"}))])
    claude = next(b for b in budget.analyze(skills, {"busy": 9, "idle": 0}, 400) if b.runtime == "claude")
    assert [e.skill for e in claude.dropped] == ["idle"]


def test_known_issue_and_deprecated_root_come_from_config(tmp_path):
    old = tmp_path / "old"
    make_skill(old, "legacy", "does legacy things")
    live = tmp_path / "live"
    live.mkdir()
    (live / "legacy").symlink_to(old / "legacy")
    make_skill(live, "keeper", "keeps", body="Run `~/nowhere-xyz/run.sh`.\n")
    roots = roots_of(live=live)
    skills = inventory.discover(roots)
    plain = broken.check(skills, roots)
    assert not any(f.kind == "deprecated-root" for f in plain)
    cfg = config.Config(deprecated_roots=[old], known_issues={"dead-path": {"keeper": "accepted"}})
    found = broken.check(skills, roots, cfg)
    assert any(f.kind == "deprecated-root" and f.skill == "legacy" for f in found)
    known = [f for f in found if f.kind == "known"]
    assert known and known[0].fix(T()) == "accepted"


def test_plugin_skills_count_only_when_enabled(tmp_path):
    import json

    home = tmp_path
    install = home / ".claude/plugins/cache/m/demo/1.0.0"
    make_skill(install / "skills", "plug", "plugin skill")
    (home / ".claude/plugins").mkdir(parents=True, exist_ok=True)
    (home / ".claude/plugins/installed_plugins.json").write_text(json.dumps(
        {"version": 2, "plugins": {"demo@m": [{"scope": "user", "installPath": str(install)}]}}))
    settings = home / ".claude/settings.json"
    settings.write_text(json.dumps({"enabledPlugins": {"demo@m": False}}))
    assert not inventory.plugin_roots(home)
    settings.write_text(json.dumps({"enabledPlugins": {"demo@m": True}}))
    roots = inventory.plugin_roots(home)
    assert [r.label for r in roots] == ["plugin:demo"]
    assert "plug" in inventory.discover(roots)


def test_anonymized_summary_has_no_skill_names():
    from skill_checkup import report

    data = {"findings": [{"skill": "secret-a", "kind": "diverged", "code": "diverged"}],
            "clusters": [["secret-a", "secret-b"]], "missed": {"secret-b": 2},
            "tiers": {"secret-a": "unused", "secret-b": "low"}, "uses": {"secret-a": 0, "secret-b": 1},
            "budget": [{"runtime": "claude", "dropped": ["secret-a"]}],
            "effects": [{"skill": "secret-b", "runs": 3}]}
    text = json.dumps(report.anonymize(data))
    assert "secret" not in text and "skill-001" in text


def test_claude_read_of_skill_md_counts_as_use(tmp_path):
    f = tmp_path / "s.jsonl"
    f.write_text(
        _claude_line(type="user", entrypoint="cli", timestamp="2026-10-01T00:00:00Z",
                     message={"content": "please use the video skill"})
        + _claude_line(type="assistant", timestamp="2026-10-01T00:00:01Z", message={"content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": "/h/.codex/skills/reverse-video-prompt/SKILL.md"}},
            {"type": "tool_use", "name": "Read", "input": {"file_path": "/h/.codex/skills/reverse-video-prompt/SKILL.md"}},
            {"type": "tool_use", "name": "Read", "input": {"file_path": "/h/notes/SKILL.md.bak"}}]}),
        encoding="utf-8",
    )
    s = sessions.parse_claude(f)
    reads = [e for e in s.events if e[0] == "skill"]
    assert [(e[2], e[3]) for e in reads] == [("reverse-video-prompt", "read")]
    assert turns.split(s)[0].skills == ["reverse-video-prompt"]
