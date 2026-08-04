"""Shared helpers for agent tools."""

from __future__ import annotations

from types import SimpleNamespace

from asgiref.sync import sync_to_async

from botapp.agent.context import AgentContext


def actor_from_context(ctx: AgentContext):
    return SimpleNamespace(
        id=ctx.admin.user_id,
        full_name=ctx.admin.display_name,
        username="",
        is_bot=False,
    )


def target_namespace(user_id: int, full_name: str = "", *, is_bot: bool = False):
    return SimpleNamespace(
        id=int(user_id),
        full_name=full_name or str(user_id),
        username="",
        is_bot=is_bot,
    )


@sync_to_async(thread_sensitive=True)
def refresh_group_settings(chat_id: int):
    from botapp.models import GroupSettings

    group, _ = GroupSettings.objects.get_or_create(chat_id=chat_id)
    return group


@sync_to_async(thread_sensitive=True)
def save_group_field(chat_id: int, field: str, value) -> None:
    from botapp.models import GroupSettings

    group, _ = GroupSettings.objects.get_or_create(chat_id=chat_id)
    setattr(group, field, value)
    group.save(update_fields=[field, "updated_at"])
