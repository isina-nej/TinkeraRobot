"""Message operation tools: delete, pin, unpin, and archive reporting."""

from __future__ import annotations

from aiogram.exceptions import TelegramAPIError
from asgiref.sync import sync_to_async

from botapp.agent.context import AgentContext
from botapp.agent.errors import ArchiveUnavailable, TelegramOperationError
from botapp.agent.permissions import (
    CAP_DELETE,
    CAP_PIN,
    AUDIT_READ,
    MESSAGES_DELETE,
    MESSAGES_PIN,
)
from botapp.agent.registry import register_tool
from botapp.agent.responses import fa_number
from botapp.agent.risk import LOW, MEDIUM
from botapp.agent.schemas import EmptyParams, MessageTargetParams
from botapp import message_archive


async def delete_message(ctx: AgentContext, bot, params: MessageTargetParams) -> str:
    try:
        await bot.delete_message(ctx.chat_id, params.message_id)
    except TelegramAPIError as exc:
        raise TelegramOperationError() from exc
    await sync_to_async(message_archive.mark_deleted_by_bot, thread_sensitive=True)(
        ctx.chat_id, [params.message_id], reason="agent.delete"
    )
    return "🗑 پیام موردنظر حذف شد."


async def pin_message(ctx: AgentContext, bot, params: MessageTargetParams) -> str:
    try:
        await bot.pin_chat_message(ctx.chat_id, params.message_id, disable_notification=True)
    except TelegramAPIError as exc:
        raise TelegramOperationError() from exc
    return "📌 پیام موردنظر پین شد."


async def unpin_message(ctx: AgentContext, bot, params: MessageTargetParams) -> str:
    try:
        await bot.unpin_chat_message(ctx.chat_id, params.message_id)
    except TelegramAPIError as exc:
        raise TelegramOperationError() from exc
    return "📍 پین پیام موردنظر برداشته شد."


def _format_snapshot(snapshot) -> str:
    who = snapshot.sender_username and f"@{snapshot.sender_username}"
    who = who or snapshot.sender_name or (snapshot.sender_user_id and str(snapshot.sender_user_id)) or "نامشخص"
    body = (snapshot.text or snapshot.caption or f"[{snapshot.content_type}]").strip()
    if len(body) > 200:
        body = body[:200] + "…"
    lines = [f"فرستنده: {who}", f"متن: {body}"]
    if snapshot.deletion_reason:
        lines.append(f"علت حذف: {snapshot.deletion_reason}")
    if snapshot.deleted_by_bot_at:
        lines.append(f"زمان حذف: {snapshot.deleted_by_bot_at.strftime('%Y-%m-%d %H:%M')}")
    return "\n".join(lines)


async def get_bot_deleted_recent(ctx: AgentContext, bot, params) -> str:
    if not message_archive.archive_enabled():
        raise ArchiveUnavailable(
            "Telegram برای گروه‌های عادی رویداد عمومی حذف پیام در اختیار ربات قرار نمی‌دهد. "
            "فقط پیام‌های ثبت‌شده و حذف‌شده توسط خود ربات قابل گزارش هستند و آرشیو این گروه فعال نیست."
        )
    rows = await sync_to_async(message_archive.recent_bot_deleted, thread_sensitive=True)(ctx.chat_id, 5)
    if not rows:
        return (
            "هیچ پیام حذف‌شده‌ای توسط ربات ثبت نشده است.\n"
            "توجه: ربات فقط پیام‌هایی را که خودش حذف کرده گزارش می‌دهد؛ "
            "حذف دستی کاربران در تلگرام برای ربات قابل مشاهده نیست."
        )
    blocks = "\n\n".join(_format_snapshot(row) for row in rows)
    return f"🗑 آخرین پیام‌های حذف‌شده توسط ربات:\n\n{blocks}"


async def get_recent_archived(ctx: AgentContext, bot, params) -> str:
    if not message_archive.archive_enabled():
        raise ArchiveUnavailable()
    rows = await sync_to_async(message_archive.recent_archived, thread_sensitive=True)(ctx.chat_id, 5)
    if not rows:
        return "هیچ پیام آرشیوشده‌ای برای این گروه وجود ندارد."
    blocks = "\n\n".join(_format_snapshot(row) for row in rows)
    return f"🗂 آخرین پیام‌های آرشیوشده:\n\n{blocks}"


register_tool(
    name="message.delete",
    description="حذف یک پیام مشخص (نیازمند ریپلای).",
    input_schema=MessageTargetParams,
    permission=MESSAGES_DELETE,
    risk_level=MEDIUM,
    requires_confirmation=True,
    handler=delete_message,
    capability=CAP_DELETE,
    target_kind="message",
    human_verb="حذف پیام",
)
register_tool(
    name="message.pin",
    description="پین‌کردن یک پیام (نیازمند ریپلای).",
    input_schema=MessageTargetParams,
    permission=MESSAGES_PIN,
    risk_level=MEDIUM,
    requires_confirmation=True,
    handler=pin_message,
    capability=CAP_PIN,
    target_kind="message",
    human_verb="پین پیام",
)
register_tool(
    name="message.unpin",
    description="برداشتن پین یک پیام (نیازمند ریپلای).",
    input_schema=MessageTargetParams,
    permission=MESSAGES_PIN,
    risk_level=MEDIUM,
    requires_confirmation=True,
    handler=unpin_message,
    capability=CAP_PIN,
    target_kind="message",
    human_verb="برداشتن پین",
)
register_tool(
    name="message.get_bot_deleted_recent",
    description="گزارش آخرین پیام‌هایی که خود ربات حذف کرده است.",
    input_schema=EmptyParams,
    permission=AUDIT_READ,
    risk_level=LOW,
    requires_confirmation=False,
    handler=get_bot_deleted_recent,
)
register_tool(
    name="message.get_recent_archived",
    description="گزارش آخرین پیام‌های آرشیوشده توسط ربات.",
    input_schema=EmptyParams,
    permission=AUDIT_READ,
    risk_level=LOW,
    requires_confirmation=False,
    handler=get_recent_archived,
)
