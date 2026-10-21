"""Static checks for skills that will load but fail when run: dead paths, missing tools, bad copies."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .i18n import T
from .inventory import Root, Skill

HOME = Path.home()

PATH_RE = re.compile(r"(?<![\w/.$-])((?:~|\$HOME|/Users|/home|/opt|/usr/local)/[^\s`'\"<>|;,()\[\]（），。#]+|(?:scripts|references|assets|templates|agents)/[^\s`'\"<>|;,()\[\]（），。#]+)")
FENCE_RE = re.compile(r"```([a-zA-Z]*)\n(.*?)```", re.S)
PLACEHOLDER_RE = re.compile(r"[<>{}*]|YYYY|MMDD|XXX|\$\{|\$[A-Z_]+(?<!\$HOME)|\.\.\.|…")
SHELL_LANGS = {"bash", "sh", "zsh", "shell", "console"}
BUILTINS = {
    "cd", "echo", "export", "set", "unset", "source", ".", "if", "then", "else", "fi", "for", "do",
    "done", "while", "case", "esac", "test", "[", "[[", "true", "false", "read", "printf", "exit",
    "return", "local", "function", "eval", "exec", "alias", "type", "command", "time", "trap",
    "shift", "wait", "{", "}", "(", ")", "#", "then", "elif", "until", "select", "declare",
    # code keywords that leak in from embedded scripts
    "break", "continue", "import", "from", "const", "let", "var", "async", "await", "def",
    "class", "print", "try", "except", "finally", "with", "pass", "raise", "yield", "lambda",
}
# Skip quoted/escaped text, comments and arithmetic before matching a simple
# heredoc delimiter. Other shell syntax is left to the existing heuristic.
HEREDOC_RE = re.compile(
    r"""'[^']*'|"(?:\\.|[^"\\])*"|\\.|(?:^|(?<=[\s;&|()]))#.*|"""
    r"""\$\(\(.*?\)\)|\(\(.*?\)\)|"""
    r"""(?<!<)<<-?\s*(?P<quote>['"]?)(?P<delimiter>\w+)(?P=quote)(?=$|[\s;&|()<>])"""
)
# Directories a runtime manages itself (the desktop app's synced Anthropic skills).
MANAGED_ENTRIES = {"synced"}
OUTPUT_FLAGS = ("--out", "--output", "--json", "--csv", "-o", ">", ">>", "--dest", "--target")


@dataclass
class Finding:
    skill: str
    kind: str  # frontmatter | diverged | dead-link | dead-path | deprecated-root | missing-tool | known
    code: str  # i18n key for the detail; the fix key is "fix_" + code
    params: dict = field(default_factory=dict)
    accepted_reason: str = ""  # set when the owner listed this in known_issues

    def detail(self, t: T) -> str:
        return t(self.code, **self.params)

    def fix(self, t: T) -> str:
        if self.accepted_reason:
            return self.accepted_reason
        return t("fix_frontmatter") if self.kind == "frontmatter" else t("fix_" + self.code)


def check(skills: dict[str, Skill], roots: list[Root], cfg: Config | None = None) -> list[Finding]:
    cfg = cfg or Config()
    out = _check(skills, roots, cfg.deprecated_roots)
    for f in out:
        reason = cfg.known_issues.get(f.kind, {}).get(f.skill)
        if reason:
            f.kind, f.accepted_reason = "known", reason
    return out


def _under(path: Path, roots: list[Path]) -> bool:
    return any(path == r or r in path.parents for r in roots)


def _check(skills: dict[str, Skill], roots: list[Root], deprecated: list[Path]) -> list[Finding]:
    out: list[Finding] = []
    out.extend(_dangling(roots))
    for s in skills.values():
        for code, params in s.problems:
            out.append(Finding(s.name, "frontmatter", code, params))
        if s.diverged:
            where = ", ".join(f"{i.root}({i.digest[:6]})" for i in s.installs)
            out.append(Finding(s.name, "diverged", "diverged", {"where": where}))
        for i in s.installs:
            if _under(i.real, deprecated):
                out.append(Finding(s.name, "deprecated-root", "link_into_deprecated",
                                   {"root": i.root, "real": str(i.real)}))
        out.extend(_paths(s, deprecated))
        out.extend(_tools(s))
    return out


def _dangling(roots: list[Root]) -> list[Finding]:
    out = []
    for root in roots:
        if not root.path.is_dir() or root.label.startswith("plugin:"):
            continue
        for entry in root.path.iterdir():
            if entry.name.startswith(".") or entry.name in MANAGED_ENTRIES:
                continue
            if entry.is_symlink() and not entry.exists():
                out.append(Finding(entry.name, "dead-link", "dangling_link",
                                   {"root": root.label, "target": str(entry.readlink())}))
            elif entry.is_dir() and not (entry / "SKILL.md").exists():
                out.append(Finding(entry.name, "dead-link", "no_skill_md", {"root": root.label}))
    return out


def _expand(raw: str, base: Path) -> Path:
    raw = raw.rstrip(".:")
    if raw.startswith("~/"):
        return HOME / raw[2:]
    if raw.startswith("$HOME/"):
        return HOME / raw[6:]
    if raw.startswith("/"):
        return Path(raw)
    return base / raw


def _paths(s: Skill, deprecated: list[Path]) -> list[Finding]:
    out: list[Finding] = []
    base = s.installs[0].real
    seen: set[str] = set()
    for lineno, line in enumerate(s.body.splitlines(), start=1):
        for m in PATH_RE.finditer(line):
            raw = m.group(1)
            if raw in seen or PLACEHOLDER_RE.search(raw) or "/tmp/" in raw:
                continue
            after = line[m.end() : m.end() + 2]
            if len(after) == 2 and after[0] == " " and after[1].isupper():
                continue  # path with a space, e.g. "Application Support"
            before = line[: m.start()].rstrip()
            if before.endswith(OUTPUT_FLAGS) or before.endswith("="):
                continue  # a path the skill will create, not one it needs
            seen.add(raw)
            target = _expand(raw, base)
            if raw.startswith(("/Users/", "/home/")) and not raw.startswith(str(HOME)):
                continue  # another machine's example path
            if not raw.startswith(("/", "~", "$")) and not (base / raw.split("/")[0]).exists():
                continue  # relative to some project the skill talks about, not to the skill itself
            literal = raw.startswith(("/", "~", "$"))
            if literal and _under(target, deprecated):
                out.append(Finding(s.name, "deprecated-root", "ref_deprecated", {"line": lineno, "path": raw}))
                if target.exists():
                    continue
            if not target.exists():
                out.append(Finding(s.name, "dead-path", "ref_missing", {"line": lineno, "path": raw}))
    return out


def _tools(s: Skill) -> list[Finding]:
    missing: dict[str, int] = {}
    for m in FENCE_RE.finditer(s.body):
        if m.group(1).lower() not in SHELL_LANGS:
            continue
        start = s.body[: m.start()].count("\n") + 2
        heredoc, prev, quoted = None, "", False
        for offset, line in enumerate(m.group(2).splitlines()):
            opens = (line.count('"') - line.count('\\"')) % 2 == 1
            if quoted:
                quoted = not opens  # inside a multi-line `python3 -c "..."` string
                continue
            if heredoc:
                if line.strip() == heredoc:
                    heredoc = None
                continue
            here = next((h for h in HEREDOC_RE.finditer(line) if h.group("delimiter")), None)
            if not prev.rstrip().endswith(("\\", "|", "&&")):
                cmd = _first_command(line)
                if cmd and cmd not in missing and shutil.which(cmd) is None:
                    missing[cmd] = start + offset
            heredoc = here.group("delimiter") if here else None
            quoted = opens and not heredoc
            prev = line
    return [Finding(s.name, "missing-tool", "tool_missing", {"line": ln, "cmd": cmd}) for cmd, ln in missing.items()]


def _first_command(line: str) -> str | None:
    line = line.strip().lstrip("$ ").strip()
    if not line or line.startswith(("#", "//", "-", "|", "&&", "\\")):
        return None
    for word in line.split():
        if "=" in word and not word.startswith("-"):
            continue  # VAR=value prefix
        word = word.strip("`'\"()")
        if not word or word in BUILTINS or "/" in word or word.startswith("$"):
            return None
        if not re.fullmatch(r"[a-z][\w+-]*", word):
            return None
        return word
    return None
