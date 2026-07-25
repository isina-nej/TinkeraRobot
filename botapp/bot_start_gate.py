import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta
from html import escape

from aiogram import BaseMiddleware
from aiogram.enums import ChatMemberStatus, ChatType, ContentType
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone

from botapp.models import BotStartGateEvent, BotStartUserState, GroupSettings, TelegramUser

logger = logging.getLogger(__name__)
_ADMIN_STATUSES = {ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR, "creator", "administrator"}
OFFICIAL_BOT_USERNAME = "NuyaRobot"
NOTICE_TTL = timedelta(minutes=3)
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


def deep_link_payload(group_id: int) -> str:
    return f"g_{abs(int(group_id))}"


def start_keyboard(bot_username: str, group_id: int, *, blocked: bool = False) -> InlineKeyboardMarkup:
    label = "🚀 باز کردن ربات" if blocked else "🚀 استارت"
    url = f"https://t.me/{OFFICIAL_BOT_USERNAME}?start={deep_link_payload(group_id)}"
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label, url=url)]])


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
        or (
            message.sender_chat
            and message.sender_chat.id == message.chat.id
        )
        or message.new_chat_members
        or message.left_chat_member
        or message.pinned_message
    )


@sync_to_async(thread_sensitive=True)
def _load_gate_context(chat_id: int, user_id: int):
    group, _ = GroupSettings.objects.get_or_create(chat_id=chat_id)
    user, _ = TelegramUser.objects.get_or_create(user_id=user_id)
    return group, user.started, user.blocked


@sync_to_async(thread_sensitive=True)
def _touch_user(user_id: int, *, started=None, blocked=None):
    user, _ = TelegramUser.objects.get_or_create(user_id=user_id)
    if started is not None:
        user.started = started
    if blocked is not None:
        user.blocked = blocked
    user.last_check_at = timezone.now()
    fields = ["last_check_at"]
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
        GroupSettings.objects.select_for_update().get(pk=group_id)
        state, _ = BotStartUserState.objects.select_for_update().get_or_create(
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
        state = BotStartUserState.objects.select_for_update().get(
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
def _warning_completed(event_id: int):
    with transaction.atomic():
        event = BotStartGateEvent.objects.select_for_update().get(pk=event_id)
        state = BotStartUserState.objects.select_for_update().get(
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
        state = BotStartUserState.objects.select_for_update().get(pk=state_id)
        event = BotStartGateEvent.objects.select_for_update().get(pk=event_id)
        state.message_deleted_count += 1
        state.save(update_fields=["message_deleted_count", "updated_at"])
        event.status = "completed"
        event.save(update_fields=["status", "updated_at"])


@sync_to_async(thread_sensitive=True)
def _reserve_notice(state_id: int):
    now = timezone.now()
    with transaction.atomic():
        state = BotStartUserState.objects.select_for_update().get(pk=state_id)
        if state.last_notice_at and state.last_notice_at > now - NOTICE_TTL:
            return None
        previous_message_id = state.notice_message_id
        state.last_notice_at = now
        state.notice_message_id = None
        state.notice_delete_at = now + NOTICE_TTL
        state.save(update_fields=[
            "last_notice_at",
            "notice_message_id",
            "notice_delete_at",
            "updated_at",
        ])
        return now, previous_message_id


@sync_to_async(thread_sensitive=True)
def _record_notice(state_id: int, reserved_at, message_id: int):
    BotStartUserState.objects.filter(
        pk=state_id,
        last_notice_at=reserved_at,
    ).update(notice_message_id=message_id, updated_at=timezone.now())


@sync_to_async(thread_sensitive=True)
def _release_notice(state_id: int, reserved_at):
    BotStartUserState.objects.filter(
        pk=state_id,
        last_notice_at=reserved_at,
        notice_message_id__isnull=True,
    ).update(last_notice_at=None, notice_delete_at=None, updated_at=timezone.now())


@sync_to_async(thread_sensitive=True)
def _due_notices(limit: int = 100):
    return list(
        BotStartUserState.objects.filter(
            notice_message_id__isnull=False,
            notice_delete_at__lte=timezone.now(),
        ).values_list("id", "group__chat_id", "notice_message_id")[:limit]
    )


@sync_to_async(thread_sensitive=True)
def _clear_notice(state_id: int, message_id: int):
    BotStartUserState.objects.filter(
        pk=state_id,
        notice_message_id=message_id,
    ).update(notice_message_id=None, notice_delete_at=None, updated_at=timezone.now())


async def cleanup_due_notices(bot, *, limit: int = 100) -> int:
    cleaned = 0
    for state_id, chat_id, message_id in await _due_notices(limit):
        try:
            await bot.delete_message(chat_id, message_id)
        except TelegramBadRequest:
            pass
        except TelegramAPIError:
            logger.exception("Bot-start notice cleanup failed for message %s", message_id)
            continue
        await _clear_notice(state_id, message_id)
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
    )


async def _user_is_admin(message: Message, bot) -> bool:
    member = await bot.get_chat_member(message.chat.id, message.from_user.id)
    return member.status in _ADMIN_STATUSES


@sync_to_async(thread_sensitive=True)
def _warning_is_pending(group_id: int, user_id: int) -> bool:
    return BotStartUserState.objects.filter(
        group_id=group_id,
        telegram_user_id=user_id,
        warning_pending_at__isnull=False,
    ).exists()


async def _wait_for_warning(group_id: int, user_id: int) -> bool:
    for _ in range(300):
        if not await _warning_is_pending(group_id, user_id):
            return True
        await asyncio.sleep(0.1)
    return False


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
    except TelegramAPIError:
        logger.exception("Bot-start permission check failed in %s", message.chat.id)
        return True

    if started:
        try:
            await bot.send_chat_action(chat_id=message.from_user.id, action="typing")
        except TelegramForbiddenError:
            started = False
            blocked = True
            await _touch_user(message.from_user.id, started=False, blocked=True)
        except TelegramAPIError:
            logger.exception("Bot-start private status check failed for %s", message.from_user.id)
            return True
        else:
            await _touch_user(message.from_user.id, blocked=False)
            return False

    decision = await _prepare_decision(
        group.id,
        message.from_user.id,
        message_id=message.message_id,
        telegram_update_id=telegram_update_id,
        blocked=blocked,
    )
    if decision.action == "duplicate":
        return True
    if decision.action == "hold":
        if not await _wait_for_warning(group.id, message.from_user.id):
            return True
        decision = await _prepare_decision(
            group.id,
            message.from_user.id,
            message_id=message.message_id,
            telegram_update_id=telegram_update_id,
            blocked=blocked,
        )
        if decision.action in {"duplicate", "hold"}:
            return True
    name = escape(message.from_user.first_name or "کاربر")
    mention = f'<a href="tg://user?id={message.from_user.id}">{name}</a>'
    keyboard = start_keyboard(bot_username, message.chat.id, blocked=decision.blocked)
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
        if previous_message_id:
            try:
                await bot.delete_message(message.chat.id, previous_message_id)
            except TelegramAPIError:
                pass
        # delete user message before sending warning notice
        try:
            await bot.delete_message(message.chat.id, message.message_id)
        except TelegramAPIError:
            pass
        try:
            notice = await bot.send_message(
                chat_id=message.chat.id,
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        except TelegramAPIError:
            await _release_notice(decision.state_id, reserved_at)
            await _warning_failed(decision.event_id)
            logger.exception("Bot-start first warning failed for message %s", message.message_id)
        else:
            notice_message_id = getattr(notice, "message_id", None)
            if isinstance(notice_message_id, int):
                await _record_notice(decision.state_id, reserved_at, notice_message_id)
            await _warning_completed(decision.event_id)
        return True

    try:
        await bot.delete_message(message.chat.id, message.message_id)
    except TelegramAPIError:
        await _warning_failed(decision.event_id)
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
    if previous_message_id:
        try:
            await bot.delete_message(message.chat.id, previous_message_id)
        except TelegramAPIError:
            pass
    try:
        notice = await bot.send_message(
            chat_id=message.chat.id,
            text=text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    except TelegramAPIError:
        await _release_notice(decision.state_id, reserved_at)
        logger.exception("Bot-start deletion notice failed for message %s", message.message_id)
    else:
        notice_message_id = getattr(notice, "message_id", None)
        if isinstance(notice_message_id, int):
            await _record_notice(decision.state_id, reserved_at, notice_message_id)
    return True


@sync_to_async(thread_sensitive=True)
def mark_user_started(user_id: int):
    with transaction.atomic():
        user, _ = TelegramUser.objects.select_for_update().get_or_create(user_id=user_id)
        now = timezone.now()
        first_start = user.welcomed_at is None
        user.started = True
        user.blocked = False
        user.warned = False
        user.last_check_at = now
        if first_start:
            user.welcomed_at = now
        user.save(update_fields=[
            "started",
            "blocked",
            "warned",
            "welcomed_at",
            "last_check_at",
        ])
        notice_targets = list(
            BotStartUserState.objects.filter(
                telegram_user_id=user_id,
                notice_message_id__isnull=False,
            ).values_list("group__chat_id", "notice_message_id")
        )
        BotStartUserState.objects.filter(telegram_user_id=user_id).update(
            warning_pending_at=None,
            warning_sent_at=None,
            last_notice_at=None,
            notice_message_id=None,
            notice_delete_at=None,
            updated_at=now,
        )
        BotStartGateEvent.objects.filter(
            telegram_user_id=user_id,
            status="pending",
        ).update(status="completed", updated_at=now)
        return user, notice_targets, first_start


class BotStartGateMiddleware(BaseMiddleware):
    def __init__(self, bot_username: str):
        self.bot_username = bot_username

    async def __call__(self, handler, event, data):
        if isinstance(event, Message):
            update = data.get("event_update")
            blocked = await enforce_bot_start_message(
                event,
                data["bot"],
                bot_username=self.bot_username,
                telegram_update_id=getattr(update, "update_id", None),
            )
            if blocked:
                return None
        return await handler(event, data)
