from aiogram.enums import ChatMemberStatus
from aiogram.types import ChatPermissions
from asgiref.sync import sync_to_async

from botapp.models import ModerationAction

MUTED_PERMISSIONS = ChatPermissions(can_send_messages=False)
OPEN_PERMISSIONS = ChatPermissions(
    can_send_messages=True,
    can_send_audios=True,
    can_send_documents=True,
    can_send_photos=True,
    can_send_videos=True,
    can_send_video_notes=True,
    can_send_voice_notes=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
    can_invite_users=True,
)
LOCKED_GROUP_PERMISSIONS = ChatPermissions(
    can_send_messages=False,
    can_send_audios=False,
    can_send_documents=False,
    can_send_photos=False,
    can_send_videos=False,
    can_send_video_notes=False,
    can_send_voice_notes=False,
    can_send_polls=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
)


@sync_to_async(thread_sensitive=True)
def save_open_permissions(group, permissions):
    group.open_permissions_snapshot = permissions.model_dump(exclude_none=True)
    group.save(update_fields=["open_permissions_snapshot", "updated_at"])


async def is_chat_admin(bot, chat_id, user_id):
    member = await bot.get_chat_member(chat_id, user_id)
    return member.status in {ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR}


async def execute_telegram_action(bot, action: ModerationAction):
    if action.action == "lock":
        chat = await bot.get_chat(action.group.chat_id)
        current = chat.permissions or OPEN_PERMISSIONS
        # Only snapshot the pre-lock permissions when the group is currently
        # OPEN. Locking an already-locked group (e.g. a second /lock or a daily
        # lock while already locked) must not overwrite the good snapshot with
        # the locked state — otherwise unlock would restore the locked
        # permissions and mute the group permanently.
        if getattr(current, "can_send_messages", None) is not False:
            await save_open_permissions(action.group, current)
        return await bot.set_chat_permissions(action.group.chat_id, LOCKED_GROUP_PERMISSIONS)
    if action.action == "unlock":
        permissions = (
            ChatPermissions(**action.group.open_permissions_snapshot)
            if action.group.open_permissions_snapshot
            else OPEN_PERMISSIONS
        )
        return await bot.set_chat_permissions(action.group.chat_id, permissions)
    if action.action == "mute":
        return await bot.restrict_chat_member(
            action.group.chat_id,
            action.target_user_id,
            MUTED_PERMISSIONS,
        )
    if action.action == "unmute":
        return await bot.restrict_chat_member(
            action.group.chat_id,
            action.target_user_id,
            OPEN_PERMISSIONS,
        )
    if action.action == "ban":
        return await bot.ban_chat_member(action.group.chat_id, action.target_user_id)
    if action.action == "unban":
        return await bot.unban_chat_member(
            action.group.chat_id,
            action.target_user_id,
            only_if_banned=True,
        )
    raise ValueError(f"unsupported Telegram action: {action.action}")
