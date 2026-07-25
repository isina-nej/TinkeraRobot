from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from asgiref.sync import sync_to_async

from botapp.models import GroupSettings, ModerationAction
from botapp.moderation import (
    complete_action,
    create_action,
    render_group_message,
)
from botapp.telegram_gateway import execute_telegram_action, is_chat_admin


@sync_to_async(thread_sensitive=True)
def create_telegram_action(**kwargs):
    return create_action(source="telegram", **kwargs)


async def queue_or_execute(
    *,
    bot,
    group: GroupSettings,
    action,
    target=None,
    actor=None,
    reason="",
    delay_minutes=0,
    duration_minutes=None,
):
    if target and action in {"mute", "ban"}:
        if target.is_bot or target.id == bot.id or await is_chat_admin(bot, group.chat_id, target.id):
            return None, render_group_message(group, "admin_protected", target=target.full_name)

    moderation_action, _ = await create_telegram_action(
        group=group,
        action=action,
        target_user_id=target.id if target else None,
        target_name=target.full_name if target else "",
        actor_user_id=actor.id if actor else None,
        actor_name=actor.full_name if actor else "",
        reason=reason,
        delay_minutes=delay_minutes,
        duration_minutes=duration_minutes,
    )
    if delay_minutes:
        return moderation_action, render_group_message(
            group,
            "scheduled",
            action=action,
            execute_at=moderation_action.execute_at.isoformat(),
        )
    try:
        await execute_telegram_action(bot, moderation_action)
    except (TelegramBadRequest, TelegramForbiddenError) as exc:
        moderation_action.status = "failed"
        moderation_action.error = str(exc)
        await sync_to_async(moderation_action.save)(update_fields=["status", "error"])
        raise
    moderation_action, _ = await sync_to_async(complete_action)(moderation_action)
    return moderation_action, render_group_message(
        group,
        action,
        target=target.full_name if target else "",
    )
