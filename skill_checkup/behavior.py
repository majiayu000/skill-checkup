"""Behaviour checks over real turns: missed triggers, description replay, new-skill mining, effect."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from .inventory import Skill
from .overlap import doc
from .text import Corpus, tokens
from .turns import Turn
from .usage import explicit_only

MISS_THRESHOLD = 0.38
MINE_THRESHOLD = 0.45
MINE_MIN_SESSIONS = 5
_LATIN_TERM_RE = re.compile(r"[a-z][a-z0-9+-]{1,}")
SNIPPET = 70


def snippet(text: str, width: int = SNIPPET) -> str:
    one = " ".join(text.split())
    return one if len(one) <= width else one[: width - 1] + "…"


# ---------------------------------------------------------------- missed triggers


@dataclass
class Miss:
    skill: str
    turn: Turn
    score: float
    kind: str  # named = user asked for it by name; similar = request resembles the description


NAMED_MAX_CHARS = 400  # past this the name is usually inside pasted material, not a request
BUILD_RE = r"(?:建|新建|创建|写|改|修改|更新|重写|修|build|create|write|edit|update|fix|rename)"


def _request_text(text: str) -> bool:
    """A message a person typed to ask for something, not agent-written or pasted material."""
    return len(text) <= NAMED_MAX_CHARS and "SKILL.md" not in text and not text.lstrip().startswith("<")


def _named(text: str, name: str) -> bool:
    n = re.escape(name)
    end = r"(?![\w/.-])"
    if re.search(rf"{BUILD_RE}[^。\n]{{0,20}}{n}{end}", text, re.I):
        return False  # asking to build or change the skill, not to use it
    return bool(re.search(rf"(?:^|\s)[/$]{n}{end}|(?:用|使用|调用|跑|运行|按)\s*{n}{end}|\buse\s+(?:the\s+)?{n}{end}", text, re.I))


def missed(skills: dict[str, Skill], turns: list[Turn]) -> dict[str, list[Miss]]:
    corpus = Corpus({k: doc(s) for k, s in skills.items()})
    out: dict[str, list[Miss]] = defaultdict(list)
    for t in turns:
        if t.skills or t.text.startswith("/") or len(t.text) < 6:
            continue
        hit = None
        if _request_text(t.text):
            hit = next((name for name in skills if len(name) >= 3 and _named(t.text, name)), None)
        if hit:
            out[hit].append(Miss(hit, t, 1.0, "named"))
            continue
        ranked = corpus.rank(t.text, top=2) if _request_text(t.text) and len(tokens(t.text)) >= 6 else []
        if not ranked:
            continue
        best, score = ranked[0]
        margin = score - (ranked[1][1] if len(ranked) > 1 else 0)
        if score >= MISS_THRESHOLD and margin >= 0.05 and not explicit_only(skills[best]):
            out[best].append(Miss(best, t, score, "similar"))
    return out


# ---------------------------------------------------------------- description replay


@dataclass
class ReplayResult:
    positives: int
    hit_at_1: float
    hit_at_3: float
    false_top1: float  # share of other skills' requests where this skill would rank first
    examples_missed: list[str] = field(default_factory=list)


def replay(skills: dict[str, Skill], turns: list[Turn], target: str, description: str | None = None) -> ReplayResult:
    docs = {k: doc(s) for k, s in skills.items()}
    if description is not None:
        docs[target] = f"{target.replace('-', ' ')} {description}"
    corpus = Corpus(docs)
    pos = [t for t in turns if target in t.skills and not t.text.startswith("/")]
    neg = [t for t in turns if t.skills and target not in t.skills and not t.text.startswith("/")]
    h1 = h3 = 0
    missed_examples = []
    for t in pos:
        ranked = [k for k, _ in corpus.rank(t.text, top=3)]
        h1 += bool(ranked[:1] == [target])
        h3 += target in ranked
        if target not in ranked and len(missed_examples) < 5:
            missed_examples.append(snippet(t.text))
    false = sum(1 for t in neg if [k for k, _ in corpus.rank(t.text, top=1)] == [target])
    n = len(pos) or 1
    return ReplayResult(len(pos), h1 / n, h3 / n, false / (len(neg) or 1), missed_examples)


# ---------------------------------------------------------------- new-skill mining


@dataclass
class Candidate:
    terms: list[str]
    turns: list[Turn]
    covered_by: str = ""  # a skill whose body handles this, though its description doesn't say so
    covered_score: float = 0.0

    @property
    def sessions(self) -> int:
        return len({t.session.sid for t in self.turns})

    @property
    def days(self) -> int:
        return len({t.ts[:10] for t in self.turns})

    @property
    def automated(self) -> bool:
        return len({t.text for t in self.turns}) / len(self.turns) < 0.3


def _covering_skill(skills: dict[str, Skill], cand: "Candidate") -> tuple[str, float]:
    """Requests often mix languages with a skill body (Chinese ask, English body), which defeats
    TF-IDF. Use the English terms the requests share instead: a skill whose name, description or
    body contains every one of them (at least two, plural-insensitive) probably handles this."""
    counts: dict[str, int] = defaultdict(int)
    for t in cand.turns:
        for w in set(_LATIN_TERM_RE.findall(t.text.lower())):
            counts[w.rstrip("s")] += 1
    terms = [w for w, n in counts.items() if n >= max(2, len(cand.turns) // 2) and len(w) >= 2]
    if len(terms) < 2:
        return "", 0.0
    best, best_hits = "", 0
    for name, s in skills.items():
        text = f"{name} {s.description} {s.body}".lower()
        hits = [len(re.findall(rf"\b{re.escape(w)}s?\b", text)) for w in terms]
        if all(hits) and sum(hits) > best_hits:  # every term present; most mentions wins
            best, best_hits = name, sum(hits)
    return (best, 1.0) if best else ("", 0.0)


def mine(skills: dict[str, Skill], turns: list[Turn], min_sessions: int = MINE_MIN_SESSIONS) -> list[Candidate]:
    skill_corpus = Corpus({k: doc(s) for k, s in skills.items()})
    pool = []
    for t in turns:
        if t.skills or t.text.startswith("/") or not _request_text(t.text) or len(tokens(t.text)) < 6:
            continue
        top = skill_corpus.rank(t.text, top=1)
        if top and top[0][1] >= 0.2:
            continue  # an existing skill already covers this kind of request
        pool.append(t)
    if not pool:
        return []
    corpus = Corpus({str(i): t.text[:600] for i, t in enumerate(pool)})
    centroids: list[dict[str, float]] = []
    groups: list[list[int]] = []
    for i in range(len(pool)):
        v = corpus.vecs[str(i)]
        if not v:
            continue
        best, best_sim = -1, 0.0
        for gi, c in enumerate(centroids):
            sim = corpus.cosine(v, c)
            if sim > best_sim:
                best, best_sim = gi, sim
        if best >= 0 and best_sim >= MINE_THRESHOLD:
            groups[best].append(i)
            c = centroids[best]
            n = len(groups[best])
            for k in set(c) | set(v):  # running mean keeps the centroid stable
                c[k] = c.get(k, 0.0) * (n - 1) / n + v.get(k, 0.0) / n
        else:
            centroids.append(dict(v))
            groups.append([i])
    out = []
    for c, g in zip(centroids, groups):
        cand = Candidate(sorted(c, key=lambda k: -c[k])[:6], [pool[i] for i in g])
        if cand.sessions >= min_sessions and cand.days >= 2:
            cand.covered_by, cand.covered_score = _covering_skill(skills, cand)
            out.append(cand)
    return sorted(out, key=lambda c: (bool(c.covered_by), -c.sessions, -len(c.turns)))


# ---------------------------------------------------------------- effect


@dataclass
class Effect:
    skill: str
    runs: int
    interrupted: int
    corrected: int

    @property
    def bad_rate(self) -> float:
        return (self.interrupted + self.corrected) / self.runs if self.runs else 0.0


def effect(turns: list[Turn], min_runs: int = 3) -> list[Effect]:
    stats: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for t in turns:
        for name in set(t.skills):
            st = stats[name]
            st[0] += 1
            st[1] += t.interrupted
            st[2] += (not t.interrupted) and t.corrected_next
    out = [Effect(k, *v) for k, v in stats.items() if v[0] >= min_runs]
    return sorted(out, key=lambda e: (-e.bad_rate, -e.runs))
