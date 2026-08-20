"""Split unstructured documents into overlapping chunks for LLM extraction."""

from __future__ import annotations

import re

_HEADING = re.compile(r"(?m)^#{1,6}\s+.+$|^第.+[章节条]\s*.+$")


def chunk_text(text: str, *, max_chars: int = 3500, overlap: int = 200) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    if len(raw) <= max_chars:
        return [raw]

    parts = _HEADING.split(raw)
    if len(parts) <= 1:
        parts = [p.strip() for p in re.split(r"\n{2,}", raw) if p.strip()]
    packed: list[str] = []
    buf = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if buf and len(buf) + len(part) + 2 > max_chars:
            packed.append(buf)
            tail = buf[-overlap:] if overlap < len(buf) else buf
            buf = (tail + "\n\n" + part).strip()
        else:
            buf = (buf + "\n\n" + part).strip() if buf else part
    if buf:
        packed.append(buf)

    # Hard-split leftovers that are still too long
    out: list[str] = []
    for block in packed:
        if len(block) <= max_chars:
            out.append(block)
            continue
        i = 0
        while i < len(block):
            out.append(block[i : i + max_chars])
            i += max_chars - overlap
    return out


def chunk_documents(texts: list[str], **kwargs) -> list[str]:
    chunks: list[str] = []
    for t in texts:
        chunks.extend(chunk_text(t, **kwargs))
    return chunks
