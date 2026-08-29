"""Ground a user type phrase onto Schema class labels (no domain synonym tables)."""

from __future__ import annotations

import re

from app.topology.normalize import normalize_alias

# Generic Chinese listing / interrogative wrappers, not domain terms.
_LIST_PREFIX = re.compile(
    r"^(都有)?(有哪些|有什么|哪些|列出|列举|罗列|全部|所有的?|什么)"
)
_TRAIL = re.compile(r"[的呢吗呀啊？?、。，,\s]+$")


def is_list_question(text: str) -> bool:
    s = (text or "").strip()
    return bool(_LIST_PREFIX.match(s))


def extract_type_phrase(text: str) -> str:
    s = (text or "").strip()
    s = _TRAIL.sub("", s)
    # Strip wrappers repeatedly so「列出全部人员」→「人员」, not「全部人员」.
    for _ in range(6):
        nxt = _LIST_PREFIX.sub("", s, count=1)
        nxt = _TRAIL.sub("", nxt).strip()
        if nxt == s:
            break
        s = nxt
    return s.strip()


def looks_like_type_scope(text: str) -> bool:
    """True for listing questions or a short type word (no instance id / digits)."""
    s = (text or "").strip()
    if not s:
        return False
    if is_list_question(s):
        return True
    phrase = extract_type_phrase(s)
    if any(ch.isdigit() for ch in phrase):
        return False
    return 1 <= len(phrase) <= 6


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            ins, delete, sub = cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + (ca != cb)
            cur.append(min(ins, delete, sub))
        prev = cur
    return prev[-1]


def score_class_label(query: str, label: str) -> float:
    nq = normalize_alias(query)
    nl = normalize_alias(label)
    if not nq or not nl:
        return 0.0
    if nq == nl:
        return 1.0
    if nq in nl or nl in nq:
        shorter, longer = (nq, nl) if len(nq) <= len(nl) else (nl, nq)
        return 0.88 + 0.1 * (len(shorter) / len(longer))
    dist = _levenshtein(nq, nl)
    maxlen = max(len(nq), len(nl))
    return max(0.0, 1.0 - dist / maxlen)


def link_class_label(query: str, labels: list[str], *, min_score: float = 0.5) -> str | None:
    """Return a unique best class label, or None when the match is ambiguous/weak."""
    phrase = extract_type_phrase(query) or (query or "").strip()
    if not phrase or not labels:
        return None
    scored: list[tuple[float, str]] = []
    for lab in labels:
        s = score_class_label(phrase, lab)
        if s >= min_score:
            scored.append((s, lab))
    if not scored:
        return None
    scored.sort(key=lambda x: (-x[0], -len(x[1])))
    best_s, best = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    if second > 0 and best_s - second < 0.12:
        return None
    return best
