import csv
import io
import logging
from html import escape

from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from botapp.forced_membership import (
    forced_membership_report,
    normalize_destination_reference,
)
from botapp.forced_membership_runtime import can_manage_rule
from botapp.models import (
    ForcedMembershipEvent,
    ForcedMembershipRule,
    ForcedMembershipUserState,
    GroupSettings,
)

router = Router(name="forced-membership")
SUPER_ADMIN_IDS: frozenset[int] = frozenset()
logger = logging.getLogger(__name__)


def configure_super_admins(user_ids) -> None:
    global SUPER_ADMIN_IDS
    SUPER_ADMIN_IDS = frozenset(user_ids)


@sync_to_async(thread_sensitive=True)
def save_rule(source_chat, destination_chat, creator_id: int, join_url: str) -> ForcedMembershipRule:
    with transaction.atomic():
        group, _ = GroupSettings.objects.update_or_create(
            chat_id=source_chat.id,
            defaults={"chat_title": source_chat.title or ""},
        )
        rule, created = ForcedMembershipRule.objects.update_or_create(
            source_group=group,
            destination_chat_id=destination_chat.id,
            defaults={
                "destination_chat_title": destination_chat.title or "",
                "destination_chat_type": str(getattr(destination_chat.type, "value", destination_chat.type)),
                "destination_username": destination_chat.username or "",
                "destination_join_url": join_url,
                "created_by_user_id": creator_id,
                "is_active": True,
                "last_validated_at": timezone.now(),
                "bot_source_permissions_valid": True,
                "bot_destination_permissions_valid": True,
            },
        )
        ForcedMembershipEvent.objects.create(
            rule=rule,
            telegram_user_id=creator_id,
            event_type="rule_activated" if created else "rule_updated",
        )
        return rule


@sync_to_async(thread_sensitive=True)
def get_rule(rule_id: int) -> ForcedMembershipRule | None:
    return ForcedMembershipRule.objects.select_related("source_group").filter(pk=rule_id).first()


@sync_to_async(thread_sensitive=True)
def update_rule_destination(rule_id: int, destination, join_url: str, actor_id: int) -> None:
    with transaction.atomic():
        rule = ForcedMembershipRule.objects.select_for_update().get(pk=rule_id)
        if ForcedMembershipRule.objects.filter(
            source_group=rule.source_group,
            destination_chat_id=destination.id,
        ).exclude(pk=rule.id).exists():
            raise ValueError("برای این مقصد قبلاً قانون ثبت شده است.")
        rule.user_states.all().delete()
        rule.invite_links.all().delete()
        rule.events.all().delete()
        rule.destination_chat_id = destination.id
        rule.destination_chat_title = destination.title or ""
        rule.destination_chat_type = str(getattr(destination.type, "value", destination.type))
        rule.destination_username = destination.username or ""
        rule.destination_join_url = join_url
        rule.last_validated_at = timezone.now()
        rule.bot_source_permissions_valid = True
        rule.bot_destination_permissions_valid = True
        rule.save()
        ForcedMembershipEvent.objects.create(
            rule=rule,
            telegram_user_id=actor_id,
            event_type="rule_destination_changed",
        )


@sync_to_async(thread_sensitive=True)
def set_rule_active(rule_id: int, active: bool, actor_id: int) -> None:
    ForcedMembershipRule.objects.filter(pk=rule_id).update(is_active=active, updated_at=timezone.now())
    ForcedMembershipEvent.objects.create(
        rule_id=rule_id,
        telegram_user_id=actor_id,
        event_type="rule_activated" if active else "rule_deactivated",
    )


@sync_to_async(thread_sensitive=True)
def rules_for_user_candidates() -> list[ForcedMembershipRule]:
    return list(ForcedMembershipRule.objects.select_related("source_group").order_by("source_group__chat_title", "id"))


@sync_to_async(thread_sensitive=True)
def rules_for_source_chat(chat_id: int) -> list[ForcedMembershipRule]:
    return list(
        ForcedMembershipRule.objects.select_related("source_group")
        .filter(source_group__chat_id=chat_id)
        .order_by("id")
    )


@sync_to_async(thread_sensitive=True)
def delete_rule(rule_id: int) -> None:
    with transaction.atomic():
        rule = ForcedMembershipRule.objects.select_related("source_group").select_for_update().get(pk=rule_id)
        group = rule.source_group
        legacy = (group.mandatory_channel or "").strip().lower()
        candidates = {
            str(rule.destination_chat_id),
            (rule.destination_username or "").strip().lower(),
            f"@{(rule.destination_username or '').strip().lower()}",
            (rule.destination_join_url or "").strip().lower(),
        }
        rule.delete()
        if legacy and legacy in candidates:
            group.mandatory_channel = ""
            group.channel_join_required = False
            group.save(update_fields=["mandatory_channel", "channel_join_required", "updated_at"])


@sync_to_async(thread_sensitive=True)
def export_rule_csv(rule_id: int) -> bytes:
    rule = ForcedMembershipRule.objects.select_related("source_group").get(pk=rule_id)
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([
        "telegram_user_id", "username", "first_name", "last_name",
        "source_chat", "destination_chat", "first_warning_at",
        "first_joined_at", "last_joined_at", "left_at", "current_status",
        "deleted_message_count", "join_count", "leave_count", "rejoin_count",
    ])
    def safe_cell(value):
        text = "" if value is None else str(value)
        return f"'{text}" if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text

    for state in ForcedMembershipUserState.objects.filter(rule=rule).iterator():
        writer.writerow([
            state.telegram_user_id, safe_cell(state.username), safe_cell(state.first_name), safe_cell(state.last_name),
            safe_cell(rule.source_group.chat_title or rule.source_group.chat_id),
            safe_cell(rule.destination_chat_title or rule.destination_chat_id),
            state.first_warning_at, state.first_joined_at, state.last_joined_at,
            state.left_at, state.current_membership_status,
            state.deleted_message_count, state.join_count, state.leave_count,
            state.rejoin_count,
        ])
    return output.getvalue().encode("utf-8-sig")


def _public_join_url(chat) -> str:
    return f"https://t.me/{chat.username}" if chat.username else ""


async def _status(bot: Bot, chat_id: int, user_id: int):
    return (await bot.get_chat_member(chat_id, user_id)).status


async def _owner_roles(bot: Bot, rule: ForcedMembershipRule, user_id: int) -> set[str]:
    if user_id in SUPER_ADMIN_IDS:
        return {"source", "destination"}
    try:
        source_status = await _status(bot, rule.source_group.chat_id, user_id)
        destination_status = await _status(bot, rule.destination_chat_id, user_id)
    except TelegramAPIError:
        return set()
    roles = set()
    if str(getattr(source_status, "value", source_status)) == "creator":
        roles.add("source")
    if str(getattr(destination_status, "value", destination_status)) == "creator":
        roles.add("destination")
    return roles


async def _can_manage(bot: Bot, rule: ForcedMembershipRule, user_id: int) -> bool:
    return bool(await _owner_roles(bot, rule, user_id))


async def _validate_configuration(message: Message, bot: Bot, destination_ref):
    actor = await bot.get_chat_member(message.chat.id, message.from_user.id)
    if actor.status != ChatMemberStatus.CREATOR and message.from_user.id not in SUPER_ADMIN_IDS:
        raise ValueError("فقط سازنده فعلی گروه می‌تواند عضویت اجباری را تنظیم کند.")
    return await _validate_destination_for_source(message.chat.id, bot, destination_ref)


def _bot_permissions_valid(source_bot, destination_bot) -> bool:
    source_valid = (
        source_bot.status == ChatMemberStatus.CREATOR
        or (
            source_bot.status == ChatMemberStatus.ADMINISTRATOR
            and bool(getattr(source_bot, "can_delete_messages", False))
        )
    )
    destination_valid = destination_bot.status in {
        ChatMemberStatus.CREATOR,
        ChatMemberStatus.ADMINISTRATOR,
    }
    return source_valid and destination_valid


async def _validate_destination_for_source(source_chat_id: int, bot: Bot, destination_ref):
    me = await bot.get_me()
    source_bot = await bot.get_chat_member(source_chat_id, me.id)
    if source_bot.status not in {ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR}:
        raise ValueError("ربات در گروه مبدأ ادمین نیست.")
    if source_bot.status != ChatMemberStatus.CREATOR and not getattr(source_bot, "can_delete_messages", False):
        raise ValueError("ربات در گروه مبدأ اجازه حذف پیام‌ها را ندارد.")

    destination = await bot.get_chat(destination_ref.value)
    destination_bot = await bot.get_chat_member(destination.id, me.id)
    if not _bot_permissions_valid(source_bot, destination_bot):
        raise ValueError("ربات در مقصد ادمین نیست.")
    join_url = _public_join_url(destination)
    if not join_url:
        try:
            invite = await bot.create_chat_invite_link(destination.id, name="forced-membership-probe")
            await bot.revoke_chat_invite_link(destination.id, invite.invite_link)
        except TelegramAPIError as exc:
            raise ValueError("مقصد عمومی نیست و ربات اجازه ساخت Invite Link ندارد.") from exc
    return destination, join_url


def _management_keyboard(rule: ForcedMembershipRule) -> InlineKeyboardMarkup:
    toggle = "غیرفعال‌کردن" if rule.is_active else "فعال‌کردن"
    rows = [
        [InlineKeyboardButton(text=toggle, callback_data=f"fmr:toggle:{rule.id}")],
        [InlineKeyboardButton(text="گزارش", callback_data=f"fmr:report:{rule.id}")],
        [InlineKeyboardButton(text="تغییر مقصد", callback_data=f"fmr:change:{rule.id}")],
        [InlineKeyboardButton(text="بررسی دسترسی‌ها", callback_data=f"fmr:validate:{rule.id}")],
        [InlineKeyboardButton(text="دریافت CSV", callback_data=f"fmr:csv:{rule.id}")],
        [InlineKeyboardButton(text="حذف قانون", callback_data=f"fmr:deleteask:{rule.id}")],
    ]
    if rule.destination_join_url:
        rows.append([InlineKeyboardButton(text="مشاهده مقصد", url=rule.destination_join_url)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _delete_confirmation_keyboard(rule_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="بله، حذف شود", callback_data=f"fmr:delete:{rule_id}")],
        [InlineKeyboardButton(text="انصراف", callback_data=f"fmr:report:{rule_id}")],
    ])


def _report_text(rule, report) -> str:
    return (
        "📊 گزارش عضویت اجباری\n\n"
        f"مبدأ: {escape(rule.source_group.chat_title or str(rule.source_group.chat_id))}\n"
        f"مقصد: {escape(rule.destination_chat_title or str(rule.destination_chat_id))}\n"
        f"Owner: {rule.created_by_user_id}\n"
        f"تاریخ ایجاد: {rule.created_at:%Y-%m-%d %H:%M}\n"
        f"وضعیت: {'فعال ✅' if rule.is_active else 'غیرفعال ❌'}\n\n"
        f"👤 کاربران بررسی‌شده: {report.checked_users}\n"
        f"✅ جوین داده‌اند: {report.joined_users}\n"
        f"⚠️ جوین نداده‌اند: {report.non_joined_users}\n"
        f"🚪 جوین و سپس لفت: {report.left_after_join_users}\n"
        f"🗑 پیام‌های حذف‌شده: {report.deleted_messages}\n"
        f"🔁 عضویت مجدد: {report.rejoin_count}"
    )


@router.callback_query(F.data.regexp(r"^fmr:list:-?\d+$"))
async def forced_membership_group_panel(callback: CallbackQuery, bot: Bot):
    chat_id = int((callback.data or "").rsplit(":", 1)[1])
    if callback.from_user.id not in SUPER_ADMIN_IDS:
        try:
            member = await bot.get_chat_member(chat_id, callback.from_user.id)
        except TelegramAPIError:
            await callback.answer("بررسی دسترسی ممکن نشد.", show_alert=True)
            return
        if member.status != ChatMemberStatus.CREATOR:
            await callback.answer("دسترسی ندارید.", show_alert=True)
            return
    rules = await rules_for_source_chat(chat_id)
    buttons = [
        [InlineKeyboardButton(
            text=(
                f"{'✅' if rule.is_active else '❌'} "
                f"{rule.destination_chat_title or rule.destination_chat_id}"
            )[:60],
            callback_data=f"fmr:report:{rule.id}",
        )]
        for rule in rules
    ]
    if not buttons:
        await callback.message.edit_text(
            "قانونی ثبت نشده است.\n\nنمونه:\nعضویت اجباری @channel"
        )
    else:
        await callback.message.edit_text(
            "قوانین عضویت اجباری این گروه:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
    await callback.answer()


@router.message(F.text.regexp(r"^\s*عضویت\s+اجباری(?:\s+.+)?\s*$"))
async def configure_forced_membership(message: Message, bot: Bot):
    if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return
    raw = message.text.strip().split(maxsplit=2)
    if len(raw) != 3:
        await message.reply("استفاده: عضویت اجباری @channel")
        return
    try:
        reference = normalize_destination_reference(raw[2])
        destination, join_url = await _validate_configuration(message, bot, reference)
        rule = await save_rule(message.chat, destination, message.from_user.id, join_url)
    except (ValueError, TelegramAPIError) as exc:
        await message.reply(f"❌ تنظیم عضویت اجباری انجام نشد.\n{exc}")
        return
    await message.reply(
        "✅ عضویت اجباری با موفقیت فعال شد.\n\n"
        f"گروه مبدأ: {escape(message.chat.title or str(message.chat.id))}\n"
        f"مقصد: {escape(destination.title or str(destination.id))}",
        reply_markup=_management_keyboard(rule),
    )


async def _owned_chat_buttons(bot: Bot, user_id: int) -> list[list[InlineKeyboardButton]]:
    chats: dict[int, str] = {}
    for rule in await rules_for_user_candidates():
        roles = await _owner_roles(bot, rule, user_id)
        if "source" in roles:
            chats[rule.source_group.chat_id] = rule.source_group.chat_title or str(rule.source_group.chat_id)
        if "destination" in roles:
            chats[rule.destination_chat_id] = rule.destination_chat_title or str(rule.destination_chat_id)
    return [
        [InlineKeyboardButton(text=title[:60], callback_data=f"fmr:roles:{chat_id}")]
        for chat_id, title in chats.items()
    ]


@router.message(F.text.regexp(r"^\s*تغییر\s+مقصد\s+\d+\s+.+\s*$"))
async def change_forced_membership_destination(message: Message, bot: Bot):
    parts = message.text.strip().split(maxsplit=3)
    if len(parts) != 4 or not parts[2].isdigit():
        await message.reply("استفاده: تغییر مقصد شناسه_قانون @channel")
        return
    rule = await get_rule(int(parts[2]))
    roles = await _owner_roles(bot, rule, message.from_user.id) if rule else set()
    if not rule or not roles:
        await message.reply("دسترسی ندارید.")
        return
    try:
        reference = normalize_destination_reference(parts[3])
        destination, join_url = await _validate_destination_for_source(
            rule.source_group.chat_id,
            bot,
            reference,
        )
        if "source" not in roles and message.from_user.id not in SUPER_ADMIN_IDS:
            new_owner = await bot.get_chat_member(destination.id, message.from_user.id)
            if new_owner.status != ChatMemberStatus.CREATOR:
                raise ValueError("برای تغییر از سمت مقصد، باید مالک مقصد جدید نیز باشید.")
        await update_rule_destination(rule.id, destination, join_url, message.from_user.id)
    except (ValueError, TelegramAPIError) as exc:
        await message.reply(f"❌ تغییر مقصد انجام نشد.\n{exc}")
        return
    await message.reply(
        "✅ مقصد قانون تغییر کرد.\n"
        f"مقصد جدید: {escape(destination.title or str(destination.id))}"
    )


@router.message(F.text.regexp(r"^\s*گزارش\s+عضو\s+اجباری\s*$"))
async def forced_membership_report_command(message: Message, bot: Bot):
    if message.chat.type != ChatType.PRIVATE:
        await message.reply("گزارش را در گفت‌وگوی خصوصی ربات درخواست کنید.")
        return
    buttons = await _owned_chat_buttons(bot, message.from_user.id)
    if not buttons:
        await message.reply("هیچ گروه یا کانال قابل دسترسی برای شما پیدا نشد.")
        return
    await message.reply(
        "📊 گروه یا کانال را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.regexp(r"^fmr:(roles|source|destination):-?\d+$"))
async def forced_membership_report_callback(callback: CallbackQuery, bot: Bot):
    action, raw_chat_id = (callback.data or "").split(":")[1:]
    try:
        chat_id = int(raw_chat_id)
    except ValueError:
        await callback.answer("درخواست نامعتبر است.", show_alert=True)
        return

    accessible: list[tuple[ForcedMembershipRule, set[str]]] = []
    for rule in await rules_for_user_candidates():
        roles = await _owner_roles(bot, rule, callback.from_user.id)
        if roles:
            accessible.append((rule, roles))

    if action == "roles":
        role_buttons = []
        if any(rule.source_group.chat_id == chat_id and "source" in roles for rule, roles in accessible):
            role_buttons.append([InlineKeyboardButton(text="مبدأ", callback_data=f"fmr:source:{chat_id}")])
        if any(rule.destination_chat_id == chat_id and "destination" in roles for rule, roles in accessible):
            role_buttons.append([InlineKeyboardButton(text="مقصد", callback_data=f"fmr:destination:{chat_id}")])
        if not role_buttons:
            await callback.answer("دسترسی ندارید.", show_alert=True)
            return
        await callback.message.edit_text(
            "نقش این گفت‌وگو را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=role_buttons),
        )
        await callback.answer()
        return

    rules = [
        rule for rule, roles in accessible
        if action in roles
        and (
            (action == "source" and rule.source_group.chat_id == chat_id)
            or (action == "destination" and rule.destination_chat_id == chat_id)
        )
    ]
    if not rules:
        await callback.answer("قانون قابل دسترسی پیدا نشد.", show_alert=True)
        return
    buttons = [
        [InlineKeyboardButton(
            text=(
                f"{rule.source_group.chat_title or rule.source_group.chat_id} ← "
                f"{rule.destination_chat_title or rule.destination_chat_id}"
            )[:60],
            callback_data=f"fmr:report:{rule.id}",
        )]
        for rule in rules
    ]
    await callback.message.edit_text(
        "قانون را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("fmr:"))
async def forced_membership_callback(callback: CallbackQuery, bot: Bot):
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        await callback.answer("درخواست نامعتبر است.", show_alert=True)
        return
    action, rule_id = parts[1], int(parts[2])
    rule = await get_rule(rule_id)
    if not rule or not await _can_manage(bot, rule, callback.from_user.id):
        await callback.answer("دسترسی ندارید.", show_alert=True)
        return
    if action == "toggle":
        await set_rule_active(rule.id, not rule.is_active, callback.from_user.id)
        rule = await get_rule(rule.id)
        await callback.message.edit_reply_markup(reply_markup=_management_keyboard(rule))
        await callback.answer("وضعیت تغییر کرد.")
        return
    if action == "report":
        report = await forced_membership_report(rule.id)
        await callback.message.edit_text(_report_text(rule, report), parse_mode="HTML", reply_markup=_management_keyboard(rule))
        await callback.answer()
        return
    if action == "change":
        await callback.message.edit_text(
            "برای تغییر مقصد، این دستور را در گروه یا پیوی ارسال کنید:\n"
            f"تغییر مقصد {rule.id} @channel"
        )
        await callback.answer()
        return
    if action == "validate":
        try:
            me = await bot.get_me()
            source_bot = await bot.get_chat_member(rule.source_group.chat_id, me.id)
            destination_bot = await bot.get_chat_member(rule.destination_chat_id, me.id)
            valid = _bot_permissions_valid(source_bot, destination_bot)
        except TelegramAPIError:
            valid = False
        await sync_to_async(ForcedMembershipRule.objects.filter(pk=rule.id).update)(
            bot_source_permissions_valid=valid,
            bot_destination_permissions_valid=valid,
            last_validated_at=timezone.now(),
        )
        await callback.answer("دسترسی‌ها معتبر است." if valid else "دسترسی‌های ربات ناقص است.", show_alert=True)
        return
    if action == "csv":
        payload = await export_rule_csv(rule.id)
        await bot.send_document(
            callback.from_user.id,
            BufferedInputFile(payload, filename=f"forced-membership-{rule.id}.csv"),
        )
        await callback.answer("فایل ارسال شد.")
        return
    if action == "deleteask":
        await callback.message.edit_text(
            "آیا از حذف کامل این قانون مطمئن هستید؟\nاین عملیات داده‌های گزارش را نیز حذف می‌کند.",
            reply_markup=_delete_confirmation_keyboard(rule.id),
        )
        await callback.answer()
        return
    if action == "delete":
        await delete_rule(rule.id)
        await callback.message.edit_text("قانون عضویت اجباری حذف شد.")
        await callback.answer()
        return
    await callback.answer("عملیات نامعتبر است.", show_alert=True)
