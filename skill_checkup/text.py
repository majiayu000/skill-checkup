"""Tokenizing and TF-IDF similarity shared by overlap, missed-trigger and mining checks.

CJK text has no spaces, so it is split into character bigrams; Latin text into
lower-cased words. Good enough to rank candidates; never a final verdict.
"""

from __future__ import annotations

import math
import re
from collections import Counter

_LATIN_RE = re.compile(r"[a-z][a-z0-9_+-]{1,}")
_CJK_RE = re.compile(r"[㐀-鿿]+")

STOPWORDS = {
    # English filler that dominates skill descriptions
    "the", "and", "for", "use", "when", "with", "this", "that", "you", "are", "from",
    "into", "skill", "skills", "user", "users", "asks", "asked", "explicitly", "requested",
    "ignore", "mentions", "traces", "incidental", "not", "only", "any", "can", "will",
    "use when", "your", "via", "e.g", "etc", "such", "also", "who", "what", "how",
    "it", "its", "or", "to", "of", "in", "on", "is", "be", "as", "by", "an", "at",
    # Chinese filler bigrams
    "使用", "用户", "时候", "当用", "户说", "以及", "或者", "进行", "可以", "需要",
    "这个", "一个", "什么", "我们", "你们", "他们", "不要", "就是", "还是", "如果",
    # conversational glue that clusters status pings instead of tasks
    "怎么", "么样", "样了", "了呢", "看看", "你看", "现在", "是什", "这是", "的呢", "帮我", "我看",
    "一下", "下吗", "了吗", "吗？", "呢？", "还有", "有什", "么可", "可以", "以吗", "我的", "你的",
    "你再", "再看", "在怎", "么做", "是怎", "做的", "个库", "这个库", "看这", "能帮", "我一", "一个个",
}


def tokens(text: str) -> list[str]:
    text = text.lower()
    out = [w for w in _LATIN_RE.findall(text) if w not in STOPWORDS]
    for run in _CJK_RE.findall(text):
        if len(run) == 1:
            continue
        out.extend(b for b in (run[i : i + 2] for i in range(len(run) - 1)) if b not in STOPWORDS)
    return out


class Corpus:
    """TF-IDF vectors over a fixed set of documents (usually skill descriptions)."""

    def __init__(self, docs: dict[str, str]):
        self.keys = list(docs)
        counts = {k: Counter(tokens(v)) for k, v in docs.items()}
        df: Counter[str] = Counter()
        for c in counts.values():
            df.update(c.keys())
        n = max(len(docs), 1)
        self.idf = {t: math.log((1 + n) / (1 + d)) + 1 for t, d in df.items()}
        self.vecs = {k: self._weigh(c) for k, c in counts.items()}

    def _weigh(self, counts: Counter[str]) -> dict[str, float]:
        vec = {t: (1 + math.log(c)) * self.idf.get(t, 0.0) for t, c in counts.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {t: v / norm for t, v in vec.items() if v}

    def vector(self, text: str) -> dict[str, float]:
        return self._weigh(Counter(t for t in tokens(text) if t in self.idf))

    @staticmethod
    def cosine(a: dict[str, float], b: dict[str, float]) -> float:
        if len(a) > len(b):
            a, b = b, a
        return sum(v * b.get(t, 0.0) for t, v in a.items())

    def shared_terms(self, a: dict[str, float], b: dict[str, float], limit: int = 6) -> list[str]:
        common = sorted(set(a) & set(b), key=lambda t: -(a[t] * b[t]))
        return common[:limit]

    def rank(self, text: str, top: int = 3) -> list[tuple[str, float]]:
        v = self.vector(text)
        if not v:
            return []
        scored = ((k, self.cosine(v, self.vecs[k])) for k in self.keys)
        return sorted((s for s in scored if s[1] > 0), key=lambda s: -s[1])[:top]


def approx_tokens(text: str) -> int:
    """Rough token estimate: ~1 token per CJK char, ~4 chars per token otherwise."""
    cjk = sum(len(r) for r in _CJK_RE.findall(text))
    return cjk + max(0, len(text) - cjk) // 4
