"""Analytics tools based on data actually recorded by the project."""

from __future__ import annotations

from datetime import timedelta

from asgiref.sync import sync_to_async
from django.db.models import Count
from django.utils import timezone

from botapp.agent.context import AgentContext
from botapp.agent.permissions import ANALYTICS_READ
from botapp.agent.registry import register_tool
from botapp.agent.responses import fa_number
from botapp.agent.risk import LOW
from botapp.agent.schemas import EmptyParams

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


@sync_to_async(thread_sensitive=True)
def _summary(group_id: int, since):
    from botapp.models import ModerationLog

    rows = (
        ModerationLog.objects.filter(group_id=group_id, created_at__gte=since)
        .values("action")
        .annotate(total=Count("id"))
        .order_by("-total")
    )
    return [(row["action"], row["total"]) for row in rows]


async def _render_summary(ctx: AgentContext, since, header: str) -> str:
    if ctx.group_settings is None:
        return "داده‌ای برای این گروه ثبت نشده است."
    rows = await _summary(ctx.group_settings.id, since)
    if not rows:
        return f"{header}\nهیچ عملیات مدیریتی ثبت نشده است."
    total = sum(count for _, count in rows)
    lines = [f"• {_ACTION_LABELS.get(action, action)}: {fa_number(count)}" for action, count in rows]
    return f"{header}\nمجموع عملیات: {fa_number(total)}\n" + "\n".join(lines)


async def today_summary(ctx: AgentContext, bot, params) -> str:
    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    return await _render_summary(ctx, start, "📊 آمار عملیات مدیریتی امروز:")


async def period_summary(ctx: AgentContext, bot, params) -> str:
    since = timezone.now() - timedelta(days=7)
    return await _render_summary(ctx, since, "📊 آمار عملیات مدیریتی ۷ روز اخیر:")


register_tool(
    name="analytics.get_today_summary",
    description="خلاصه عملیات مدیریتی امروز.",
    input_schema=EmptyParams,
    permission=ANALYTICS_READ,
    risk_level=LOW,
    requires_confirmation=False,
    handler=today_summary,
)
register_tool(
    name="analytics.get_period_summary",
    description="خلاصه عملیات مدیریتی ۷ روز اخیر.",
    input_schema=EmptyParams,
    permission=ANALYTICS_READ,
    risk_level=LOW,
    requires_confirmation=False,
    handler=period_summary,
)
