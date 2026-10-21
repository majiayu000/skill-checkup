"""Find skills whose descriptions compete for the same requests."""

from __future__ import annotations

from dataclasses import dataclass

from .inventory import Skill
from .text import Corpus


@dataclass
class Cluster:
    members: list[str]
    pairs: list[tuple[str, str, float, list[str]]]  # a, b, similarity, shared terms


def doc(s: Skill) -> str:
    return f"{s.name.replace('-', ' ')} {s.description}"


def find(skills: dict[str, Skill], threshold: float = 0.32) -> list[Cluster]:
    corpus = Corpus({k: doc(s) for k, s in skills.items()})
    keys = corpus.keys
    parent = {k: k for k in keys}

    def root(k: str) -> str:
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    pairs = []
    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            sim = corpus.cosine(corpus.vecs[a], corpus.vecs[b])
            if sim >= threshold:
                pairs.append((a, b, sim, corpus.shared_terms(corpus.vecs[a], corpus.vecs[b])))
                parent[root(a)] = root(b)
    groups: dict[str, list[str]] = {}
    for k in keys:
        groups.setdefault(root(k), []).append(k)
    clusters = []
    for members in groups.values():
        if len(members) < 2:
            continue
        ms = set(members)
        cp = sorted((p for p in pairs if p[0] in ms), key=lambda p: -p[2])
        clusters.append(Cluster(sorted(members), cp))
    return sorted(clusters, key=lambda c: -max(p[2] for p in c.pairs))
