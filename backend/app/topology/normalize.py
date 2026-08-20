"""String normalization for instance alias lookup."""

from __future__ import annotations

import re
import unicodedata

_SPACE_RE = re.compile(r"[\s\-_·•、，,。；;：:（）()【】\[\]{}]+")
_PUNCT_RE = re.compile(r"[\"'`~!@#$%^&*+=|\\/<>?]+")


def normalize_alias(text: str | None) -> str:
    """Stable lookup key: strip, NFKC, lowercase, drop spaces/punctuation."""
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", str(text)).strip().lower()
    s = _SPACE_RE.sub("", s)
    s = _PUNCT_RE.sub("", s)
    return s
