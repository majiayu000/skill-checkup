from pathlib import Path
from unittest.mock import patch

from skill_checkup import broken, inventory


def test_missing_tool_skips_heredoc_payload_and_resumes_after_delimiter():
    for redirect, indent in [
        ("<<eof", ""),
        ("<< 'eof'", ""),
        ('<< "eof"', ""),
        ("<<-'eof'", "\t"),
        ('"argument" <<eof', ""),
    ]:
        body = (
            f"```bash\nnotarealtool-before {redirect}\n"
            f"{indent}utterly-not-a-command-xyz\n{indent}eof\n"
            "notarealtool-after --flag\n```\n"
        )
        skill = inventory.Skill("demo", "demo", {}, body, Path("SKILL.md"))
        with patch.object(broken.shutil, "which", return_value=None):
            findings = broken._tools(skill)
        assert [(f.kind, f.params) for f in findings] == [
            ("missing-tool", {"line": 2, "cmd": "notarealtool-before"}),
            ("missing-tool", {"line": 5, "cmd": "notarealtool-after"}),
        ], redirect


def test_missing_tool_does_not_treat_shell_text_as_heredoc():
    for line in [
        "cat <<<text",
        'cat <<< "text"',
        "echo '<<eof'",
        'echo "<<eof"',
        "echo text # <<eof",
        "echo text;# <<eof",
        r"echo \<<eof",
        "value=$((1 << 2))",
        "((1 << 2))",
    ]:
        body = f"```bash\n{line}\nnotarealtool-after --flag\n```\n"
        skill = inventory.Skill("demo", "demo", {}, body, Path("SKILL.md"))
        with patch.object(broken.shutil, "which", side_effect=lambda cmd: "/bin/cat" if cmd == "cat" else None):
            findings = broken._tools(skill)
        assert [(f.kind, f.params) for f in findings] == [
            ("missing-tool", {"line": 3, "cmd": "notarealtool-after"}),
        ], line
