"""Find skills whose descriptions compete for the same requests."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .inventory import Skill
from .text import Corpus
from .usage import explicit_only


@dataclass
class Cluster:
    members: list[str]
    pairs: list[tuple[str, str, float, list[str]]]  # a, b, similarity, shared terms


def doc(s: Skill) -> str:
    return f"{s.name.replace('-', ' ')} {s.description}"


def _mentions(s: Skill, name: str) -> bool:
    text = s.description.lower()
    return name.lower() in text or name.replace("-", " ").lower() in text


def _routes_to(s: Skill, name: str) -> bool:
    """The description sends some requests to `name`. A one-word name such as `codex` is usually
    the product, so it only counts when quoted or right after a routing word."""
    text, n = s.description.lower(), re.escape(name.lower())
    if "-" in name:
        return name.lower() in text
    return bool(re.search(rf"`{n}`|(?:走|改用|转到|交给|\buse|\bsee|\bvia)\s*`?{n}\b", text))


def bounded(a: Skill, b: Skill) -> bool:
    """The authors already separated these two: one description routes to the other, or both are
    explicit-only and name themselves, so a request has to say which one it wants."""
    if _routes_to(a, b.name) or _routes_to(b, a.name):
        return True
    return explicit_only(a) and explicit_only(b) and _mentions(a, a.name) and _mentions(b, b.name)


def find(skills: dict[str, Skill], threshold: float = 0.32) -> list[Cluster]:
    """Complete-link grouping: a skill joins a group only if it is similar to every member, so
    shared boilerplate cannot chain unrelated skills into one large group."""
    corpus = Corpus({k: doc(s) for k, s in skills.items()})
    keys = corpus.keys
    sims: dict[frozenset, tuple[str, str, float, list[str]]] = {}
    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            sim = corpus.cosine(corpus.vecs[a], corpus.vecs[b])
            if sim >= threshold and not bounded(skills[a], skills[b]):
                sims[frozenset((a, b))] = (a, b, sim, corpus.shared_terms(corpus.vecs[a], corpus.vecs[b]))
    groups: list[set[str]] = []
    placed: set[str] = set()
    for a, b, _, _ in sorted(sims.values(), key=lambda p: -p[2]):
        if a in placed and b in placed:
            continue
        home = next((g for g in groups if (a in g) != (b in g)), None)
        if home is not None:
            new = b if a in home else a
            if all(frozenset((new, m)) in sims for m in home):
                home.add(new)
                placed.add(new)
            continue
        if a not in placed and b not in placed:
            groups.append({a, b})
            placed.update((a, b))
    clusters = []
    for g in groups:
        pairs = sorted((p for k, p in sims.items() if k <= g), key=lambda p: -p[2])
        clusters.append(Cluster(sorted(g), pairs))
    return sorted(clusters, key=lambda c: -c.pairs[0][2])
