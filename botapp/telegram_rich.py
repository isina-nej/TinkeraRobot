"""Flatten Telegram Rich Messages into plain text for Noya.

Some peer bots (e.g. Mira) send ``ContentType.RICH_MESSAGE`` with empty
``text`` / ``caption``. The readable content lives in ``message.rich_message``.
"""

from __future__ import annotations

from typing import Any, Iterable

# Attribute names that commonly hold nested rich text / blocks.
_NESTED_ATTRS = (
    "text",
    "summary",
    "credit",
    "caption",
    "expression",
    "alternative_text",
    "blocks",
    "items",
    "cells",
    "rows",
)


def rich_plain_text(node: Any, *, _depth: int = 0) -> str:
    """Recursively extract human-readable text from a RichMessage / block / RichText."""
    if node is None or _depth > 40:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, (int, float, bool)):
        return ""
    if isinstance(node, dict):
        parts = [rich_plain_text(v, _depth=_depth + 1) for v in node.values()]
        return _join_parts(parts)
    if isinstance(node, (list, tuple)):
        parts = [rich_plain_text(item, _depth=_depth + 1) for item in node]
        return _join_parts(parts)

    parts: list[str] = []
    for attr in _NESTED_ATTRS:
        if hasattr(node, attr):
            val = getattr(node, attr, None)
            if val is None or val is node:
                continue
            chunk = rich_plain_text(val, _depth=_depth + 1)
            if chunk:
                parts.append(chunk)
    return _join_parts(parts)


def _join_parts(parts: Iterable[str]) -> str:
    cleaned = [p.strip() for p in parts if p and str(p).strip()]
    if not cleaned:
        return ""
    # Prefer paragraph breaks between block-level chunks; collapse excess blank lines later.
    return "\n".join(cleaned)


def extract_message_body(message: Any) -> str:
    """Plain body from text, caption, or rich_message (in that preference order)."""
    if message is None:
        return ""
    text = getattr(message, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()
    caption = getattr(message, "caption", None)
    if isinstance(caption, str) and caption.strip():
        return caption.strip()
    rich = getattr(message, "rich_message", None)
    if rich is not None:
        return rich_plain_text(rich).strip()
    return ""
