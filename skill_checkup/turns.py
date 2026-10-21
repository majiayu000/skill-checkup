"""Split sessions into turns (one user message plus what followed) for the behaviour checks."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .sessions import Session

CORRECTION = re.compile(
    r"^.{0,30}?(不对|错了|搞错|不是这样|不是这个|不是我要|你理解错|理解错了|重来|重新做|撤销|回滚|别这样|不要这样|还是不行|没用|白做|"
    r"\bwrong\b|\brevert\b|\bundo\b|that'?s not|not what i)",
    re.I | re.S,
)


@dataclass
class Turn:
    session: Session
    index: int
    ts: str
    text: str
    skills: list[str] = field(default_factory=list)  # non-audit skills reached in this turn
    interrupted: bool = False
    next_text: str | None = None

    @property
    def corrected_next(self) -> bool:
        return bool(self.next_text and CORRECTION.search(self.next_text))


def split(s: Session) -> list[Turn]:
    turns: list[Turn] = []
    pending: list[str] = []  # skill events before the first user text (e.g. slash with no args)
    for e in s.events:
        if e[0] == "user":
            t = Turn(s, len(turns), e[1], e[2], skills=pending)
            pending = []
            if turns:
                turns[-1].next_text = e[2]
            turns.append(t)
        elif e[0] == "skill" and e[3] != "audit":
            (turns[-1].skills if turns else pending).append(e[2])
        elif e[0] == "interrupt" and turns:
            turns[-1].interrupted = True
    return turns
