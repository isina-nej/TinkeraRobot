from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from django.utils import timezone

from asgiref.sync import async_to_sync
from django.test import TestCase

from botapp.models import GroupSettings, TelegramUser


class BotStartGateRuntimeTest(TestCase):
    def setUp(self):
        self.group = GroupSettings.objects.create(
            chat_id=-100123,
            chat_title="source",
            bot_start_required=True,
        )
        self.user = SimpleNamespace(
            id=42,
            username=None,
            first_name="<Ali>",
            is_bot=False,
        )

    def message(self, message_id: int, chat_id: int = -100123):
        return SimpleNamespace(
            message_id=message_id,
            chat=SimpleNamespace(id=chat_id, type="supergroup", title="source"),
            from_user=self.user,
            sender_chat=None,
            new_chat_members=None,
            left_chat_member=None,
            pinned_message=None,
        )

    @staticmethod
    def member(status="member", **kwargs):
        return SimpleNamespace(status=status, **kwargs)

    def bot(self):
        bot = AsyncMock()
        bot.id = 999
        bot.get_chat_member.side_effect = [
            self.member("administrator", can_delete_messages=True),
            self.member("member"),
            self.member("administrator", can_delete_messages=True),
            self.member("member"),
        ]
        return bot

    def test_first_message_warns_and_second_is_deleted_with_group_deep_link(self):
        from botapp.bot_start_gate import enforce_bot_start_message
        from botapp.models import GroupUserGateState

        bot = self.bot()

        first = async_to_sync(enforce_bot_start_message)(
            self.message(1), bot, bot_username="NuyaRobot"
        )
        second = async_to_sync(enforce_bot_start_message)(
            self.message(2), bot, bot_username="NuyaRobot"
        )

        state = GroupUserGateState.objects.get(group=self.group, telegram_user_id=42)
        assert first is True
        assert second is True
        assert bot.delete_message.await_count == 2
        assert bot.send_message.await_count == 1
        first_send = bot.send_message.await_args
        assert "&lt;Ali&gt;" in first_send.kwargs["text"]
        assert first_send.kwargs["reply_markup"].inline_keyboard[0][0].url.startswith(
            "https://t.me/NuyaRobot?start=gate_"
        )
        assert state.warning_sent_at is not None
        assert state.message_deleted_count == 2

    def test_started_user_is_allowed(self):
        from botapp.bot_start_gate import enforce_bot_start_message

        TelegramUser.objects.create(telegram_user_id=42, started=True)
        bot = AsyncMock()
        bot.id = 999
        bot.get_chat_member.side_effect = [
            self.member("administrator", can_delete_messages=True),
            self.member("member"),
        ]
        bot.send_chat_action.return_value = True

        blocked = async_to_sync(enforce_bot_start_message)(
            self.message(3), bot, bot_username="NuyaRobot"
        )

        assert blocked is False
        bot.send_message.assert_not_awaited()
        bot.delete_message.assert_not_awaited()

    def test_notice_is_sent_at_most_once_per_three_minutes(self):
        from botapp.bot_start_gate import enforce_bot_start_message

        bot = self.bot()
        bot.send_message.return_value = SimpleNamespace(message_id=700)
        async_to_sync(enforce_bot_start_message)(
            self.message(20), bot, bot_username="wrong_name"
        )
        async_to_sync(enforce_bot_start_message)(
            self.message(21), bot, bot_username="wrong_name"
        )

        assert bot.delete_message.await_count == 2
        assert bot.send_message.await_count == 1
        state = self.group.user_gate_states.get(telegram_user_id=42)
        assert state.warning_message_id == 700
        assert state.notice_delete_at == state.last_warning_update_at + timedelta(minutes=3)

    def test_notice_is_resent_after_three_minutes(self):
        from botapp.bot_start_gate import enforce_bot_start_message

        bot = self.bot()
        first_notice = SimpleNamespace(message_id=700)
        second_notice = SimpleNamespace(message_id=701)
        bot.send_message.side_effect = [first_notice, second_notice]
        async_to_sync(enforce_bot_start_message)(self.message(22), bot, bot_username="wrong_name")
        state = self.group.user_gate_states.get(telegram_user_id=42)
        state.last_warning_update_at = timezone.now() - timedelta(minutes=3, seconds=1)
        state.notice_delete_at = timezone.now() - timedelta(seconds=1)
        state.save(update_fields=["last_warning_update_at", "notice_delete_at"])

        async_to_sync(enforce_bot_start_message)(self.message(23), bot, bot_username="wrong_name")

        assert bot.send_message.await_count == 2
        assert bot.send_message.await_args.kwargs["reply_markup"].inline_keyboard[0][0].url.startswith(
            "https://t.me/wrong_name?start=gate_"
        )

    def test_due_notice_cleanup_survives_restart(self):
        from botapp.bot_start_gate import cleanup_due_notices
        from botapp.models import GroupUserGateState

        state = GroupUserGateState.objects.create(
            group=self.group,
            telegram_user_id=42,
            last_warning_update_at=timezone.now() - timedelta(minutes=4),
            warning_message_id=800,
            notice_delete_at=timezone.now() - timedelta(minutes=1),
        )
        bot = AsyncMock()

        assert async_to_sync(cleanup_due_notices)(bot) == 1
        bot.delete_message.assert_awaited_once_with(-100123, 800)
        state.refresh_from_db()
        assert state.warning_message_id is None
        assert state.notice_delete_at is None

    def test_states_are_independent_per_group(self):
        from botapp.bot_start_gate import enforce_bot_start_message
        from botapp.models import GroupUserGateState

        second_group = GroupSettings.objects.create(
            chat_id=-100456,
            chat_title="second",
            bot_start_required=True,
        )
        bot = AsyncMock()
        bot.id = 999
        bot.get_chat_member.side_effect = [
            self.member("administrator", can_delete_messages=True),
            self.member("member"),
            self.member("administrator", can_delete_messages=True),
            self.member("member"),
        ]

        async_to_sync(enforce_bot_start_message)(
            self.message(4), bot, bot_username="NuyaRobot"
        )
        async_to_sync(enforce_bot_start_message)(
            self.message(5, second_group.chat_id), bot, bot_username="NuyaRobot"
        )

        assert GroupUserGateState.objects.filter(telegram_user_id=42).count() == 2
        assert bot.delete_message.await_count == 2
        assert bot.send_message.await_count == 2

    def test_blocked_user_gets_block_warning_then_delete_notice(self):
        from aiogram.exceptions import TelegramForbiddenError
        from botapp.bot_start_gate import enforce_bot_start_message
        from botapp.models import GroupUserGateState

        TelegramUser.objects.create(telegram_user_id=42, started=True)
        bot = AsyncMock()
        bot.id = 999
        bot.get_chat_member.side_effect = [
            self.member("administrator", can_delete_messages=True),
            self.member("member"),
            self.member("administrator", can_delete_messages=True),
            self.member("member"),
        ]
        bot.send_chat_action.side_effect = TelegramForbiddenError(
            method=AsyncMock(), message="bot was blocked by the user"
        )

        first = async_to_sync(enforce_bot_start_message)(
            self.message(6), bot, bot_username="NuyaRobot"
        )
        second = async_to_sync(enforce_bot_start_message)(
            self.message(7), bot, bot_username="NuyaRobot"
        )

        user = TelegramUser.objects.get(telegram_user_id=42)
        state = GroupUserGateState.objects.get(group=self.group, telegram_user_id=42)
        assert first is True and second is True
        assert user.started is False and user.blocked is True
        assert "مسدود کرده‌اید" in bot.send_message.await_args.kwargs["text"]
        assert bot.send_message.await_args.kwargs["reply_markup"].inline_keyboard[0][0].text == "🚀 باز کردن ربات"
        assert state.message_deleted_count == 2

    def test_start_marks_user_allowed_clears_group_warnings_and_sends_exact_welcome(self):
        from botapp.bot_start_gate import WELCOME_TEXT, mark_user_started
        from botapp.models import GroupUserGateState

        TelegramUser.objects.create(telegram_user_id=42, started=False, blocked=True)
        state = GroupUserGateState.objects.create(
            group=self.group,
            telegram_user_id=42,
            warning_pending_at="2026-01-01T00:00:00Z",
            warning_sent_at="2026-01-01T00:00:00Z",
            message_deleted_count=2,
        )
        from botapp.models import BotStartGateEvent
        event = BotStartGateEvent.objects.create(
            group=self.group,
            telegram_user_id=42,
            message_id=99,
            action="warn",
            status="pending",
        )

        async_to_sync(mark_user_started)(42)

        user = TelegramUser.objects.get(telegram_user_id=42)
        state.refresh_from_db()
        event.refresh_from_db()
        assert user.started is True and user.blocked is False
        assert state.warning_pending_at is None and state.warning_sent_at is None
        assert event.status == "completed"
        assert WELCOME_TEXT.startswith("به ربات تینکرا خوش اومدی. 🚀")
        assert WELCOME_TEXT.endswith("ممنونیم. ❤️")

    def test_failed_warning_rolls_back_and_failed_delete_is_not_counted(self):
        from aiogram.exceptions import TelegramNetworkError
        from botapp.bot_start_gate import enforce_bot_start_message
        from botapp.models import GroupUserGateState

        bot = self.bot()
        bot.send_message.side_effect = TelegramNetworkError(method=AsyncMock(), message="offline")
        assert async_to_sync(enforce_bot_start_message)(
            self.message(8), bot, bot_username="NuyaRobot"
        ) is True
        state = GroupUserGateState.objects.get(group=self.group, telegram_user_id=42)
        assert state.warning_sent_at is None

        state.warning_sent_at = "2026-01-01T00:00:00Z"
        state.save(update_fields=["warning_sent_at"])
        bot = self.bot()
        bot.delete_message.side_effect = TelegramNetworkError(method=AsyncMock(), message="offline")
        assert async_to_sync(enforce_bot_start_message)(
            self.message(9), bot, bot_username="NuyaRobot"
        ) is True
        state.refresh_from_db()
        assert state.message_deleted_count == 0

    def test_duplicate_message_delivery_has_no_second_side_effect(self):
        from botapp.bot_start_gate import enforce_bot_start_message

        bot = self.bot()
        message = self.message(10)

        first = async_to_sync(enforce_bot_start_message)(
            message, bot, bot_username="NuyaRobot", telegram_update_id=501
        )
        duplicate = async_to_sync(enforce_bot_start_message)(
            message, bot, bot_username="NuyaRobot", telegram_update_id=501
        )

        assert first is True and duplicate is True
        bot.send_message.assert_awaited_once()
        bot.delete_message.assert_awaited_once_with(-100123, 10)

    def test_pending_warning_never_turns_concurrent_message_into_delete(self):
        from botapp.bot_start_gate import _prepare_decision, _warning_failed

        first = async_to_sync(_prepare_decision)(
            self.group.id, 42, message_id=11, telegram_update_id=601, blocked=False
        )
        concurrent = async_to_sync(_prepare_decision)(
            self.group.id, 42, message_id=12, telegram_update_id=602, blocked=False
        )
        async_to_sync(_warning_failed)(first.event_id)
        retry = async_to_sync(_prepare_decision)(
            self.group.id, 42, message_id=12, telegram_update_id=602, blocked=False
        )

        assert first.action == "warn"
        assert concurrent.action == "hold"
        assert retry.action == "warn"

    def test_concurrent_second_message_is_deleted_without_waiting(self):
        from botapp.bot_start_gate import _prepare_decision, enforce_bot_start_message

        async_to_sync(_prepare_decision)(
            self.group.id, 42, message_id=14, telegram_update_id=701, blocked=False
        )
        bot = self.bot()

        assert async_to_sync(enforce_bot_start_message)(
            self.message(15), bot, bot_username="NuyaRobot", telegram_update_id=702
        ) is True
        bot.delete_message.assert_awaited_once_with(-100123, 15)
        bot.send_message.assert_not_awaited()

    def test_all_non_user_content_types_are_service_exempt(self):
        from botapp.bot_start_gate import _service_or_exempt

        for content_type in (
            "forum_topic_created",
            "video_chat_started",
            "boost_added",
            "migrate_to_chat_id",
            "new_chat_title",
            "message_auto_delete_timer_changed",
        ):
            message = self.message(13)
            message.content_type = content_type
            assert _service_or_exempt(message) is True, content_type

    def test_official_username_and_exact_welcome_text(self):
        from botapp.bot_start_gate import OFFICIAL_BOT_USERNAME, WELCOME_TEXT, start_keyboard

        assert OFFICIAL_BOT_USERNAME == "NuyaRobot"
        assert start_keyboard("wrong_name", -100123, 42).inline_keyboard[0][0].url.startswith(
            "https://t.me/wrong_name?start=gate_"
        )
        assert WELCOME_TEXT == (
            "به ربات تینکرا خوش اومدی. 🚀\n\n"
            "اگر مشکلی مشاهده کردی یا پیشنهادی برای بهتر شدن ربات داشتی، خوشحال می‌شیم با ما در میون بذاری. "
            "بازخوردهای شما مستقیماً در بهبود نسخه‌های بعدی تأثیر داره.\n"
            "ارتباط با ما: @TinkeraSupport\n\n"
            "از اینکه در این مرحله کنار ما هستی و به بهتر شدن ربات کمک می‌کنی، ممنونیم. ❤️"
        )

    def test_start_handler_sends_welcome_on_every_start(self):
        from botapp.bot_start_gate import WELCOME_TEXT
        from botapp.management.commands.runbot import start

        message = SimpleNamespace(
            chat=SimpleNamespace(type="private"),
            from_user=self.user,
            answer=AsyncMock(),
        )
        bot = AsyncMock()
        async_to_sync(start)(message, bot)
        async_to_sync(start)(message, bot)

        user = TelegramUser.objects.get(telegram_user_id=42)
        assert user.started is True and user.blocked is False
        assert message.answer.await_count == 2
        message.answer.assert_awaited_with(WELCOME_TEXT)

    def test_dispatcher_factory_installs_both_outer_middlewares(self):
        from botapp.bot_start_gate import BotStartGateMiddleware
        from botapp.forced_membership_handlers import router as forced_router
        from botapp.forced_membership_runtime import ForcedMembershipMiddleware
        from botapp.management.commands.runbot import build_dispatcher, router as main_router

        try:
            dispatcher = build_dispatcher("NuyaRobot")
            middlewares = dispatcher.message.outer_middleware._middlewares
            assert isinstance(middlewares[0], ForcedMembershipMiddleware)
            assert isinstance(middlewares[1], BotStartGateMiddleware)
        finally:
            forced_router._parent_router = None
            main_router._parent_router = None

    def test_real_aiogram_command_message_is_stopped_by_outer_middleware(self):
        from datetime import datetime, timezone

        from aiogram.types import Chat, Message, User
        from botapp.bot_start_gate import BotStartGateMiddleware

        event = Message(
            message_id=10,
            date=datetime.now(timezone.utc),
            chat=Chat(id=-100123, type="supergroup", title="source"),
            from_user=User(id=42, is_bot=False, first_name="<Ali>"),
            text="/rules",
        )
        bot = AsyncMock()
        bot.id = 999
        bot.get_chat_member.side_effect = [
            self.member("administrator", can_delete_messages=True),
            self.member("member"),
        ]
        handler = AsyncMock(return_value="handled")

        result = async_to_sync(BotStartGateMiddleware("NuyaRobot"))(
            handler,
            event,
            {"bot": bot},
        )

        assert result is None
        handler.assert_not_awaited()
        bot.send_message.assert_awaited_once()

    def test_dispatcher_end_to_end_group_warning_then_private_start(self):
        from datetime import datetime, timezone

        from aiogram.types import Chat, Message, Update, User
        from botapp.bot_start_gate import WELCOME_TEXT
        from botapp.forced_membership_handlers import router as forced_router
        from botapp.management.commands.runbot import build_dispatcher, router as main_router

        bot = AsyncMock()
        bot.id = 999
        bot.get_chat_member = AsyncMock(side_effect=[
            self.member("administrator", can_delete_messages=True),
            self.member("member"),
        ])
        bot.send_message = AsyncMock()
        bot.send_chat_action = AsyncMock()
        bot.delete_message = AsyncMock()

        dispatcher = build_dispatcher("NuyaRobot")
        user = User(id=42, is_bot=False, first_name="<Ali>")
        group_update = Update(
            update_id=100,
            message=Message(
                message_id=11,
                date=datetime.now(timezone.utc),
                chat=Chat(id=-100123, type="supergroup", title="source"),
                from_user=user,
                text="/rules",
            ),
        )
        private_update = Update(
            update_id=101,
            message=Message(
                message_id=12,
                date=datetime.now(timezone.utc),
                chat=Chat(id=42, type="private", first_name="<Ali>"),
                from_user=user,
                text="/start g_100123",
                entities=[{"type": "bot_command", "offset": 0, "length": 6}],
            ),
        )

        try:
            async_to_sync(dispatcher.feed_update)(bot, group_update)
            async_to_sync(dispatcher.feed_update)(bot, private_update)
        finally:
            forced_router._parent_router = None
            main_router._parent_router = None

        telegram_user = TelegramUser.objects.get(telegram_user_id=42)
        assert telegram_user.started is True
        assert "?start=gate_" in (
            bot.send_message.await_args_list[0].kwargs["reply_markup"].inline_keyboard[0][0].url
        )
        assert bot.await_args.args[0].text == WELCOME_TEXT

    def test_bot_admin_user_admin_bot_and_service_messages_are_exempt(self):
        from botapp.bot_start_gate import enforce_bot_start_message

        bot = AsyncMock()
        bot.id = 999
        bot.get_chat_member.side_effect = [
            self.member("member"),
            self.member("administrator", can_delete_messages=True),
            self.member("creator"),
        ]
        assert async_to_sync(enforce_bot_start_message)(
            self.message(6), bot, bot_username="NuyaRobot"
        ) is False

        admin_bot = AsyncMock()
        admin_bot.id = 999
        admin_bot.get_chat_member.side_effect = [
            self.member("administrator", can_delete_messages=True),
            self.member("creator"),
        ]
        assert async_to_sync(enforce_bot_start_message)(
            self.message(7), admin_bot, bot_username="NuyaRobot"
        ) is False

        bot_user_message = self.message(8)
        bot_user_message.from_user = SimpleNamespace(id=77, is_bot=True)
        service_message = self.message(9)
        service_message.new_chat_members = [self.user]
        anonymous_admin_message = self.message(10)
        anonymous_admin_message.sender_chat = SimpleNamespace(id=-100123, type="supergroup")
        plain_bot = AsyncMock()
        plain_bot.id = 999
        assert async_to_sync(enforce_bot_start_message)(
            bot_user_message, plain_bot, bot_username="NuyaRobot"
        ) is False
        assert async_to_sync(enforce_bot_start_message)(
            service_message, plain_bot, bot_username="NuyaRobot"
        ) is False
        assert async_to_sync(enforce_bot_start_message)(
            anonymous_admin_message, plain_bot, bot_username="NuyaRobot"
        ) is False
        plain_bot.get_chat_member.assert_not_awaited()
