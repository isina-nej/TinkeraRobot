"""Confirmation callback processing (confirm / cancel)."""

from __future__ import annotations

from dataclasses import dataclass

from asgiref.sync import sync_to_async

from . import confirmations
from .errors import AgentError
from .orchestrator import execute_confirmed


@dataclass
class CallbackResult:
    text: str
    handled: bool = True


def parse_callback(data: str) -> tuple[str, str] | None:
    """Return ``(action, raw_token)`` for a valid agent callback, else ``None``."""
    if data and data.startswith(confirmations.CONFIRM_PREFIX):
        return "confirm", data[len(confirmations.CONFIRM_PREFIX):]
    if data and data.startswith(confirmations.CANCEL_PREFIX):
        return "cancel", data[len(confirmations.CANCEL_PREFIX):]
    return None


async def process_confirm(bot, raw_token: str, *, user_id: int, chat_id: int) -> CallbackResult:
    try:
        confirmation = await sync_to_async(
            confirmations.claim_for_execution, thread_sensitive=True
        )(raw_token, requester_user_id=user_id, chat_id=chat_id)
    except AgentError as exc:
        return CallbackResult(text=exc.user_message)
    text = await execute_confirmed(bot, confirmation)
    return CallbackResult(text=f"✅ انجام شد.\n\n{text}")


async def process_cancel(bot, raw_token: str, *, user_id: int, chat_id: int) -> CallbackResult:
    try:
        await sync_to_async(
            confirmations.cancel_confirmation, thread_sensitive=True
        )(raw_token, requester_user_id=user_id, chat_id=chat_id)
    except AgentError as exc:
        return CallbackResult(text=exc.user_message)
    return CallbackResult(text="❌ عملیات لغو شد.")
