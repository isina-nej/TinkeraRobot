"""Group settings tools (read + write)."""

from __future__ import annotations

from asgiref.sync import sync_to_async

from botapp.agent.context import AgentContext
from botapp.agent.permissions import SETTINGS_READ, SETTINGS_WRITE
from botapp.agent.registry import register_tool
from botapp.agent.responses import fa_number
from botapp.agent.risk import LOW, MEDIUM
from botapp.agent.schemas import EmptyParams, IntValueParams, WordParams

from ._common import save_group_field


def _toggle_tool(field: str, value: bool, label: str, on: bool):
    async def handler(ctx: AgentContext, bot, params) -> str:
        await save_group_field(ctx.chat_id, field, value)
        state = "فعال ✅" if value else "غیرفعال ❌"
        return f"⚙️ {label} {state} شد."

    handler.__name__ = f"{'enable' if on else 'disable'}_{field}"
    return handler


async def set_flood_limit(ctx: AgentContext, bot, params: IntValueParams) -> str:
    await save_group_field(ctx.chat_id, "flood_limit", params.value)
    return f"⚙️ محدودیت پیام روی {fa_number(params.value)} تنظیم شد."


async def set_max_warnings(ctx: AgentContext, bot, params: IntValueParams) -> str:
    await save_group_field(ctx.chat_id, "max_warnings", params.value)
    return f"⚙️ سقف اخطار روی {fa_number(params.value)} تنظیم شد."


def _list_words_tool(field: str, label: str):
    async def handler(ctx: AgentContext, bot, params) -> str:
        @sync_to_async(thread_sensitive=True)
        def load():
            from botapp.models import GroupSettings

            group, _ = GroupSettings.objects.get_or_create(chat_id=ctx.chat_id)
            return list(getattr(group, field))

        items = await load()
        if not items:
            return f"فهرست {label} خالی است."
        return f"📋 {label} ({fa_number(len(items))} مورد):\n" + "\n".join(f"• {w}" for w in items[:50])

    handler.__name__ = f"get_{field}"
    return handler


def _mutate_list_tool(field: str, label: str, add: bool):
    async def handler(ctx: AgentContext, bot, params: WordParams) -> str:
        @sync_to_async(thread_sensitive=True)
        def mutate():
            from botapp.models import GroupSettings

            group, _ = GroupSettings.objects.get_or_create(chat_id=ctx.chat_id)
            values = list(getattr(group, field))
            item = params.value.strip()
            if add and item not in values:
                values.append(item)
            elif not add:
                values = [v for v in values if v != item]
            setattr(group, field, values)
            group.save(update_fields=[field, "updated_at"])
            return len(values)

        count = await mutate()
        verb = "افزوده" if add else "حذف"
        return f"⚙️ «{params.value}» {verb} شد؛ اکنون {fa_number(count)} مورد در {label} فعال است."

    handler.__name__ = f"{'add' if add else 'remove'}_{field}"
    return handler


_TOGGLES = (
    ("anti_spam_enabled", "ضداسپم"),
    ("anti_link_enabled", "ضدلینک"),
    ("anti_forward_enabled", "ضدفوروارد"),
)

for _field, _label in _TOGGLES:
    _name = _field.replace("_enabled", "")
    register_tool(
        name=f"settings.enable_{_name}",
        description=f"فعال‌کردن {_label}.",
        input_schema=EmptyParams,
        permission=SETTINGS_WRITE,
        risk_level=MEDIUM,
        requires_confirmation=False,
        handler=_toggle_tool(_field, True, _label, on=True),
        human_verb=f"فعال‌کردن {_label}",
    )
    register_tool(
        name=f"settings.disable_{_name}",
        description=f"غیرفعال‌کردن {_label}.",
        input_schema=EmptyParams,
        permission=SETTINGS_WRITE,
        # Disabling a security feature is treated as higher risk than enabling.
        risk_level=MEDIUM,
        requires_confirmation=True,
        handler=_toggle_tool(_field, False, _label, on=False),
        human_verb=f"غیرفعال‌کردن {_label}",
    )

register_tool(
    name="settings.set_flood_limit",
    description="تنظیم سقف تعداد پیام برای ضداسپم.",
    input_schema=IntValueParams,
    permission=SETTINGS_WRITE,
    risk_level=MEDIUM,
    # Free-text/numeric value is not reply-bound, so require an explicit
    # confirmation of the exact value (defends against injected/ambiguous input).
    requires_confirmation=True,
    handler=set_flood_limit,
    human_verb="تنظیم محدودیت پیام",
)
register_tool(
    name="settings.set_max_warnings",
    description="تنظیم حداکثر تعداد اخطار.",
    input_schema=IntValueParams,
    permission=SETTINGS_WRITE,
    risk_level=MEDIUM,
    requires_confirmation=True,
    handler=set_max_warnings,
    human_verb="تنظیم سقف اخطار",
)
register_tool(
    name="settings.get_blocked_words",
    description="نمایش کلمات ممنوع.",
    input_schema=EmptyParams,
    permission=SETTINGS_READ,
    risk_level=LOW,
    requires_confirmation=False,
    handler=_list_words_tool("blocked_words", "کلمات ممنوع"),
)
register_tool(
    name="settings.add_blocked_word",
    description="افزودن کلمه ممنوع.",
    input_schema=WordParams,
    permission=SETTINGS_WRITE,
    risk_level=MEDIUM,
    requires_confirmation=True,
    handler=_mutate_list_tool("blocked_words", "کلمات ممنوع", add=True),
    human_verb="افزودن کلمه ممنوع",
)
register_tool(
    name="settings.remove_blocked_word",
    description="حذف کلمه ممنوع.",
    input_schema=WordParams,
    permission=SETTINGS_WRITE,
    risk_level=MEDIUM,
    requires_confirmation=True,
    handler=_mutate_list_tool("blocked_words", "کلمات ممنوع", add=False),
    human_verb="حذف کلمه ممنوع",
)
register_tool(
    name="settings.get_allowed_domains",
    description="نمایش دامنه‌های مجاز.",
    input_schema=EmptyParams,
    permission=SETTINGS_READ,
    risk_level=LOW,
    requires_confirmation=False,
    handler=_list_words_tool("allowed_domains", "دامنه‌های مجاز"),
)
register_tool(
    name="settings.add_allowed_domain",
    description="افزودن دامنه مجاز.",
    input_schema=WordParams,
    permission=SETTINGS_WRITE,
    risk_level=MEDIUM,
    requires_confirmation=True,
    handler=_mutate_list_tool("allowed_domains", "دامنه‌های مجاز", add=True),
    human_verb="افزودن دامنه مجاز",
)
register_tool(
    name="settings.remove_allowed_domain",
    description="حذف دامنه مجاز.",
    input_schema=WordParams,
    permission=SETTINGS_WRITE,
    risk_level=MEDIUM,
    requires_confirmation=True,
    handler=_mutate_list_tool("allowed_domains", "دامنه‌های مجاز", add=False),
    human_verb="حذف دامنه مجاز",
)
