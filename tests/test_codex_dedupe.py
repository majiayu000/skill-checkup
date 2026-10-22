"""Codex format copies must not hide separate requests with identical text."""

import hashlib
import json
from unittest.mock import patch

from skill_checkup import sessions, turns, usage


def user_line(format_, text, ts="2026-10-01T00:00:00Z"):
    if format_ == "user_message":
        payload = {"type": format_, "message": text}
    else:
        payload = {"type": "item_completed", "item": {
            "type": "UserMessage", "content": [{"type": "text", "text": text}]}}
    return json.dumps({"type": "event_msg", "timestamp": ts, "payload": payload}) + "\n"


def parse(tmp_path, lines):
    path = tmp_path / "s.jsonl"
    path.write_text("".join(lines), encoding="utf-8")
    return sessions.parse_codex(path)


def test_repeated_codex_requests_at_distinct_timestamps(tmp_path):
    first, second = "2026-10-01T00:00:00Z", "2026-10-01T00:01:00Z"
    for a in ("user_message", "item_completed"):
        for b in ("user_message", "item_completed"):
            for text in ("Please try again", "$tidy-notes please"):
                s = parse(tmp_path, [user_line(a, text, first), user_line(b, text, second)])
                assert s.user_texts() == [(first, text), (second, text)]
                if text.startswith("$"):
                    assert usage.aggregate([s])["tidy-notes"].uses == 2


def test_codex_dual_format_copies_match_one_to_one(tmp_path):
    # Same-format occurrences are distinct, even when timestamps coincide.
    for formats in ("nn", "oo", "no", "on", "nno", "oon", "nnoo", "oonn", "nono", "onon"):
        lines = [user_line("user_message" if f == "n" else "item_completed",
                           "$tidy-notes please") for f in formats]
        s = parse(tmp_path, lines)
        expected = max(formats.count("n"), formats.count("o"))
        assert len(s.user_texts()) == expected, formats
        assert usage.aggregate([s])["tidy-notes"].by_via["dollar"] == expected, formats
        assert all(t.skills == ["tidy-notes"] for t in turns.split(s)), formats


def test_codex_dedupe_uses_clean_full_text(tmp_path):
    text = "$tidy-notes please"
    s = parse(tmp_path, [user_line("user_message", text), user_line(
        "item_completed", "# Files mentioned by the user\n\n## My request:\n" + text)])
    assert len(s.user_texts()) == 1
    # Distinct long requests must not match just because storage truncates them.
    prefix = "x" * 4000
    s = parse(tmp_path, [user_line("user_message", prefix + " first"),
                         user_line("item_completed", prefix + " second")])
    assert len(s.user_texts()) == 2


def test_codex_missing_timestamps_do_not_establish_duplicate_identity(tmp_path):
    for a in ("user_message", "item_completed"):
        for b in ("user_message", "item_completed"):
            s = parse(tmp_path, [user_line(a, "$tidy-notes please", ""),
                                 user_line(b, "$tidy-notes please", "")])
            assert len(s.user_texts()) == 2
            assert usage.aggregate([s])["tidy-notes"].uses == 2


def test_codex_repeated_requests_keep_turns_and_usage(tmp_path):
    first, second, third = (f"2026-10-01T00:0{i}:00Z" for i in range(3))
    text = "$tidy-notes please"
    s = parse(tmp_path, [
        user_line("user_message", text, first),
        user_line("item_completed", text, first),
        user_line("item_completed", text, second),
        user_line("user_message", text, second),
        json.dumps({"type": "event_msg", "timestamp": second, "payload": {
            "type": "turn_aborted", "reason": "interrupted"}}) + "\n",
        user_line("user_message", "Wrong, try again", third),
    ])
    parsed = turns.split(s)
    assert [(t.ts, t.text, t.skills) for t in parsed] == [
        (first, text, ["tidy-notes"]), (second, text, ["tidy-notes"]),
        (third, "Wrong, try again", []),
    ]
    assert not parsed[0].interrupted and not parsed[0].corrected_next
    assert parsed[1].interrupted and parsed[1].corrected_next
    u = usage.aggregate([s])["tidy-notes"]
    assert u.uses == 2 and u.by_via == {"dollar": 2} and u.last == second


def test_codex_repeated_requests_keep_audit_sweep_boundaries(tmp_path):
    lines = []
    for turn in range(2):
        ts = f"2026-10-01T00:0{turn}:00Z"
        lines.append(user_line("user_message", "Please inspect these skills", ts))
        for i in range(sessions.AUDIT_DISTINCT_READS // 2):
            lines.append(json.dumps({"type": "response_item", "timestamp": ts, "payload": {
                "type": "function_call", "arguments": json.dumps({
                    "cmd": f"cat skills/skill-{turn}-{i}/SKILL.md"})}}) + "\n")
    s = parse(tmp_path, lines)
    sessions._mark_audit_sweeps(s, sessions.AUDIT_DISTINCT_READS)
    assert len(turns.split(s)) == 2
    assert all(e[3] == "read" for e in s.events if e[0] == "skill")


def test_cached_codex_requests_ignore_lossy_v6_extraction(tmp_path):
    first, second = "2026-10-01T00:00:00Z", "2026-10-01T00:01:00Z"
    text = "$tidy-notes please"
    path = tmp_path / "s.jsonl"
    path.write_text(user_line("user_message", text, first)
                    + user_line("user_message", text, second), encoding="utf-8")
    old = sessions.Session("codex", "s", "", str(path), events=[
        ["user", first, text], ["skill", first, "tidy-notes", "dollar"],
    ])
    st = path.stat()
    key = hashlib.sha1(str(path).encode()).hexdigest()
    cache_home = tmp_path / "cache"
    legacy = cache_home / "skill-checkup" / "v6" / f"{key}.json"
    legacy.parent.mkdir(parents=True)
    stale = json.dumps({"stamp": [st.st_mtime_ns, st.st_size], "session": old.__dict__})
    legacy.write_text(stale)
    with patch.dict("os.environ", {"XDG_CACHE_HOME": str(cache_home)}):
        actual = sessions._cached(path, sessions.parse_codex)
        # The refreshed extraction is reusable without reparsing unchanged files.
        with patch.object(sessions, "parse_codex", side_effect=AssertionError("cache miss")):
            assert sessions._cached(path, sessions.parse_codex) == actual
    assert legacy.read_text() == stale
    assert actual.user_texts() == [(first, text), (second, text)]
    assert usage.aggregate([actual])["tidy-notes"].uses == 2
