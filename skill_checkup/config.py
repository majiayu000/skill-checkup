"""Optional per-user settings. Everything works without a config file.

~/.config/skill-checkup/config.json (or $XDG_CONFIG_HOME/skill-checkup/config.json):

{
  "deprecated_roots": ["~/.old-skill-registry"],
  "known_issues": {"deprecated-root": {"some-skill": "why it is accepted for now"}}
}
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "skill-checkup" / "config.json"


@dataclass
class Config:
    deprecated_roots: list[Path] = field(default_factory=list)
    known_issues: dict[str, dict[str, str]] = field(default_factory=dict)


def load(path: Path | None = None) -> Config:
    path = path or config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Config()
    roots = [Path(os.path.expanduser(p)) for p in raw.get("deprecated_roots", []) if isinstance(p, str)]
    known = raw.get("known_issues") if isinstance(raw.get("known_issues"), dict) else {}
    return Config(deprecated_roots=roots, known_issues=known)
