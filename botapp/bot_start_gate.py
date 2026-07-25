import asyncio
import base64
import hashlib
import hmac
import logging
import struct
from dataclasses import dataclass
from datetime import timedelta
from html import escape

from aiogram import BaseMiddleware
from aiogram.enums import ChatMemberStatus, ChatType, ContentType
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from botapp.models import BotStartGateEvent, GroupSettings, GroupUserGateState, TelegramUser

logger = logging.getLogger(__name__)
_TELEGRAM_CALL_ERRORS = (TelegramAPIError, OSError)
_ADMIN_STATUSES = {ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR, "creator", "administrator"}
OFFICIAL_BOT_USERNAME = "NuyaRobot"
NOTICE_TTL = timedelta(minutes=3)
DEEP_LINK_TTL = timedelta(minutes=15)
_DEEP_LINK_PREFIX = "gate_"
_DEEP_LINK_STRUCT = struct.Struct(">qQ")
_DEEP_LINK_EXPIRY_STRUCT = struct.Struct(">I")
_DEEP_LINK_TAG_BYTES = 10
WELCOME_TEXT = """به ربات تینکرا خوش اومدی. 🚀

اگر مشکلی مشاهده کردی یا پیشنهادی برای بهتر شدن ربات داشتی، خوشحال می‌شیم با ما در میون بذاری. بازخوردهای شما مستقیماً در بهبود نسخه‌های بعدی تأثیر داره.
ارتباط با ما: @TinkeraSupport

از اینکه در این مرحله کنار ما هستی و به بهتر شدن ربات کمک می‌کنی، ممنونیم. ❤️"""


@dataclass(frozen=True, slots=True)
class BotStartDecision:
    action: str
    state_id: int | None = None
    event_id: int | None = None
    blocked: bool = False


def _deep_link_key() -> bytes:
    return hashlib.sha256(f"bot-start-gate:{settings.SECRET_KEY}".encode()).digest()


def deep_link_payload(group_id: int, user_id: int, *, expires_at: int | None = None) -> str:
    expiry = expires_at or int((timezone.now() + DEEP_LINK_TTL).timestamp())
    body = _DEEP_LINK_STRUCT.pack(int(group_id), int(user_id)) + _DEEP_LINK_EXPIRY_STRUCT.pack(expiry)
    tag = hmac.digest(_deep_link_key(), body, "sha256")[:_DEEP_LINK_TAG_BYTES]
    encoded = base64.urlsafe_b64encode(body + tag).rstrip(b"=").decode()
    return f"{_DEEP_LINK_PREFIX}{encoded}"


def parse_deep_link_payload(payload: str, *, current_user_id: int) -> int | None:
    if not payload.startswith(_DEEP_LINK_PREFIX):
        return None
    encoded = payload[len(_DEEP_LINK_PREFIX):]
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        body, supplied_tag = raw[:-_DEEP_LINK_TAG_BYTES], raw[-_DEEP_LINK_TAG_BYTES:]
        expected_tag = hmac.digest(_deep_link_key(), body, "sha256")[:_DEEP_LINK_TAG_BYTES]
        if not hmac.compare_digest(supplied_tag, expected_tag):
            return None
        identity, expiry_bytes = body[:_DEEP_LINK_STRUCT.size], body[_DEEP_LINK_STRUCT.size:]
        group_id, token_user_id = _DEEP_LINK_STRUCT.unpack(identity)
        expires_at = _DEEP_LINK_EXPIRY_STRUCT.unpack(expiry_bytes)[0]
    except (ValueError, TypeError, struct.error):
        return None
    if token_user_id != int(current_user_id) or expires_at < int(timezone.now().timestamp()):
        return None
    return group_id


def start_keyboard(
    bot_username: str,
    group_id: int,
    user_id: int,
    *,
    blocked: bool = False,
) -> InlineKeyboardMarkup:
    label = "🚀 باز کردن ربات" if blocked else "🚀 استارت"
    username = (bot_username or OFFICIAL_BOT_USERNAME).lstrip("@")
    url = f"https://t.me/{username}?start={deep_link_payload(group_id, user_id)}"
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label, url=url)]])


def _gate_event_message_id(message: Message) -> int:
    media_group_id = getattr(message, "media_group_id", None)
    if not media_group_id:
        return message.message_id
    identity = f"{message.chat.id}:{getattr(message.from_user, 'id', 0)}:{media_group_id}".encode()
    event_id = int.from_bytes(hashlib.sha256(identity).digest()[:8], "big") & ((1 << 63) - 1)
    return -(event_id or 1)


def _service_or_exempt(message: Message) -> bool:
    user = message.from_user
    user_content_types = {
        ContentType.TEXT,
        ContentType.ANIMATION,
        ContentType.AUDIO,
        ContentType.DOCUMENT,
        ContentType.PAID_MEDIA,
        ContentType.PHOTO,
        ContentType.STICKER,
        ContentType.STORY,
        ContentType.VIDEO,
        ContentType.VIDEO_NOTE,
        ContentType.VOICE,
        ContentType.CHECKLIST,
        ContentType.CONTACT,
        ContentType.DICE,
        ContentType.GAME,
        ContentType.POLL,
        ContentType.VENUE,
        ContentType.LOCATION,
    }
    return bool(
        not user
        or user.is_bot
        or (
            getattr(message, "content_type", None) is not None
            and message.content_type not in user_content_types
        )
        or message.sender_chat is not None
        or message.new_chat_members
        or message.left_chat_member
        or message.pinned_message
    )


@sync_to_async(thread_sensitive=True)
def _load_gate_context(chat_id: int, user_id: int):
    group, _ = GroupSettings.objects.get_or_create(chat_id=chat_id)
    user, _ = TelegramUser.objects.get_or_create(telegram_user_id=user_id)
    return group, user.started, user.blocked


@sync_to_async(thread_sensitive=True)
def _touch_user(user_id: int, *, started=None, blocked=None):
    user, _ = TelegramUser.objects.get_or_create(telegram_user_id=user_id)
    if started is not None:
        user.started = started
    if blocked is not None:
        user.blocked = blocked
    user.last_live_check_at = timezone.now()
    fields = ["last_live_check_at"]
    if started is not None:
        fields.append("started")
    if blocked is not None:
        fields.append("blocked")
    user.save(update_fields=fields)
    return user


@sync_to_async(thread_sensitive=True)
def _prepare_decision(
    group_id: int,
    user_id: int,
    *,
    message_id: int,
    telegram_update_id: int | None,
    blocked: bool,
) -> BotStartDecision:
    now = timezone.now()
    with transaction.atomic():
        state, _ = GroupUserGateState.objects.select_for_update().get_or_create(
            group_id=group_id,
            telegram_user_id=user_id,
        )
        event = BotStartGateEvent.objects.filter(
            group_id=group_id,
            message_id=message_id,
        ).first()
        if (
            event
            and event.status == "pending"
            and event.updated_at < now - timedelta(seconds=30)
        ):
            event.status = "failed"
            event.save(update_fields=["status", "updated_at"])
        if event and event.status != "failed":
            return BotStartDecision(action="duplicate", state_id=state.id, event_id=event.id, blocked=blocked)
        if event:
            event.status = "pending"
            event.telegram_update_id = telegram_update_id
            event.save(update_fields=["status", "telegram_update_id", "updated_at"])
        else:
            event = BotStartGateEvent.objects.create(
                group_id=group_id,
                telegram_user_id=user_id,
                message_id=message_id,
                telegram_update_id=telegram_update_id,
                action="",
            )
        state.last_check_at = now
        if state.first_message_at is None:
            state.first_message_at = now
        if (
            state.warning_pending_at is not None
            and state.warning_pending_at >= now - timedelta(seconds=30)
        ):
            action = "hold"
        else:
            state.warning_pending_at = None
            action = "warn" if state.warning_sent_at is None else "delete"
        if action == "warn":
            state.warning_pending_at = now
        event.action = action
        event.save(update_fields=["action", "updated_at"])
        state.save(update_fields=[
            "first_message_at",
            "warning_pending_at",
            "warning_sent_at",
            "last_check_at",
            "updated_at",
        ])
        return BotStartDecision(
            action=action,
            state_id=state.id,
            event_id=event.id,
            blocked=blocked,
        )


@sync_to_async(thread_sensitive=True)
def _warning_failed(event_id: int):
    with transaction.atomic():
        event = BotStartGateEvent.objects.select_for_update().get(pk=event_id)
        state = GroupUserGateState.objects.select_for_update().get(
            group=event.group,
            telegram_user_id=event.telegram_user_id,
        )
        event.status = "failed"
        event.save(update_fields=["status", "updated_at"])
        BotStartGateEvent.objects.filter(
            group=event.group,
            telegram_user_id=event.telegram_user_id,
            action="hold",
            status="pending",
        ).update(status="failed", updated_at=timezone.now())
        state.warning_pending_at = None
        state.save(update_fields=["warning_pending_at", "updated_at"])


@sync_to_async(thread_sensitive=True)
def _event_failed(event_id: int):
    BotStartGateEvent.objects.filter(pk=event_id).update(
        status="failed",
        updated_at=timezone.now(),
    )


@sync_to_async(thread_sensitive=True)
def _warning_completed(event_id: int):
    with transaction.atomic():
        event = BotStartGateEvent.objects.select_for_update().get(pk=event_id)
        state = GroupUserGateState.objects.select_for_update().get(
            group=event.group,
            telegram_user_id=event.telegram_user_id,
        )
        now = timezone.now()
        event.status = "completed"
        event.save(update_fields=["status", "updated_at"])
        BotStartGateEvent.objects.filter(
            group=event.group,
            telegram_user_id=event.telegram_user_id,
            action="hold",
            status="pending",
        ).update(status="failed", updated_at=now)
        state.warning_pending_at = None
        state.warning_sent_at = now
        state.save(update_fields=["warning_pending_at", "warning_sent_at", "updated_at"])


@sync_to_async(thread_sensitive=True)
def _mark_deleted(state_id: int, event_id: int):
    with transaction.atomic():
        state = GroupUserGateState.objects.select_for_update().get(pk=state_id)
        event = BotStartGateEvent.objects.select_for_update().get(pk=event_id)
        state.message_deleted_count += 1
        state.save(update_fields=["message_deleted_count", "updated_at"])
        event.status = "completed"
        event.save(update_fields=["status", "updated_at"])


@sync_to_async(thread_sensitive=True)
def _reserve_notice(state_id: int):
    now = timezone.now()
    with transaction.atomic():
        state = GroupUserGateState.objects.select_for_update().get(pk=state_id)
        if state.last_warning_update_at and state.last_warning_update_at > now - NOTICE_TTL:
            return None
        previous_message_id = state.warning_message_id
        state.last_warning_update_at = now
        state.save(update_fields=["last_warning_update_at", "updated_at"])
        return now, previous_message_id


@sync_to_async(thread_sensitive=True)
def _record_notice(state_id: int, reserved_at, message_id: int):
    GroupUserGateState.objects.filter(
        pk=state_id,
        last_warning_update_at=reserved_at,
    ).update(
        warning_message_id=message_id,
        notice_delete_at=reserved_at + NOTICE_TTL,
        updated_at=timezone.now(),
    )


@sync_to_async(thread_sensitive=True)
def _release_notice(state_id: int, reserved_at):
    GroupUserGateState.objects.filter(
        pk=state_id,
        last_warning_update_at=reserved_at,
    ).update(last_warning_update_at=None, updated_at=timezone.now())


@sync_to_async(thread_sensitive=True)
def _due_notices(limit: int = 100):
    return list(
        GroupUserGateState.objects.filter(
            warning_message_id__isnull=False,
            notice_delete_at__lte=timezone.now(),
        ).values_list("id", "group__chat_id", "warning_message_id")[:limit]
    )


@sync_to_async(thread_sensitive=True)
def clear_notice_record(state_id: int, message_id: int):
    GroupUserGateState.objects.filter(
        pk=state_id,
        warning_message_id=message_id,
    ).update(warning_message_id=None, notice_delete_at=None, updated_at=timezone.now())


async def cleanup_due_notices(bot, *, limit: int = 100) -> int:
    cleaned = 0
    for state_id, chat_id, message_id in await _due_notices(limit):
        try:
            await bot.delete_message(chat_id, message_id)
        except TelegramBadRequest:
            pass
        except _TELEGRAM_CALL_ERRORS:
            logger.exception("Bot-start notice cleanup failed for message %s", message_id)
            continue
        await clear_notice_record(state_id, message_id)
        cleaned += 1
    return cleaned


async def notice_cleanup_loop(bot):
    while True:
        await cleanup_due_notices(bot)
        await asyncio.sleep(1)


async def _bot_can_enforce(message: Message, bot) -> bool:
    member = await bot.get_chat_member(message.chat.id, bot.id)
    return member.status == ChatMemberStatus.CREATOR or (
        member.status == ChatMemberStatus.ADMINISTRATOR
        and bool(getattr(member, "can_delete_messages", False))
        and getattr(member, "can_send_messages", True) is not False
    )


async def _user_is_admin(message: Message, bot) -> bool:
    member = await bot.get_chat_member(message.chat.id, message.from_user.id)
    return member.status in _ADMIN_STATUSES


async def enforce_bot_start_message(
    message: Message,
    bot,
    *,
    bot_username: str,
    telegram_update_id: int | None = None,
) -> bool:
    if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP, "group", "supergroup"}:
        return False
    if _service_or_exempt(message):
        return False

    group, started, blocked = await _load_gate_context(message.chat.id, message.from_user.id)
    if not group.bot_start_required:
        return False
    try:
        if not await _bot_can_enforce(message, bot):
            return False
        if await _user_is_admin(message, bot):
            return False
    except _TELEGRAM_CALL_ERRORS:
        logger.warning("Bot-start permission check temporarily failed in %s", message.chat.id)
        return False

    if started:
        try:
            await bot.send_chat_action(chat_id=message.from_user.id, action="typing")
        except TelegramForbiddenError:
            started = False
            blocked = True
            await _touch_user(message.from_user.id, started=False, blocked=True)
        except _TELEGRAM_CALL_ERRORS:
            logger.warning("Bot-start private status check temporarily failed for %s", message.from_user.id)
            return False
        else:
            await _touch_user(message.from_user.id, blocked=False)
            return False

    decision = await _prepare_decision(
        group.id,
        message.from_user.id,
        message_id=_gate_event_message_id(message),
        telegram_update_id=telegram_update_id,
        blocked=blocked,
    )
    if decision.action == "duplicate":
        if getattr(message, "media_group_id", None):
            try:
                await bot.delete_message(message.chat.id, message.message_id)
            except _TELEGRAM_CALL_ERRORS:
                pass
        return True
    if decision.action == "hold":
        try:
            await bot.delete_message(message.chat.id, message.message_id)
        except _TELEGRAM_CALL_ERRORS:
            await _event_failed(decision.event_id)
        else:
            await _mark_deleted(decision.state_id, decision.event_id)
        return True
    name = escape(message.from_user.first_name or "کاربر")
    mention = f'<a href="tg://user?id={message.from_user.id}">{name}</a>'
    keyboard = start_keyboard(
        bot_username,
        message.chat.id,
        message.from_user.id,
        blocked=decision.blocked,
    )
    if decision.action == "warn":
        if decision.blocked:
            text = (
                f"• کاربر {mention}\n\n"
                "• شما ارتباط با Nuya را مسدود کرده‌اید.\n\n"
                "• برای ارسال پیام ابتدا ربات را از حالت Block خارج کرده و دوباره Start کنید."
            )
        else:
            text = (
                f"• کاربر {mention}\n\n"
                "• برای ارسال پیام باید در Nuya عضو شوید.\n\n"
                "• لطفاً با استفاده از دکمه زیر ربات را استارت کنید!\n"
                "در غیر این صورت پیام بعدی شما نیز پاک می‌شود."
            )
        reservation = await _reserve_notice(decision.state_id)
        if reservation is None:
            await _warning_completed(decision.event_id)
            return True
        reserved_at, previous_message_id = reservation
        deleted = False
        try:
            await bot.delete_message(message.chat.id, message.message_id)
        except _TELEGRAM_CALL_ERRORS:
            pass
        else:
            deleted = True
        try:
            notice = await bot.send_message(
                chat_id=message.chat.id,
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        except _TELEGRAM_CALL_ERRORS:
            await _release_notice(decision.state_id, reserved_at)
            await _warning_failed(decision.event_id)
            logger.exception("Bot-start first warning failed for message %s", message.message_id)
        else:
            warning_message_id = getattr(notice, "message_id", None)
            if isinstance(warning_message_id, int):
                await _record_notice(decision.state_id, reserved_at, warning_message_id)
            if previous_message_id:
                try:
                    await bot.delete_message(message.chat.id, previous_message_id)
                except _TELEGRAM_CALL_ERRORS:
                    pass
            await _warning_completed(decision.event_id)
            if deleted:
                await _mark_deleted(decision.state_id, decision.event_id)
        return True

    try:
        await bot.delete_message(message.chat.id, message.message_id)
    except _TELEGRAM_CALL_ERRORS:
        await _event_failed(decision.event_id)
        logger.exception("Bot-start delete failed for message %s", message.message_id)
        return True
    await _mark_deleted(decision.state_id, decision.event_id)
    if decision.blocked:
        text = (
            f"• کاربر {mention}\n\n"
            "• پیام ارسالی شما پاک شد.\n\n"
            "• شما باید ابتدا Nuya را فعال کنید تا بتوانید در گروه پیام ارسال کنید."
        )
    else:
        text = (
            f"• کاربر {mention}\n\n"
            "• پیام ارسالی شما پاک شد.\n\n"
            "• برای ارسال پیام باید در Nuya عضو شوید.\n\n"
            "• لطفاً با استفاده از دکمه زیر ربات را استارت کنید!"
        )
    reservation = await _reserve_notice(decision.state_id)
    if reservation is None:
        return True
    reserved_at, previous_message_id = reservation
    try:
        notice = await bot.send_message(
            chat_id=message.chat.id,
            text=text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    except _TELEGRAM_CALL_ERRORS:
        await _release_notice(decision.state_id, reserved_at)
        logger.exception("Bot-start deletion notice failed for message %s", message.message_id)
    else:
        warning_message_id = getattr(notice, "message_id", None)
        if isinstance(warning_message_id, int):
            await _record_notice(decision.state_id, reserved_at, warning_message_id)
        if previous_message_id:
            try:
                await bot.delete_message(message.chat.id, previous_message_id)
            except _TELEGRAM_CALL_ERRORS:
                pass
    return True


@sync_to_async(thread_sensitive=True)
def mark_user_started(user_id: int):
    with transaction.atomic():
        user, _ = TelegramUser.objects.select_for_update().get_or_create(telegram_user_id=user_id)
        now = timezone.now()
        user.started = True
        user.blocked = False
        user.last_live_check_at = now
        user.save(update_fields=[
            "started",
            "blocked",
            "last_live_check_at",
        ])
        notice_targets = list(
            GroupUserGateState.objects.filter(
                telegram_user_id=user_id,
                warning_message_id__isnull=False,
            ).values_list("id", "group__chat_id", "warning_message_id")
        )
        GroupUserGateState.objects.filter(telegram_user_id=user_id).update(
            warning_pending_at=None,
            warning_sent_at=None,
            last_warning_update_at=None,
            updated_at=now,
        )
        BotStartGateEvent.objects.filter(
            telegram_user_id=user_id,
            status="pending",
        ).update(status="completed", updated_at=now)
        return user, notice_targets


class BotStartGateService:
    def __init__(self, bot_username: str):
        self.bot_username = bot_username

    async def check_user_access(self, message: Message, bot, *, telegram_update_id=None) -> bool:
        return await enforce_bot_start_message(
            message,
            bot,
            bot_username=self.bot_username,
            telegram_update_id=telegram_update_id,
        )

    async def mark_started(self, user_id: int):
        return await mark_user_started(user_id)

    async def mark_blocked(self, user_id: int):
        return await _touch_user(user_id, started=False, blocked=True)

    async def clear_warning(self, bot, state_id: int, chat_id: int, message_id: int) -> None:
        try:
            await bot.delete_message(chat_id, message_id)
        except _TELEGRAM_CALL_ERRORS:
            return
        await clear_notice_record(state_id, message_id)

    async def validate_group_permission(self, message: Message, bot) -> bool:
        return await _bot_can_enforce(message, bot)


class BotStartGateMiddleware(BaseMiddleware):
    def __init__(self, bot_username: str):
        self.service = BotStartGateService(bot_username)

    async def __call__(self, handler, event, data):
        if isinstance(event, Message):
            if event.chat.type == ChatType.PRIVATE and event.from_user:
                _, notice_targets = await self.service.mark_started(event.from_user.id)
                for state_id, chat_id, message_id in notice_targets:
                    await self.service.clear_warning(data["bot"], state_id, chat_id, message_id)
            update = data.get("event_update")
            blocked = await self.service.check_user_access(
                event,
                data["bot"],
                telegram_update_id=getattr(update, "update_id", None),
            )
            if blocked:
                return None
        return await handler(event, data)
