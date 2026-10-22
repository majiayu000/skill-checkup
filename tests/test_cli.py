import json

from skill_checkup.__main__ import main


def line(**kw):
    return json.dumps(kw, ensure_ascii=False) + "\n"


def make_home(home):
    for name, desc in [("deploy-helper", "Deploy the web app to staging and production servers"),
                       ("tidy-notes", "Tidy and summarize meeting notes into action items")]:
        d = home / ".claude/skills" / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {desc}\n---\nBody\n")
    proj = home / ".claude/projects/p"
    proj.mkdir(parents=True)
    (proj / "s1.jsonl").write_text(
        line(type="user", entrypoint="cli", timestamp="2099-01-01T00:00:00Z",
             message={"content": "please deploy the web app to staging servers now"})
        + line(type="assistant", timestamp="2099-01-01T00:00:01Z",
               message={"content": [{"type": "tool_use", "name": "Skill", "input": {"skill": "deploy-helper"}}]})
        + line(type="user", timestamp="2099-01-01T00:01:00Z",
               message={"content": "This session is being continued from a previous conversation"})
        + line(type="user", timestamp="2099-01-01T00:02:00Z",
               message={"content": "use tidy-notes on these meeting notes please"})
    )
    codex = home / ".codex/sessions/2099/01/01"
    codex.mkdir(parents=True)
    (codex / "rollout-2099-01-01T00-00-00-00000000-0000-0000-0000-000000000001.jsonl").write_text(
        line(type="session_meta", payload={"id": "c1", "originator": "codex-tui"})
        + line(type="event_msg", timestamp="2099-01-01T00:00:00Z", payload={
            "type": "item_completed",
            "item": {"type": "UserMessage", "content": [{"type": "text", "text": "summarize meeting notes into action items"}]}})
        + line(type="event_msg", timestamp="2099-01-01T00:00:01Z", payload={
            "type": "item_completed",
            "item": {"type": "CommandExecution", "command": ["/bin/zsh", "-lc", "cat ~/.claude/skills/tidy-notes/SKILL.md"]}})
    )


def test_default_run_writes_report_and_private_summary(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    make_home(home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.chdir(home)
    out, summary = tmp_path / "r.md", tmp_path / "s.json"
    assert main(["--since", "36500", "--lang", "en", "--out", str(out),
                 "--summary-json", str(summary), "--anonymize"]) == 0

    printed = capsys.readouterr().out
    assert "At a glance" not in printed and "| Broken |" in printed
    report = out.read_text()
    assert "please deploy" not in report, "requests stay hidden without --show-examples"
    assert "- `tidy-notes` (Used once or twice): requests 1, named 1" in report  # appendix entry
    glance = report.split("## Actions")[0]
    assert "Silent" not in glance and "Reword" not in report
    assert report.index("Appendix: low-confidence signals") > report.index("7. New skill candidates")
    data = json.loads(summary.read_text())
    assert "deploy-helper" not in summary.read_text()
    assert data["typed_messages"] == 3  # the continuation summary is not a typed message
    assert sorted(data["uses"].values()) == [1, 1]  # one Claude Skill call, one Codex SKILL.md read

    assert main(["--since", "36500", "--lang", "en", "--out", str(out), "--show-examples"]) == 0
    assert "use tidy-notes on these meeting notes" in out.read_text()
