"""Audit/report tools reading the project's moderation log."""

from __future__ import annotations

from asgiref.sync import sync_to_async

from botapp.agent.context import AgentContext
from botapp.agent.permissions import AUDIT_READ
from botapp.agent.registry import register_tool
from botapp.agent.responses import fa_number
from botapp.agent.risk import LOW
from botapp.agent.schemas import EmptyParams, TargetParams

_ACTION_LABELS = {
    "warn": "اخطار",
    "mute": "سکوت",
    "unmute": "رفع سکوت",
    "ban": "بن",
    "unban": "رفع بن",
    "lock": "قفل",
    "unlock": "بازکردن",
    "delete": "حذف",
    "filter": "فیلتر",
}


def _format_logs(rows) -> str:
    if not rows:
        return "هیچ عملیات مدیریتی ثبت نشده است."
    lines = []
    for action, target_name, actor_name, when in rows:
        label = _ACTION_LABELS.get(action, action)
        target = target_name or "-"
        actor = actor_name or "-"
        lines.append(f"• {when.strftime('%m-%d %H:%M')} | {label} | هدف: {target} | توسط: {actor}")
    return "\n".join(lines)


@sync_to_async(thread_sensitive=True)
def _recent(group_id: int, limit: int, *, actor_id=None, target_id=None):
    from botapp.models import ModerationLog

    qs = ModerationLog.objects.filter(group_id=group_id)
    if actor_id is not None:
        qs = qs.filter(actor_user_id=actor_id)
    if target_id is not None:
        qs = qs.filter(target_user_id=target_id)
    return [
        (r.action, r.target_name, r.actor_name, r.created_at)
        for r in qs.order_by("-created_at")[: max(limit, 1)]
    ]


async def get_recent_actions(ctx: AgentContext, bot, params) -> str:
    if ctx.group_settings is None:
        return "داده‌ای برای این گروه ثبت نشده است."
    rows = await _recent(ctx.group_settings.id, 5)
    return "📜 آخرین عملیات مدیریتی:\n" + _format_logs(rows)


async def get_actions_for_member(ctx: AgentContext, bot, params: TargetParams) -> str:
    if ctx.group_settings is None:
        return "داده‌ای برای این گروه ثبت نشده است."
    rows = await _recent(ctx.group_settings.id, 5, target_id=params.target_user_id)
    header = f"📜 آخرین عملیات روی کاربر {fa_number(params.target_user_id)}:\n"
    return header + _format_logs(rows)


register_tool(
    name="audit.get_recent_actions",
    description="آخرین عملیات مدیریتی ثبت‌شده در گروه.",
    input_schema=EmptyParams,
    permission=AUDIT_READ,
    risk_level=LOW,
    requires_confirmation=False,
    handler=get_recent_actions,
)
register_tool(
    name="audit.get_actions_for_member",
    description="آخرین عملیات مدیریتی روی یک کاربر مشخص.",
    input_schema=TargetParams,
    permission=AUDIT_READ,
    risk_level=LOW,
    requires_confirmation=False,
    handler=get_actions_for_member,
    target_kind="member",
)
