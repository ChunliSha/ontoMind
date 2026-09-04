"""Keyword ranking for instance search (ILIKE recall + alias scoring)."""

from __future__ import annotations

import re

from app.topology.normalize import normalize_alias

_LEADING_NUM = re.compile(r"^\d+")


def score_hit(
    q: str,
    *,
    label: str,
    local_name: str | None = None,
    class_label: str | None = None,
    data_values: dict[str, str] | None = None,
) -> float:
    needle = (q or "").strip()
    if not needle:
        return 0.0
    nq = normalize_alias(needle)
    best = _score_label_fields(needle, nq, label, local_name, class_label)
    return max(best, _score_data_values(needle, nq, data_values))


def _score_label_fields(
    needle: str,
    nq: str,
    label: str,
    local_name: str | None,
    class_label: str | None,
) -> float:
    nl = normalize_alias(label)
    nn = normalize_alias(local_name)
    nc = normalize_alias(class_label)
    best = _score_name_match(needle, nq, nl, label)
    core = _LEADING_NUM.sub("", nq)
    if core and len(core) >= 3 and core in nl and nl != nq:
        best = max(best, 0.68)
    if nq and nn and (nn == nq or nq in nn):
        best = max(best, 0.8)
    if nq and nc and nc == nq:
        best = max(best, 0.55)
    return best


def _score_name_match(needle: str, nq: str, nl: str, label: str) -> float:
    if nq and nl == nq:
        return 1.0
    if nq and nl.startswith(nq):
        return 0.92
    if nq and nq in nl:
        return 0.85
    if needle.lower() in (label or "").lower():
        return 0.72
    return 0.0


def _score_data_values(needle: str, nq: str, data_values: dict[str, str] | None) -> float:
    best = 0.0
    for val in (data_values or {}).values():
        nv = normalize_alias(val)
        if nq and nv == nq:
            best = max(best, 0.88)
        elif nq and nq in nv:
            best = max(best, 0.7)
        elif needle.lower() in (val or "").lower():
            best = max(best, 0.6)
    return best
