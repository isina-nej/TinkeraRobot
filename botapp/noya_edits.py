"""Professional coordination of Telegram ``edited_message`` / streaming bot replies.

Streaming AI bots (e.g. Mira) often deliver:

1. an empty shell message (``text=''`` / empty rich draft) as a reply to Noya;
2. one or more rapid ``edited_message`` updates that fill/grow the body
   (plain ``text`` **or** ``rich_message`` blocks — Mira uses Rich Messages).

This module turns that into **exactly one** Noya answer after the body settles.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from botapp.telegram_rich import extract_message_body

logger = logging.getLogger(__name__)

AnswerCallback = Callable[[Any], Awaitable[None]]

# How long the body must stay unchanged before we treat the stream as finished.
_SETTLE_S = float(os.getenv("NOYA_EDIT_SETTLE_SECONDS", "1.5") or 1.5)
# Absolute deadline from session start (empty shell or first edit).
_MAX_WAIT_S = float(os.getenv("NOYA_EDIT_MAX_WAIT_SECONDS", "15") or 15)
# Remember answered message ids to ignore late cosmetic edits.
_ANSWERED_TTL_S = float(os.getenv("NOYA_EDIT_ANSWERED_TTL_SECONDS", "600") or 600)
_MIN_BODY = int(os.getenv("NOYA_EDIT_MIN_BODY_CHARS", "1") or 1)


def message_body(message) -> str:
    return extract_message_body(message)


def message_key(message) -> tuple[int, int] | None:
    chat = getattr(message, "chat", None)
    mid = getattr(message, "message_id", None)
    if chat is None or mid is None:
        return None
    return int(chat.id), int(mid)


def body_fingerprint(body: str) -> str:
    return hashlib.sha1(body.encode("utf-8", errors="replace")).hexdigest()[:16]


@dataclass
class EditSession:
    key: tuple[int, int]
    latest: Any
    created_at: float = field(default_factory=time.monotonic)
    last_change_at: float = field(default_factory=time.monotonic)
    fingerprint: str = ""
    answered: bool = False
    settle_task: asyncio.Task | None = None
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    reason: str = ""


class NoyaEditCoordinator:
    """Debounce streaming edits and dispatch a single answer callback."""

    def __init__(
        self,
        *,
        settle_seconds: float = _SETTLE_S,
        max_wait_seconds: float = _MAX_WAIT_S,
        answered_ttl_seconds: float = _ANSWERED_TTL_S,
        min_body_chars: int = _MIN_BODY,
    ):
        self.settle_seconds = max(float(settle_seconds), 0.2)
        self.max_wait_seconds = max(float(max_wait_seconds), self.settle_seconds)
        self.answered_ttl_seconds = max(float(answered_ttl_seconds), 30.0)
        self.min_body_chars = max(int(min_body_chars), 1)
        self._sessions: dict[tuple[int, int], EditSession] = {}
        self._answered: dict[tuple[int, int], tuple[str, float]] = {}
        self._lock = asyncio.Lock()
        self._answer_cb: AnswerCallback | None = None

    def set_answer_callback(self, callback: AnswerCallback) -> None:
        self._answer_cb = callback

    def reset_for_tests(self) -> None:
        for session in list(self._sessions.values()):
            if session.settle_task and not session.settle_task.done():
                session.settle_task.cancel()
        self._sessions.clear()
        self._answered.clear()
        self._answer_cb = None

    def _purge_answered(self, now: float) -> None:
        dead = [
            key
            for key, (_, ts) in self._answered.items()
            if now - ts > self.answered_ttl_seconds
        ]
        for key in dead:
            self._answered.pop(key, None)

    def already_answered(self, message, *, body: str | None = None) -> bool:
        key = message_key(message)
        if key is None:
            return False
        now = time.monotonic()
        self._purge_answered(now)
        entry = self._answered.get(key)
        if not entry:
            return False
        fp, _ = entry
        if body is None:
            return True
        # Same settled fingerprint → ignore; different body after answer → ignore
        # too (we answer once per message_id to stop edit ping-pong).
        return True if fp else True

    async def observe_empty_shell(self, message, *, reason: str = "empty_shell") -> None:
        """Track an empty bot reply; settle loop will wait for body + quiet period."""
        key = message_key(message)
        if key is None:
            return
        async with self._lock:
            self._purge_answered(time.monotonic())
            if key in self._answered:
                return
            session = self._sessions.get(key)
            if session is None:
                session = EditSession(key=key, latest=message, reason=reason)
                self._sessions[key] = session
                session.settle_task = asyncio.create_task(
                    self._settle_loop(key),
                    name=f"noya-edit-settle-{key[0]}-{key[1]}",
                )
            else:
                session.latest = message
                session.wake.set()
            logger.warning(
                "noya_edit_session_open chat=%s msg=%s reason=%s",
                key[0],
                key[1],
                reason,
            )

    async def observe_edit(self, message, *, reason: str = "edited") -> str:
        """Ingest an edited_message.

        Returns one of: ``ignored``, ``tracked``, ``dispatched_inline``.
        Prefer letting the settle loop dispatch; ``dispatched_inline`` is unused
        reserved for future sync paths.
        """
        key = message_key(message)
        if key is None:
            return "ignored"
        body = message_body(message)
        if len(body) < self.min_body_chars:
            # Still empty edit — keep/extend session.
            await self.observe_empty_shell(message, reason="edit_still_empty")
            return "tracked"

        fp = body_fingerprint(body)
        now = time.monotonic()
        async with self._lock:
            self._purge_answered(now)
            if key in self._answered:
                logger.warning(
                    "noya_edit_ignored_already_answered chat=%s msg=%s fp=%s",
                    key[0],
                    key[1],
                    fp,
                )
                return "ignored"

            session = self._sessions.get(key)
            if session is None:
                session = EditSession(
                    key=key,
                    latest=message,
                    fingerprint=fp,
                    reason=reason,
                )
                self._sessions[key] = session
                session.settle_task = asyncio.create_task(
                    self._settle_loop(key),
                    name=f"noya-edit-settle-{key[0]}-{key[1]}",
                )
            else:
                if fp != session.fingerprint:
                    session.fingerprint = fp
                    session.last_change_at = now
                session.latest = message
                session.wake.set()

            logger.warning(
                "noya_edit_tracked chat=%s msg=%s reason=%s fp=%s len=%s",
                key[0],
                key[1],
                reason,
                fp,
                len(body),
            )
            return "tracked"

    async def _settle_loop(self, key: tuple[int, int]) -> None:
        try:
            while True:
                async with self._lock:
                    session = self._sessions.get(key)
                    if session is None or session.answered:
                        return
                    latest = session.latest
                    created = session.created_at
                    last_change = session.last_change_at
                    wake = session.wake
                    wake.clear()

                now = time.monotonic()
                body = message_body(latest)
                age = now - created
                quiet_for = now - last_change

                if age >= self.max_wait_seconds:
                    if len(body) >= self.min_body_chars:
                        await self._dispatch(key, latest, reason="max_wait")
                    else:
                        await self._drop(key, reason="max_wait_empty")
                    return

                if len(body) >= self.min_body_chars and quiet_for >= self.settle_seconds:
                    await self._dispatch(key, latest, reason="settled")
                    return

                # Sleep until settle window elapses, or until woken by a newer edit.
                sleep_for = self.settle_seconds - quiet_for
                if len(body) < self.min_body_chars:
                    sleep_for = min(0.5, max(self.max_wait_seconds - age, 0.1))
                else:
                    sleep_for = max(sleep_for, 0.05)
                sleep_for = min(sleep_for, max(self.max_wait_seconds - age, 0.05))
                try:
                    await asyncio.wait_for(wake.wait(), timeout=sleep_for)
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("noya_edit_settle_loop_failed key=%s", key)
            await self._drop(key, reason="error")

    async def _dispatch(self, key: tuple[int, int], message, *, reason: str) -> None:
        body = message_body(message)
        fp = body_fingerprint(body) if body else ""
        callback = self._answer_cb
        async with self._lock:
            session = self._sessions.pop(key, None)
            if session is None or session.answered:
                return
            session.answered = True
            self._answered[key] = (fp, time.monotonic())
        if callback is None or not body:
            logger.warning(
                "noya_edit_dispatch_skipped chat=%s msg=%s reason=%s body_len=%s",
                key[0],
                key[1],
                reason,
                len(body),
            )
            return
        logger.warning(
            "noya_edit_dispatch chat=%s msg=%s reason=%s fp=%s len=%s",
            key[0],
            key[1],
            reason,
            fp,
            len(body),
        )
        try:
            await callback(message)
        except Exception:
            logger.exception(
                "noya_edit_answer_failed chat=%s msg=%s",
                key[0],
                key[1],
            )

    async def _drop(self, key: tuple[int, int], *, reason: str) -> None:
        async with self._lock:
            self._sessions.pop(key, None)
        logger.warning(
            "noya_edit_session_drop chat=%s msg=%s reason=%s",
            key[0],
            key[1],
            reason,
        )


# Process-wide coordinator used by runbot handlers.
coordinator = NoyaEditCoordinator()
