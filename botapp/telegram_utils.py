from asgiref.sync import sync_to_async
from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
import os

from .models import GroupSettings

ADMIN_IDS = frozenset(
    int(value.strip())
    for value in os.getenv("ADMIN_IDS", "").split(",")
    if value.strip()
)

@sync_to_async
def aget_group_settings(chat_id: int):
    try:
        return GroupSettings.objects.get(chat_id=chat_id)
    except GroupSettings.DoesNotExist:
        return None

@sync_to_async
def aget_super_admin_ids():
    return ADMIN_IDS

async def user_is_admin_in_group(chat, user_id):
    if user_id in ADMIN_IDS:
        return True
    
    settings = await aget_group_settings(chat.id)
    if settings and user_id in settings.group_admins:
        return True

    try:
        member = await Bot.get_current().get_chat_member(chat.id, user_id)
        return member.status in {ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR}
    except TelegramAPIError:
        return False
