"""Normalize Claude Code and Codex session logs into ordered event lists.

Transcript text is untrusted data: it is only counted and compared, never executed.
Each file's extraction is cached by (mtime, size) because the raw logs are many GB.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

CACHE_VERSION = "v8"


def claude_projects() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"


def codex_sessions() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "sessions"


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "skill-checkup" / CACHE_VERSION

# The folder a SKILL.md was read from, so a "remove this copy" suggestion never targets the copy in use.
SKILL_READ_RE = re.compile(r"(?:\.(claude|agents|codex)/)?skills/([A-Za-z0-9_.:-]+)/SKILL\.md")
CLAUDE_SKILL_FILE_RE = re.compile(r"/skills/([A-Za-z0-9_.:-]+)/SKILL\.md$")
CODEX_DOLLAR_RE = re.compile(r"(?<![\w$])\$([a-z][a-z0-9-]{2,})")
COMMAND_RE = re.compile(r"<command-name>/?([^<\s]+)</command-name>")
COMMAND_ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.S)
AUDIT_DISTINCT_READS = 8  # one turn reading this many skills is an inventory sweep, not use
READ_DEDUPE = timedelta(minutes=5)
# Programmatic entry points (claude -p, Agent SDK, codex exec): scheduled jobs and harnesses,
# not a person typing. Their usage counts, their "user" messages are prompts, not requests.
AUTOMATED_ENTRIES = {"sdk-cli", "sdk-py", "sdk-ts", "codex_exec", "mirasim"}
# Built-in slash commands that are not skills.
BUILTIN_COMMANDS = {
    "model", "login", "logout", "compact", "clear", "mcp", "config", "cost", "doctor", "help", "init",
    "memory", "permissions", "resume", "status", "review", "exit", "agents", "hooks", "ide", "plugin",
    "context", "usage", "fast", "effort", "rewind", "export", "add-dir", "bug", "vim", "theme",
    "terminal-setup", "upgrade", "release-notes", "statusline", "todos", "output-style", "privacy-settings",
    "install-github-app", "pr-comments", "security-review", "artifacts", "workflows", "tasks", "btw",
}
# Context blocks a client wraps around the typed message, e.g. <in-app-browser-context>.
INJECTED_BLOCK_RE = re.compile(r"<([a-z]+(?:[-_][a-z]+)+)\b[^>]*>.*?</\1>", re.S)
REQUEST_MARKER_RE = re.compile(r"^## My request(?: for Codex)?:\s*$", re.M)
PASTED_RE = re.compile(r"<pasted_content[^>]*>.*?</pasted_content[^>]*>", re.S)

# Kinds: user (text), skill (name, via), interrupt
# via: tool = Claude Skill tool, slash = /command, dollar = Codex $name, read = Codex SKILL.md read,
#      audit = read during a bulk sweep (excluded from usage)


@dataclass
class Session:
    runtime: str
    sid: str
    cwd: str
    path: str
    events: list[list] = field(default_factory=list)  # [kind, ts, *payload]
    entry: str = ""

    @property
    def automated(self) -> bool:
        return self.entry in AUTOMATED_ENTRIES

    def user_texts(self) -> list[tuple[str, str]]:
        return [(e[1], e[2]) for e in self.events if e[0] == "user"]


def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _clean_user_text(text: str) -> str | None:
    t = text.strip()
    if not t:
        return None
    noise = ("<local-command", "<system-reminder", "Caveat:", "<bash-", "<task-notification",
             "<side-sessions-event", "<environment_context", "<user_instructions", "# AGENTS.md",
             "<turn_aborted", "<subagent_notification", "<ci-monitor-event", "<user_shell_command", "<artifact-view-context", "<artifact-comment")
    if t.startswith(noise):
        return None
    if t.startswith(("Another Claude session sent a message", "[SYSTEM NOTIFICATION",
                     "This session is being continued from a previous conversation")):
        return None
    marker = list(REQUEST_MARKER_RE.finditer(t))
    if marker:  # Codex prepends attachments and app state, then "## My request:"
        t = t[marker[-1].end():].strip()
    elif t.startswith("# Files mentioned by the user"):
        return None
    t = PASTED_RE.sub(" [粘贴内容] ", t).strip()  # pasted material is not the user's own request
    t = INJECTED_BLOCK_RE.sub(" ", t).strip()
    return t or None


# ---------------------------------------------------------------- Claude


def parse_claude(path: Path) -> Session:
    s = Session("claude", path.stem, "", str(path))
    last_read: dict[str, datetime] = {}
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"user"' not in line and '"Skill"' not in line and "SKILL.md" not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if not isinstance(d, dict) or d.get("isSidechain"):
                continue
            s.cwd = s.cwd or d.get("cwd") or ""
            s.entry = s.entry or d.get("entrypoint") or ""
            ts = d.get("timestamp") or ""
            msg = d.get("message")
            if not isinstance(msg, dict):
                continue
            content = msg.get("content")
            if d.get("type") == "assistant" and isinstance(content, list):
                for item in content:
                    if not isinstance(item, dict) or item.get("type") != "tool_use":
                        continue
                    if item.get("name") == "Skill":
                        name = (item.get("input") or {}).get("skill")
                        if isinstance(name, str) and name.strip():
                            s.events.append(["skill", ts, name.strip().split(":")[-1], "tool"])
                    elif item.get("name") == "Read":
                        # Agents often open a skill's SKILL.md directly instead of calling the Skill tool.
                        path_arg = (item.get("input") or {}).get("file_path")
                        m = CLAUDE_SKILL_FILE_RE.search(path_arg) if isinstance(path_arg, str) else None
                        if m:
                            _skill_reads(s, ts, path_arg, last_read)
                continue
            if d.get("type") != "user" or d.get("isMeta"):
                continue
            if isinstance(content, str):
                texts = [content]
            elif isinstance(content, list):
                if any(isinstance(i, dict) and i.get("type") == "tool_result" for i in content):
                    continue
                texts = [i.get("text", "") for i in content if isinstance(i, dict) and i.get("type") == "text"]
            else:
                continue
            text = "\n".join(texts)
            if text.lstrip().startswith("[Request interrupted by user"):
                s.events.append(["interrupt", ts])
                continue
            cmd = COMMAND_RE.search(text)
            if cmd:
                name = cmd.group(1).split(":")[-1]
                args = COMMAND_ARGS_RE.search(text)
                s.events.append(["user", ts, f"/{name} {args.group(1).strip() if args else ''}".strip()])
                if name not in BUILTIN_COMMANDS:
                    s.events.append(["skill", ts, name, "slash"])
                continue
            clean = _clean_user_text(text)
            if clean:
                s.events.append(["user", ts, clean[:4000]])
    return s


# ---------------------------------------------------------------- Codex

_CODEX_KEYS = ('"user_message"', '"UserMessage"', "SKILL.md", '"turn_aborted"', '"session_meta"', '"turn_context"')


def parse_codex(path: Path) -> Session:
    s = Session("codex", path.stem[-36:], "", str(path))
    last_read: dict[str, datetime] = {}
    unmatched_user: dict[tuple[str, str], tuple[str, int]] = {}
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not any(k in line for k in _CODEX_KEYS):
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if not isinstance(d, dict):
                continue
            ts = d.get("timestamp") or ""
            p = d.get("payload")
            if not isinstance(p, dict):
                continue
            kind = d.get("type")
            if kind == "session_meta":
                s.sid = p.get("id") or p.get("session_id") or s.sid
                s.cwd = p.get("cwd") or s.cwd
                s.entry = p.get("originator") or s.entry
                continue
            if kind == "turn_context":
                s.cwd = s.cwd or p.get("cwd") or ""
                continue
            ptype = p.get("type")
            if ptype == "turn_aborted" and p.get("reason") == "interrupted":
                s.events.append(["interrupt", ts])
                continue
            text = None
            if ptype == "user_message":
                text = p.get("message") if isinstance(p.get("message"), str) else None
            elif ptype == "item_completed" and isinstance(p.get("item"), dict):
                item = p["item"]
                if item.get("type") == "UserMessage":
                    text = "\n".join(c.get("text", "") for c in item.get("content", []) if isinstance(c, dict))
                else:
                    if item.get("type") == "CommandExecution":
                        _skill_reads(s, ts, " ".join(map(str, item.get("command") or [])), last_read)
                    continue
            elif ptype in ("function_call", "custom_tool_call"):
                raw = p.get("arguments") if ptype == "function_call" else p.get("input")
                if isinstance(raw, str):
                    _skill_reads(s, ts, raw, last_read)
                continue
            if text is None:
                continue
            clean = _clean_user_text(text)
            if not clean:
                continue
            # Conservatively pair same-timestamp old/new format copies one-to-one.
            # Without a timestamp, matching text alone cannot establish identity.
            if isinstance(ts, str) and ts:
                key = (ts, clean)
                previous, count = unmatched_user.get(key, (ptype, 0))
                if previous != ptype:
                    if count == 1:
                        del unmatched_user[key]
                    else:
                        unmatched_user[key] = (previous, count - 1)
                    continue
                unmatched_user[key] = (ptype, count + 1)
            s.events.append(["user", ts, clean[:4000]])
            for name in sorted(set(CODEX_DOLLAR_RE.findall(clean))):
                s.events.append(["skill", ts, name, "dollar"])
    return s


def _skill_reads(s: Session, ts: str, text: str, last_read: dict[str, datetime]) -> None:
    when = _parse_ts(ts)
    roots: dict[str, str] = {}
    for m in SKILL_READ_RE.finditer(text):
        roots.setdefault(m.group(2), m.group(1) or "")
    for name in sorted(roots):
        prev = last_read.get(name)
        if when and prev and when - prev < READ_DEDUPE:
            continue
        if when:
            last_read[name] = when
        s.events.append(["skill", ts, name, "read", roots[name]])  # 5th field: .claude/.agents/.codex or ""


def _mark_audit_sweeps(s: Session, min_reads: int) -> None:
    """Between two user messages, many distinct SKILL.md reads means an inventory sweep."""
    for e in s.events:
        if e[0] == "skill" and e[3] == "audit":
            e[3] = "read"
    start = 0
    for i in range(len(s.events) + 1):
        if i == len(s.events) or s.events[i][0] == "user":
            reads = [e for e in s.events[start:i] if e[0] == "skill" and e[3] == "read"]
            if len({e[2] for e in reads}) >= min_reads:
                for e in reads:
                    e[3] = "audit"
            start = i + 1


# ---------------------------------------------------------------- loading


def _cached(path: Path, parser) -> Session:
    st = path.stat()
    key = hashlib.sha1(str(path).encode()).hexdigest()
    cache = cache_dir() / f"{key}.json"
    stamp = [st.st_mtime_ns, st.st_size]
    try:
        data = json.loads(cache.read_text())
        if data["stamp"] == stamp:
            return Session(**data["session"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    sess = parser(path)
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"stamp": stamp, "session": sess.__dict__}, ensure_ascii=False))
    except OSError:
        pass
    return sess


def iter_sessions(since_days: int, claude: bool = True, codex: bool = True,
                  sweep_reads: int = AUDIT_DISTINCT_READS) -> Iterator[Session]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    cutoff_ts = cutoff.timestamp()
    if claude and claude_projects().is_dir():
        for f in claude_projects().glob("*/*.jsonl"):
            try:
                if f.stat().st_mtime < cutoff_ts:
                    continue
            except OSError:
                continue
            sess = _cached(f, parse_claude)
            _mark_audit_sweeps(sess, sweep_reads)
            if sess.events:
                yield sess
    if codex and codex_sessions().is_dir():
        for f in codex_sessions().glob("*/*/*/*.jsonl"):
            y, m, dd = f.parts[-4:-1]
            try:
                if datetime(int(y), int(m), int(dd), tzinfo=timezone.utc) < cutoff - timedelta(days=1):
                    continue
            except ValueError:
                continue
            sess = _cached(f, parse_codex)
            _mark_audit_sweeps(sess, sweep_reads)
            if sess.events:
                yield sess
