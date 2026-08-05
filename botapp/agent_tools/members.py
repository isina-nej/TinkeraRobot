"""Member information and per-member moderation tools.

All state-changing member operations reuse the project's existing moderation
pipeline (``queue_or_execute`` -> ``ModerationAction`` -> ``execute_telegram_action``)
and warning services. They never call ``restrict_chat_member`` directly.
"""

from __future__ import annotations

from aiogram.exceptions import TelegramAPIError

from botapp.agent.context import AgentContext
from botapp.agent.errors import ProtectedTarget, TelegramOperationError
from botapp.agent.permissions import (
    CAP_RESTRICT,
    MEMBERS_BAN,
    MEMBERS_READ,
    MEMBERS_RESTRICT,
    MEMBERS_WARN,
)
from botapp.agent.registry import register_tool
from botapp.agent.responses import fa_duration, fa_number
from botapp.agent.risk import HIGH, LOW, MEDIUM
from botapp.agent.schemas import MuteParams, TargetParams

from ._common import actor_from_context, target_namespace


async def _target_is_protected(ctx: AgentContext, bot, user_id: int) -> bool:
    """True if the target is the bot itself or a group admin.

    Fails CLOSED: if the admin status cannot be determined, treat the target as
    protected so a moderation action is never taken against a possible admin.
    """
    from botapp.telegram_gateway import is_chat_admin

    try:
        me = await bot.me()
        if int(user_id) == int(me.id):
            return True
        return await is_chat_admin(bot, ctx.chat_id, int(user_id))
    except Exception:
        return True


async def get_info(ctx: AgentContext, bot, params: TargetParams) -> str:
    try:
        member = await bot.get_chat_member(ctx.chat_id, params.target_user_id)
    except TelegramAPIError as exc:
        raise TelegramOperationError() from exc
    user = getattr(member, "user", None)
    label = getattr(user, "full_name", "") or getattr(user, "username", "") or str(params.target_user_id)
    return (
        f"👤 اطلاعات کاربر: {label}\n"
        f"شناسه: {fa_number(params.target_user_id)}\n"
        f"وضعیت در گروه: {getattr(member, 'status', 'نامشخص')}"
    )


async def get_warnings(ctx: AgentContext, bot, params: TargetParams) -> str:
    from botapp.services import get_active_warning_count

    count = await get_active_warning_count(ctx.group_settings.id, params.target_user_id)
    return f"⚠️ تعداد اخطارهای فعال کاربر {fa_number(params.target_user_id)}: {fa_number(count)}"


async def _moderate(ctx: AgentContext, bot, action: str, target_user_id: int, *, reason="", duration=None):
    from botapp.telegram_moderation import queue_or_execute

    _, text = await queue_or_execute(
        bot=bot,
        group=ctx.group_settings,
        action=action,
        target=target_namespace(target_user_id),
        actor=actor_from_context(ctx),
        reason=reason,
        duration_minutes=duration,
    )
    return text


async def mute(ctx: AgentContext, bot, params: MuteParams) -> str:
    duration = params.duration_minutes or ctx.group_settings.mute_duration_minutes
    text = await _moderate(
        ctx, bot, "mute", params.target_user_id, reason=params.reason, duration=duration
    )
    return f"🔇 {text} ({fa_duration(duration)})"


async def unmute(ctx: AgentContext, bot, params: TargetParams) -> str:
    text = await _moderate(ctx, bot, "unmute", params.target_user_id)
    return f"🔊 {text}"


async def ban(ctx: AgentContext, bot, params: TargetParams) -> str:
    text = await _moderate(ctx, bot, "ban", params.target_user_id, reason=params.reason)
    return f"⛔ {text}"


async def unban(ctx: AgentContext, bot, params: TargetParams) -> str:
    text = await _moderate(ctx, bot, "unban", params.target_user_id)
    return f"✅ {text}"


async def warn(ctx: AgentContext, bot, params: TargetParams) -> str:
    from botapp.services import add_warning, create_moderation_log

    # Backstop admin/bot protection: warn runs at confirm time, where the
    # orchestrator's pre-execution target check does not re-run. mute/ban are
    # already guarded inside queue_or_execute, but warn writes directly.
    if await _target_is_protected(ctx, bot, params.target_user_id):
        raise ProtectedTarget("❌ کاربر هدف ادمین گروه است و نمی‌توان به او اخطار داد.")

    group = ctx.group_settings
    target_label = str(params.target_user_id)
    actor = actor_from_context(ctx)
    count = await add_warning(
        group.id,
        params.target_user_id,
        target_label,
        actor.id,
        actor.full_name,
        params.reason,
        group.warning_expiry_days,
    )
    await create_moderation_log(
        group.id,
        "warn",
        params.target_user_id,
        target_label,
        actor.id,
        actor.full_name,
        params.reason,
    )
    return (
        f"⚠️ به کاربر {fa_number(params.target_user_id)} اخطار داده شد "
        f"({fa_number(count)}/{fa_number(group.max_warnings)})."
    )


register_tool(
    name="member.get_info",
    description="اطلاعات پایه یک کاربر (نیازمند ریپلای به پیام او).",
    input_schema=TargetParams,
    permission=MEMBERS_READ,
    risk_level=LOW,
    requires_confirmation=False,
    handler=get_info,
    target_kind="member",
)
register_tool(
    name="member.get_warnings",
    description="تعداد اخطارهای فعال یک کاربر.",
    input_schema=TargetParams,
    permission=MEMBERS_READ,
    risk_level=LOW,
    requires_confirmation=False,
    handler=get_warnings,
    target_kind="member",
)
register_tool(
    name="member.warn",
    description="ثبت اخطار برای یک کاربر.",
    input_schema=TargetParams,
    permission=MEMBERS_WARN,
    risk_level=MEDIUM,
    requires_confirmation=True,
    handler=warn,
    target_kind="member",
    human_verb="اخطار به کاربر",
)
register_tool(
    name="member.mute",
    description="محدودکردن (سکوت) یک کاربر برای مدت مشخص یا دائمی.",
    input_schema=MuteParams,
    permission=MEMBERS_RESTRICT,
    risk_level=HIGH,
    requires_confirmation=True,
    handler=mute,
    capability=CAP_RESTRICT,
    target_kind="member",
    human_verb="محدودکردن کاربر",
)
register_tool(
    name="member.unmute",
    description="رفع محدودیت (سکوت) یک کاربر.",
    input_schema=TargetParams,
    permission=MEMBERS_RESTRICT,
    risk_level=MEDIUM,
    requires_confirmation=True,
    handler=unmute,
    capability=CAP_RESTRICT,
    target_kind="member",
    human_verb="رفع محدودیت کاربر",
)
register_tool(
    name="member.ban",
    description="بن‌کردن (اخراج و مسدودسازی) یک کاربر از گروه.",
    input_schema=TargetParams,
    permission=MEMBERS_BAN,
    risk_level=HIGH,
    requires_confirmation=True,
    handler=ban,
    capability=CAP_RESTRICT,
    target_kind="member",
    human_verb="بن کاربر",
)
register_tool(
    name="member.unban",
    description="رفع بن یک کاربر.",
    input_schema=TargetParams,
    permission=MEMBERS_BAN,
    risk_level=MEDIUM,
    requires_confirmation=True,
    handler=unban,
    capability=CAP_RESTRICT,
    target_kind="member",
    human_verb="رفع بن کاربر",
)
