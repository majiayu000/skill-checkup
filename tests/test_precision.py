"""Regression cases for the false positives found in the 2026-10-21 precision sample."""

from skill_checkup import behavior, broken, inventory, overlap, sessions, turns
from skill_checkup.i18n import T
from skill_checkup.inventory import Root

BOTH = frozenset({"claude", "codex"})


def make_skill(root, name, description, body=""):
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\n{body}", encoding="utf-8")
    return d


def findings(tmp_path, kind):
    roots = [Root("t", tmp_path, BOTH)]
    return [f.detail(T()) for f in broken.check(inventory.discover(roots), roots) if f.kind == kind]


def test_paths_the_skill_writes_or_deletes_are_not_missing(tmp_path):
    body = (
        "Sync a copy to `~/nowhere-a/PORTFOLIO.md` when done.\n"
        "### 4. 生成 draft.json\n\n路径：\n- X: `/opt/nowhere-b/draft.json`\n- Y: `/opt/nowhere-c/draft.json`\n\n"
        "Then run `cp /opt/nowhere-c/draft.json /opt/nowhere-c/final.json`.\n"
        "| cleanup | `rm -rf ~/nowhere-d` |\n"
        "Session 固定放在 `~/nowhere-e/sessions/`。\n"
        "Read `/opt/nowhere-f/input.txt` first.\n"
    )
    make_skill(tmp_path, "writer", "writes things", body)
    missing = findings(tmp_path, "dead-path")
    assert len(missing) == 1 and "nowhere-f" in missing[0], missing


def test_subcommands_awk_bodies_and_own_cli_are_not_missing_tools(tmp_path):
    body = (
        "```bash\n"
        'JOIN=$(lark-cli vc +meeting-join --format json)\n'
        "ps aux | awk 'NR>1 {\n  n = split($11, parts, \"/\")\n  name = parts[n]\n}'\n"
        "browser wait selector \"<css>\"\n"
        "notarealtool-xyz --flag\n"
        "```\n"
    )
    make_skill(tmp_path, "opencli-browser", "drives a browser", body)
    tools = findings(tmp_path, "missing-tool")
    assert {t.split("`")[1] for t in tools} <= {"lark-cli", "notarealtool-xyz"}, tools
    assert any("notarealtool-xyz" in t for t in tools)


def test_skills_that_already_draw_a_boundary_do_not_compete(tmp_path):
    make_skill(tmp_path, "lark-doc", "飞书云文档：读取和编辑飞书文档内容，文档 URL token 编辑 读取")
    make_skill(tmp_path, "lark-slides", "飞书幻灯片：读取编辑幻灯片，文档 URL token。不负责：云文档内容编辑（走 lark-doc）")
    make_skill(tmp_path, "tool-scout", "Run or audit the daily Tool Scout workflow report. Use only when the user explicitly asks for Tool Scout.")
    make_skill(tmp_path, "news-scout", "Run or audit the daily News Scout workflow report. Use only when the user explicitly asks for News Scout.")
    make_skill(tmp_path, "codex", "Run OpenAI Codex CLI for code review or edits. Use when explicitly requested.")
    make_skill(tmp_path, "threads", "Run Codex agent lanes for code review queues. Use when explicitly requested.")
    skills = inventory.discover([Root("t", tmp_path, BOTH)])
    clusters = overlap.find(skills, threshold=0.2)
    assert [c.members for c in clusters] == [["codex", "threads"]]


def session_with(*texts):
    s = sessions.Session("claude", "1", "", "")
    s.events = [["user", f"t{i}", text] for i, text in enumerate(texts)]
    return s


def test_named_ignores_agent_prompts_build_requests_and_pasted_text(tmp_path):
    make_skill(tmp_path, "kb-consolidate", "consolidate a knowledge base line")
    make_skill(tmp_path, "atlas", "AtlasCloud model calls")
    skills = inventory.discover([Root("t", tmp_path, BOTH)])
    s = session_with(
        "Use the kb-consolidate skill (its SKILL.md is at /x/SKILL.md)",
        "开工：建 harvest.py、写 kb-consolidate skill",
        "背景很长" * 120 + " 用 atlas 生成",
        "不能用 atlas cli 来做这件事吗",
    )
    misses = behavior.missed(skills, turns.split(s))
    assert list(misses) == ["atlas"] and len(misses["atlas"]) == 1


def test_client_injected_context_is_not_part_of_the_request():
    browser = ('<in-app-browser-context source="ambient-ui-state">\nstate\n</in-app-browser-context>\n\n'
               "## My request:\n帮我看看这个库")
    files = "# Files mentioned by the user:\n\n## a.md: /x/a.md\n\n## My request:\n实现这个"
    assert sessions._clean_user_text(browser) == "帮我看看这个库"
    assert sessions._clean_user_text(files) == "实现这个"
    assert sessions._clean_user_text("# Files mentioned by the user:\n\n## a.md: /x/a.md") is None


def test_repeated_request_handled_in_a_skill_body_is_reported_as_a_description_gap(tmp_path):
    make_skill(tmp_path, "threads", "Run Codex agent lanes for code review queues.",
               body="Broad queue requests such as all issues and PRs are bounded. issues PRs issues PRs\n")
    make_skill(tmp_path, "other", "Unrelated helper.", body="mentions an issue once")
    skills = inventory.discover([Root("t", tmp_path, BOTH)])
    asks = [f"帮我解决这个库的所有issues和prs 第{i}次 谢谢你的帮助" for i in range(6)]
    turn_list = []
    for i, text in enumerate(asks):
        s = sessions.Session("claude", f"s{i}", "", "")
        s.events = [["user", f"2026-10-0{i + 1}T00:00:00Z", text]]
        turn_list.extend(turns.split(s))
    cands = behavior.mine(skills, turn_list)
    assert cands and cands[0].covered_by == "threads"


def test_shared_boilerplate_does_not_chain_unrelated_skills(tmp_path):
    make_skill(tmp_path, "alpha", "alpha gamma planning rollback")
    make_skill(tmp_path, "beta", "gamma planning rollback delta")
    make_skill(tmp_path, "omega", "rollback delta epsilon zeta")
    skills = inventory.discover([Root("t", tmp_path, BOTH)])
    groups = [c.members for c in overlap.find(skills, threshold=0.3)]
    assert all(len(g) == 2 for g in groups), groups
