"""Group information and group-level moderation tools."""

from __future__ import annotations

from aiogram.exceptions import TelegramAPIError

from botapp.agent.context import AgentContext
from botapp.agent.errors import TelegramOperationError
from botapp.agent.permissions import (
    CAP_RESTRICT,
    GROUP_READ,
    MEMBERS_RESTRICT,
    SETTINGS_READ,
)
from botapp.agent.registry import register_tool
from botapp.agent.responses import fa_number
from botapp.agent.schemas import EmptyParams, LockParams
from botapp.agent.risk import HIGH, LOW, MEDIUM

from ._common import actor_from_context


async def get_member_count(ctx: AgentContext, bot, params) -> str:
    try:
        count = await bot.get_chat_member_count(ctx.chat_id)
    except TelegramAPIError as exc:
        raise TelegramOperationError() from exc
    return f"👥 تعداد اعضای فعلی گروه: {fa_number(count)} نفر"


async def get_info(ctx: AgentContext, bot, params) -> str:
    try:
        chat = await bot.get_chat(ctx.chat_id)
        count = await bot.get_chat_member_count(ctx.chat_id)
    except TelegramAPIError as exc:
        raise TelegramOperationError() from exc
    lines = [
        f"ℹ️ اطلاعات گروه: {getattr(chat, 'title', '') or ctx.chat_title}",
        f"شناسه: {fa_number(ctx.chat_id)}",
        f"نوع: {getattr(chat, 'type', ctx.chat_type)}",
        f"تعداد اعضا: {fa_number(count)} نفر",
    ]
    if getattr(chat, "username", ""):
        lines.append(f"یوزرنیم: @{chat.username}")
    return "\n".join(lines)


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
    header = f"👮 تعداد ادمین‌های گروه: {fa_number(len(names))} نفر"
    return header + ("\n\n" + "\n".join(names[:30]) if names else "")


async def get_bot_permissions(ctx: AgentContext, bot, params) -> str:
    caps = ctx.bot_capabilities
    if not caps.is_admin:
        return "🤖 ربات در این گروه ادمین نیست و دسترسی مدیریتی ندارد."
    def mark(value: bool) -> str:
        return "✅" if value else "❌"
    return (
        "🤖 دسترسی‌های فعلی ربات:\n"
        f"{mark(caps.can_restrict_members)} محدودکردن اعضا\n"
        f"{mark(caps.can_delete_messages)} حذف پیام‌ها\n"
        f"{mark(caps.can_pin_messages)} پین پیام‌ها"
    )


async def get_settings(ctx: AgentContext, bot, params) -> str:
    group = ctx.group_settings
    if group is None:
        return "تنظیماتی برای این گروه ثبت نشده است."

    def mark(value: bool) -> str:
        return "✅" if value else "❌"

    return (
        f"⚙️ تنظیمات گروه: {group.chat_title or ctx.chat_id}\n\n"
        f"{mark(group.moderation_enabled)} مدیریت\n"
        f"{mark(group.anti_spam_enabled)} ضداسپم\n"
        f"{mark(group.anti_link_enabled)} ضدلینک\n"
        f"{mark(group.anti_forward_enabled)} ضدفوروارد\n"
        f"{mark(group.welcome_enabled)} خوش‌آمد\n"
        f"سقف اخطار: {fa_number(group.max_warnings)}\n"
        f"محدودیت پیام: {fa_number(group.flood_limit)} پیام در {fa_number(group.flood_window_seconds)} ثانیه\n"
        f"مدت mute خودکار: {fa_number(group.mute_duration_minutes)} دقیقه\n"
        f"دامنه‌های مجاز: {fa_number(len(group.allowed_domains))} مورد\n"
        f"کلمات ممنوع: {fa_number(len(group.blocked_words))} مورد"
    )


async def get_moderation_status(ctx: AgentContext, bot, params) -> str:
    group = ctx.group_settings
    if group is None:
        return "وضعیت مدیریتی برای این گروه ثبت نشده است."

    def state(value: bool) -> str:
        return "فعال ✅" if value else "غیرفعال ❌"

    return (
        "🛡 وضعیت مدیریت گروه:\n"
        f"مدیریت کلی: {state(group.moderation_enabled)}\n"
        f"ضداسپم: {state(group.anti_spam_enabled)}\n"
        f"ضدلینک: {state(group.anti_link_enabled)}\n"
        f"ضدفوروارد: {state(group.anti_forward_enabled)}"
    )


async def get_schedules(ctx: AgentContext, bot, params) -> str:
    from asgiref.sync import sync_to_async

    from botapp.models import GroupSchedule

    @sync_to_async(thread_sensitive=True)
    def load():
        if ctx.group_settings is None:
            return []
        return [
            (s.action, s.time_of_day.strftime("%H:%M"), s.is_active)
            for s in GroupSchedule.objects.filter(group=ctx.group_settings)
        ]

    rows = await load()
    if not rows:
        return "هیچ زمان‌بندی روزانه‌ای برای این گروه ثبت نشده است."
    labels = {"lock": "قفل", "unlock": "بازکردن"}
    lines = [
        f"• {labels.get(action, action)} ساعت {time_str} ({'فعال' if active else 'غیرفعال'})"
        for action, time_str, active in rows
    ]
    return "🗓 زمان‌بندی‌های روزانه:\n" + "\n".join(lines)


async def lock_group(ctx: AgentContext, bot, params: LockParams) -> str:
    from botapp.telegram_moderation import queue_or_execute

    _, text = await queue_or_execute(
        bot=bot,
        group=ctx.group_settings,
        action="lock",
        actor=actor_from_context(ctx),
        reason=params.reason,
        delay_minutes=params.delay_minutes,
        duration_minutes=params.duration_minutes,
    )
    return f"🔒 {text}"


async def unlock_group(ctx: AgentContext, bot, params) -> str:
    from botapp.telegram_moderation import queue_or_execute

    _, text = await queue_or_execute(
        bot=bot,
        group=ctx.group_settings,
        action="unlock",
        actor=actor_from_context(ctx),
    )
    return f"🔓 {text}"


register_tool(
    name="group.get_info",
    description="اطلاعات کلی گروه شامل عنوان، نوع و تعداد اعضا.",
    input_schema=EmptyParams,
    permission=GROUP_READ,
    risk_level=LOW,
    requires_confirmation=False,
    handler=get_info,
)
register_tool(
    name="group.get_member_count",
    description="تعداد اعضای فعلی گروه.",
    input_schema=EmptyParams,
    permission=GROUP_READ,
    risk_level=LOW,
    requires_confirmation=False,
    handler=get_member_count,
)
register_tool(
    name="group.get_admins",
    description="فهرست و تعداد ادمین‌های گروه.",
    input_schema=EmptyParams,
    permission=GROUP_READ,
    risk_level=LOW,
    requires_confirmation=False,
    handler=get_admins,
)
register_tool(
    name="group.get_bot_permissions",
    description="دسترسی‌های فعلی خود ربات در گروه.",
    input_schema=EmptyParams,
    permission=GROUP_READ,
    risk_level=LOW,
    requires_confirmation=False,
    handler=get_bot_permissions,
)
register_tool(
    name="group.get_settings",
    description="نمایش تنظیمات گروه.",
    input_schema=EmptyParams,
    permission=SETTINGS_READ,
    risk_level=LOW,
    requires_confirmation=False,
    handler=get_settings,
)
register_tool(
    name="group.get_moderation_status",
    description="وضعیت فعال/غیرفعال قابلیت‌های مدیریتی.",
    input_schema=EmptyParams,
    permission=SETTINGS_READ,
    risk_level=LOW,
    requires_confirmation=False,
    handler=get_moderation_status,
)
register_tool(
    name="group.get_schedules",
    description="زمان‌بندی‌های روزانه قفل/بازکردن گروه.",
    input_schema=EmptyParams,
    permission=SETTINGS_READ,
    risk_level=LOW,
    requires_confirmation=False,
    handler=get_schedules,
)
register_tool(
    name="group.lock",
    description="قفل‌کردن گروه (جلوگیری از ارسال پیام اعضا).",
    input_schema=LockParams,
    permission=MEMBERS_RESTRICT,
    risk_level=HIGH,
    requires_confirmation=True,
    handler=lock_group,
    capability=CAP_RESTRICT,
    human_verb="قفل گروه",
)
register_tool(
    name="group.unlock",
    description="بازکردن گروهِ قفل‌شده.",
    input_schema=EmptyParams,
    permission=MEMBERS_RESTRICT,
    risk_level=MEDIUM,
    requires_confirmation=True,
    handler=unlock_group,
    capability=CAP_RESTRICT,
    human_verb="بازکردن گروه",
)
