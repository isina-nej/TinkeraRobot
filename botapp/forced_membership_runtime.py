import hashlib
import logging
from html import escape

from aiogram import BaseMiddleware
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from botapp.forced_membership import (
    active_rules_for_source,
    evaluate_nonmember_message,
    legacy_membership_setting,
    mark_message_deleted,
    observe_membership,
    promote_legacy_membership_rule,
    rollback_initial_warning,
    save_tracked_invite,
    tracked_invite_url,
)

logger = logging.getLogger(__name__)
_MEMBER_STATUSES = {
    ChatMemberStatus.CREATOR,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.MEMBER,
}


def can_manage_rule(source_status, destination_status, is_super_admin: bool) -> bool:
    source = str(getattr(source_status, "value", source_status))
    destination = str(getattr(destination_status, "value", destination_status))
    return is_super_admin or source == "creator" or destination == "creator"


def join_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="عضویت الزامی", url=url)]]
    )


def _restricted_is_member(member) -> bool:
    return bool(getattr(member, "is_member", False))


async def _join_url(rule, user_id: int, bot) -> str:
    if rule.destination_username:
        return rule.destination_join_url or f"https://t.me/{rule.destination_username.lstrip('@')}"
    existing = await tracked_invite_url(rule.id, user_id)
    if existing:
        return existing
    invite = await bot.create_chat_invite_link(
        rule.destination_chat_id,
        name=f"fm:{rule.id}:{user_id}",
        member_limit=1,
    )
    return await save_tracked_invite(rule.id, user_id, invite)


async def _is_source_admin(message: Message, bot) -> bool:
    member = await bot.get_chat_member(message.chat.id, message.from_user.id)
    return member.status in {ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR}


async def _legacy_bot_permissions_valid(message: Message, destination_chat_id: int, bot) -> bool:
    source = await bot.get_chat_member(message.chat.id, bot.id)
    source_valid = source.status == ChatMemberStatus.CREATOR or (
        source.status == ChatMemberStatus.ADMINISTRATOR
        and bool(getattr(source, "can_delete_messages", False))
    )
    if not source_valid:
        return False
    destination = await bot.get_chat_member(destination_chat_id, bot.id)
    return destination.status in {
        ChatMemberStatus.CREATOR,
        ChatMemberStatus.ADMINISTRATOR,
    }


def _is_exempt_message(message: Message) -> bool:
    user = message.from_user
    return bool(
        not user
        or user.is_bot
        or (message.sender_chat is not None and message.sender_chat.id == message.chat.id)
        or message.new_chat_members
        or message.left_chat_member
        or message.pinned_message
    )


def _membership_event_message_id(message: Message) -> int:
    media_group_id = getattr(message, "media_group_id", None)
    if not media_group_id:
        return message.message_id
    identity = f"{message.chat.id}:{getattr(message.from_user, 'id', 0)}:{media_group_id}".encode()
    event_id = int.from_bytes(hashlib.sha256(identity).digest()[:8], "big") & ((1 << 63) - 1)
    return -(event_id or 1)


async def enforce_forced_membership_message(
    message: Message,
    bot,
    *,
    update_id: int | None = None,
) -> bool:
    if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP, "group", "supergroup"}:
        return False
    if _is_exempt_message(message):
        return False

    rules = await active_rules_for_source(message.chat.id)
    if not rules:
        legacy = await legacy_membership_setting(message.chat.id)
        if legacy:
            try:
                destination = await bot.get_chat(legacy[1])
                if not await _legacy_bot_permissions_valid(message, destination.id, bot):
                    logger.error("Legacy forced membership permissions invalid in %s", message.chat.id)
                    return True
                await promote_legacy_membership_rule(legacy[0], destination)
                rules = await active_rules_for_source(message.chat.id)
            except TelegramAPIError:
                logger.exception("Legacy forced membership destination could not be resolved")
                return True
    if not rules:
        return False

    try:
        if await _is_source_admin(message, bot):
            return False
    except TelegramAPIError:
        logger.exception("Forced membership source-admin check failed in %s", message.chat.id)
        return True

    for rule in rules:
        try:
            member = await bot.get_chat_member(rule.destination_chat_id, message.from_user.id)
        except TelegramAPIError:
            logger.exception("Forced membership check failed for rule %s", rule.id)
            return True

        membership = await observe_membership(
            rule.id,
            message.from_user,
            member.status,
            restricted_is_member=_restricted_is_member(member),
            update_id=None,
        )
        if membership.action == "allow":
            continue

        keyboard = join_keyboard(await _join_url(rule, message.from_user.id, bot))
        decision = await evaluate_nonmember_message(
            rule.id,
            message.from_user,
            _membership_event_message_id(message),
            update_id,
        )
        if decision.action == "ignore":
            if getattr(message, "media_group_id", None):
                try:
                    await bot.delete_message(message.chat.id, message.message_id)
                except TelegramAPIError:
                    logger.exception("Forced membership album delete failed for message %s", message.message_id)
                else:
                    await mark_message_deleted(decision.state_id, rule.id, message.message_id, update_id)
            return True

        mention = (
            f'<a href="tg://user?id={message.from_user.id}">'
            f'{escape(message.from_user.first_name or "کاربر")}</a>'
        )
        if decision.action == "warn":
            deleted = False
            if getattr(message, "media_group_id", None):
                try:
                    await bot.delete_message(message.chat.id, message.message_id)
                except TelegramAPIError:
                    logger.exception("Forced membership album delete failed for message %s", message.message_id)
                else:
                    deleted = True
            send_kwargs = {
                "chat_id": message.chat.id,
                "text": (
                    "⚠️ برای ارسال پیام در این گروه، ابتدا باید در مقصد زیر عضو شوید.\n"
                    "در صورت عضو نشدن، پیام‌های بعدی شما حذف خواهند شد."
                ),
                "reply_markup": keyboard,
            }
            if not getattr(message, "media_group_id", None):
                send_kwargs["reply_to_message_id"] = message.message_id
            try:
                await bot.send_message(**send_kwargs)
            except TelegramAPIError:
                await rollback_initial_warning(
                    decision.state_id,
                    rule.id,
                    _membership_event_message_id(message),
                    update_id,
                )
                logger.exception("Forced membership warning failed for message %s", message.message_id)
            else:
                if deleted:
                    await mark_message_deleted(decision.state_id, rule.id, message.message_id, update_id)
            return True

        try:
            await bot.delete_message(message.chat.id, message.message_id)
        except TelegramAPIError:
            logger.exception("Forced membership delete failed for message %s", message.message_id)
            return True
        await mark_message_deleted(decision.state_id, rule.id, message.message_id, update_id)
        try:
            await bot.send_message(
                chat_id=message.chat.id,
                text=(
                    f"⚠️ {mention} عزیز، برای ارسال پیام باید ابتدا عضو مقصد شوید.\n"
                    "تا زمان عضویت، پیام‌های شما حذف می‌شوند."
                ),
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        except TelegramAPIError:
            logger.exception("Forced membership deletion notice failed for message %s", message.message_id)
        return True
    return False


class ForcedMembershipMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, Message):
            try:
                blocked = await enforce_forced_membership_message(
                    event,
                    data["bot"],
                    update_id=getattr(data.get("event_update"), "update_id", None),
                )
            except Exception:
                logger.exception("Forced membership middleware failed")
                return None
            if blocked:
                return None
        return await handler(event, data)
