"""Channel-focused agent tools (Bot API capabilities).

Channel admins typically drive these from a private chat by naming
``@channel`` / ``-100…`` as the target. Write ops always require confirmation.
"""

from __future__ import annotations

from aiogram.exceptions import TelegramAPIError

from botapp.agent.context import AgentContext
from botapp.agent.errors import TelegramOperationError
from botapp.agent.permissions import (
    CAP_DELETE,
    CAP_PIN,
    CAP_POST,
    CHANNEL_POST,
    CHANNEL_READ,
    MESSAGES_DELETE,
    MESSAGES_PIN,
)
from botapp.agent.registry import register_tool
from botapp.agent.responses import fa_number
from botapp.agent.risk import HIGH, LOW, MEDIUM
from botapp.agent.schemas import EmptyParams, MessageTargetParams, TextContentParams


async def get_info(ctx: AgentContext, bot, params) -> str:
    try:
        chat = await bot.get_chat(ctx.chat_id)
        count = await bot.get_chat_member_count(ctx.chat_id)
    except TelegramAPIError as exc:
        raise TelegramOperationError() from exc
    lines = [
        f"ℹ️ اطلاعات کانال: {getattr(chat, 'title', '') or ctx.chat_title}",
        f"شناسه: {fa_number(ctx.chat_id)}",
        f"نوع: {getattr(chat, 'type', ctx.chat_type)}",
        f"تعداد اعضا/مشترک: {fa_number(count)} نفر",
    ]
    if getattr(chat, "username", ""):
        lines.append(f"یوزرنیم: @{chat.username}")
    description = (getattr(chat, "description", None) or "").strip()
    if description:
        lines.append(f"توضیح: {description[:280]}{'…' if len(description) > 280 else ''}")
    return "\n".join(lines)


async def get_subscriber_count(ctx: AgentContext, bot, params) -> str:
    try:
        count = await bot.get_chat_member_count(ctx.chat_id)
    except TelegramAPIError as exc:
        raise TelegramOperationError() from exc
    return f"📣 تعداد مشترکین کانال: {fa_number(count)} نفر"


async def get_admins(ctx: AgentContext, bot, params) -> str:
    try:
        admins = await bot.get_chat_administrators(ctx.chat_id)
    except TelegramAPIError as exc:
        raise TelegramOperationError() from exc
    names = []
    for admin in admins:
        user = getattr(admin, "user", None)
        if not user:
            continue
        label = getattr(user, "full_name", "") or getattr(user, "username", "") or str(user.id)
        marker = "👑" if getattr(admin, "status", "") == "creator" else "🛡"
        names.append(f"{marker} {label}")
    header = f"👮 تعداد ادمین‌های کانال: {fa_number(len(names))} نفر"
    return header + ("\n\n" + "\n".join(names[:30]) if names else "")


async def delete_post(ctx: AgentContext, bot, params) -> str:
    try:
        await bot.delete_message(ctx.chat_id, int(params.message_id))
    except TelegramAPIError as exc:
        raise TelegramOperationError() from exc
    return f"🗑 پست کانال (شناسه {fa_number(params.message_id)}) حذف شد."


async def pin_post(ctx: AgentContext, bot, params) -> str:
    try:
        await bot.pin_chat_message(ctx.chat_id, int(params.message_id), disable_notification=True)
    except TelegramAPIError as exc:
        raise TelegramOperationError() from exc
    return f"📌 پست کانال (شناسه {fa_number(params.message_id)}) پین شد."


async def unpin_post(ctx: AgentContext, bot, params) -> str:
    try:
        await bot.unpin_chat_message(ctx.chat_id)
    except TelegramAPIError as exc:
        raise TelegramOperationError() from exc
    return "📌 پین پست کانال برداشته شد."


async def post_text(ctx: AgentContext, bot, params) -> str:
    text = (params.value or "").strip()
    try:
        sent = await bot.send_message(ctx.chat_id, text)
    except TelegramAPIError as exc:
        raise TelegramOperationError() from exc
    return f"✅ پیام در کانال ارسال شد (شناسه پست: {fa_number(sent.message_id)})."


register_tool(
    name="channel.get_info",
    description="اطلاعات کانال هدف (عنوان، شناسه، تعداد مشترک، یوزرنیم).",
    input_schema=EmptyParams,
    permission=CHANNEL_READ,
    risk_level=LOW,
    requires_confirmation=False,
    handler=get_info,
    human_verb="نمایش اطلاعات کانال",
)
register_tool(
    name="channel.get_subscriber_count",
    description="تعداد مشترکین کانال.",
    input_schema=EmptyParams,
    permission=CHANNEL_READ,
    risk_level=LOW,
    requires_confirmation=False,
    handler=get_subscriber_count,
    human_verb="نمایش تعداد مشترکین",
)
register_tool(
    name="channel.get_admins",
    description="لیست ادمین‌های کانال.",
    input_schema=EmptyParams,
    permission=CHANNEL_READ,
    risk_level=LOW,
    requires_confirmation=False,
    handler=get_admins,
    human_verb="نمایش ادمین‌های کانال",
)
register_tool(
    name="channel.delete_post",
    description="حذف پست کانال (نیاز به Reply روی پست یا message_id).",
    input_schema=MessageTargetParams,
    permission=MESSAGES_DELETE,
    risk_level=HIGH,
    requires_confirmation=True,
    handler=delete_post,
    capability=CAP_DELETE,
    target_kind="message",
    human_verb="حذف پست کانال",
)
register_tool(
    name="channel.pin_post",
    description="پین کردن پست کانال (نیاز به Reply).",
    input_schema=MessageTargetParams,
    permission=MESSAGES_PIN,
    risk_level=MEDIUM,
    requires_confirmation=True,
    handler=pin_post,
    capability=CAP_PIN,
    target_kind="message",
    human_verb="پین پست کانال",
)
register_tool(
    name="channel.unpin_post",
    description="برداشتن پین فعلی کانال.",
    input_schema=EmptyParams,
    permission=MESSAGES_PIN,
    risk_level=MEDIUM,
    requires_confirmation=True,
    handler=unpin_post,
    capability=CAP_PIN,
    human_verb="برداشتن پین کانال",
)
register_tool(
    name="channel.post_text",
    description="ارسال یک متن به کانال (value = متن پست).",
    input_schema=TextContentParams,
    permission=CHANNEL_POST,
    risk_level=HIGH,
    requires_confirmation=True,
    handler=post_text,
    capability=CAP_POST,
    human_verb="ارسال پست به کانال",
)
