"""Detect when a group message is addressing Noya (reply / @mention / name)."""

from __future__ import annotations

import re

_NOYA_NAME_RE = re.compile(r"(?<![\wآ-ی])نویا(?![\wآ-ی])", re.IGNORECASE)


def is_addressing_noya(
    message,
    *,
    bot_id: int | None = None,
    bot_username: str = "",
) -> bool:
    """True if this update is a reply to us, @mentions us, or calls «نویا»."""
    replied = getattr(message, "reply_to_message", None)
    replied_user = getattr(replied, "from_user", None) if replied else None
    if (
        replied_user is not None
        and bot_id is not None
        and int(getattr(replied_user, "id", 0) or 0) == int(bot_id)
    ):
        return True

    body = (getattr(message, "text", None) or getattr(message, "caption", None) or "")
    if not body:
        return False
    if bot_username:
        if re.search(rf"@{re.escape(bot_username)}\b", body, flags=re.IGNORECASE):
            return True
        if re.search(rf"/\w+@{re.escape(bot_username)}\b", body, flags=re.IGNORECASE):
            return True
    return bool(_NOYA_NAME_RE.search(body))
