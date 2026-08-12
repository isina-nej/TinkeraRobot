"""Allow Noya to answer other bots (Telegram bot-to-bot) with loop guards.

Telegram only *delivers* other bots' messages when Bot-to-Bot Communication
Mode is enabled in @BotFather. This module does not turn that on (BotFather
only); it makes sure that once updates arrive, we:

* answer other bots that reply to / mention Noya;
* never answer ourselves;
* rate-limit per (chat, sender bot) to stop reply loops.
* wait briefly for empty shell messages that later get edited (streaming bots).
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import defaultdict, deque
from threading import Lock

# Defaults are conservative; override with env if needed.
_DEFAULT_WINDOW_S = float(os.getenv("NOYA_BOT_REPLY_WINDOW_SECONDS", "12") or 12)
_DEFAULT_MAX = int(os.getenv("NOYA_BOT_REPLY_MAX_PER_WINDOW", "2") or 2)
_EDIT_WAIT_S = float(os.getenv("NOYA_BOT_EMPTY_EDIT_WAIT_SECONDS", "6") or 6)

_lock = Lock()
_hits: dict[tuple[int, int], deque[float]] = defaultdict(deque)
_pending_edits: dict[tuple[int, int], dict] = {}
_pending_lock = asyncio.Lock()


def is_other_bot_sender(message, *, self_bot_id: int | None) -> bool:
    user = getattr(message, "from_user", None)
    if user is None or not getattr(user, "is_bot", False):
        return False
    if self_bot_id is not None and int(user.id) == int(self_bot_id):
        return False
    return True


def is_self_bot_message(message, *, self_bot_id: int | None) -> bool:
    user = getattr(message, "from_user", None)
    if user is None or self_bot_id is None:
        return False
    return bool(getattr(user, "is_bot", False) and int(user.id) == int(self_bot_id))


def allow_bot_to_bot_reply(
    chat_id: int,
    sender_bot_id: int,
    *,
    window_seconds: float | None = None,
    max_per_window: int | None = None,
) -> bool:
    """Return True if we may answer this bot now (sliding window)."""
    window = float(_DEFAULT_WINDOW_S if window_seconds is None else window_seconds)
    limit = int(_DEFAULT_MAX if max_per_window is None else max_per_window)
    if window <= 0 or limit <= 0:
        return True
    key = (int(chat_id), int(sender_bot_id))
    now = time.monotonic()
    with _lock:
        q = _hits[key]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


def reset_bot_reply_limits_for_tests() -> None:
    with _lock:
        _hits.clear()
    _pending_edits.clear()


async def watch_empty_bot_reply(message) -> None:
    """Remember an empty bot reply so a later edit can wake the waiter."""
    chat = getattr(message, "chat", None)
    if chat is None or getattr(message, "message_id", None) is None:
        return
    key = (int(chat.id), int(message.message_id))
    async with _pending_lock:
        slot = _pending_edits.get(key)
        if slot is None:
            slot = {"event": asyncio.Event(), "message": message}
            _pending_edits[key] = slot
        else:
            slot["message"] = message


async def notify_bot_reply_edit(message) -> bool:
    """Wake any waiter when an edited body arrives. True if a waiter exists."""
    chat = getattr(message, "chat", None)
    if chat is None or getattr(message, "message_id", None) is None:
        return False
    body = (getattr(message, "text", None) or getattr(message, "caption", None) or "").strip()
    if not body:
        return False
    key = (int(chat.id), int(message.message_id))
    async with _pending_lock:
        slot = _pending_edits.get(key)
        if not slot:
            return False
        slot["message"] = message
        slot["event"].set()
        return True


async def wait_for_bot_reply_body(message, *, timeout: float | None = None):
    """Wait for text/caption to appear on an empty bot reply (edit/stream)."""
    chat = getattr(message, "chat", None)
    if chat is None:
        return message
    key = (int(chat.id), int(message.message_id))
    body = (getattr(message, "text", None) or getattr(message, "caption", None) or "").strip()
    if body:
        return message
    await watch_empty_bot_reply(message)
    timeout = _EDIT_WAIT_S if timeout is None else float(timeout)
    async with _pending_lock:
        slot = _pending_edits.get(key)
        event = slot["event"] if slot else None
    if event is None:
        return message
    try:
        await asyncio.wait_for(event.wait(), timeout=max(timeout, 0.1))
    except asyncio.TimeoutError:
        pass
    async with _pending_lock:
        slot = _pending_edits.pop(key, None)
        return (slot or {}).get("message", message)
