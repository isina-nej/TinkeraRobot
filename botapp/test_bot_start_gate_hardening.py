from datetime import datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.exceptions import TelegramNetworkError
from aiogram.types import Chat, Message, Update, User
from asgiref.sync import async_to_sync
from django.test import TestCase
from django.utils import timezone

from botapp.models import BotStartGateEvent, GroupSettings, TelegramUser


class BotStartGateHardeningTest(TestCase):
    def setUp(self):
        self.group = GroupSettings.objects.create(
            chat_id=-100123,
            chat_title="source",
            bot_start_required=True,
        )
        self.user = SimpleNamespace(id=42, first_name="Ali", is_bot=False)

    @staticmethod
    def member(status="member", **kwargs):
        return SimpleNamespace(status=status, **kwargs)

    def message(self, message_id, *, media_group_id=None):
        return SimpleNamespace(
            message_id=message_id,
            chat=SimpleNamespace(id=-100123, type="supergroup", title="source"),
            from_user=self.user,
            sender_chat=None,
            new_chat_members=None,
            left_chat_member=None,
            pinned_message=None,
            media_group_id=media_group_id,
        )

    def bot(self):
        bot = AsyncMock()
        bot.id = 999
        bot.get_chat_member.side_effect = [
            self.member("administrator", can_delete_messages=True, can_send_messages=True),
            self.member("member"),
        ] * 20
        return bot

    def test_signed_deep_link_is_short_scoped_and_expires(self):
        from botapp.bot_start_gate import deep_link_payload, parse_deep_link_payload

        payload = deep_link_payload(-100123, 42)
        assert payload.startswith("gate_")
        assert len(payload) <= 64
        assert parse_deep_link_payload(payload, current_user_id=42) == -100123
        assert parse_deep_link_payload(payload, current_user_id=99) is None

        expired = deep_link_payload(
            -100123,
            42,
            expires_at=int((timezone.now() - timedelta(seconds=1)).timestamp()),
        )
        assert parse_deep_link_payload(expired, current_user_id=42) is None

    def test_temporary_permission_error_fails_open_without_state_change(self):
        from botapp.bot_start_gate import enforce_bot_start_message

        TelegramUser.objects.create(telegram_user_id=42, started=True, blocked=False)
        bot = self.bot()
        bot.get_chat_member.side_effect = TelegramNetworkError(method=AsyncMock(), message="offline")

        assert async_to_sync(enforce_bot_start_message)(
            self.message(1), bot, bot_username="NuyaRobot"
        ) is False
        user = TelegramUser.objects.get(telegram_user_id=42)
        assert user.started is True and user.blocked is False
        bot.delete_message.assert_not_awaited()

    def test_raw_connection_error_fails_open_without_state_change(self):
        from botapp.bot_start_gate import enforce_bot_start_message

        TelegramUser.objects.create(telegram_user_id=42, started=True, blocked=False)
        bot = self.bot()
        bot.get_chat_member.side_effect = ConnectionError("offline")

        assert async_to_sync(enforce_bot_start_message)(
            self.message(2), bot, bot_username="NuyaRobot"
        ) is False
        user = TelegramUser.objects.get(telegram_user_id=42)
        assert user.started is True and user.blocked is False

    def test_temporary_live_check_error_preserves_state_and_fails_open(self):
        from botapp.bot_start_gate import enforce_bot_start_message

        TelegramUser.objects.create(telegram_user_id=42, started=True, blocked=False)
        bot = self.bot()
        bot.send_chat_action.side_effect = TelegramNetworkError(method=AsyncMock(), message="offline")

        assert async_to_sync(enforce_bot_start_message)(
            self.message(2), bot, bot_username="NuyaRobot"
        ) is False
        user = TelegramUser.objects.get(telegram_user_id=42)
        assert user.started is True and user.blocked is False

    def test_ten_rapid_messages_are_all_deleted_with_one_warning(self):
        from botapp.bot_start_gate import enforce_bot_start_message

        bot = self.bot()
        for message_id in range(10, 20):
            assert async_to_sync(enforce_bot_start_message)(
                self.message(message_id), bot, bot_username="NuyaRobot"
            ) is True

        assert bot.delete_message.await_count == 10
        assert bot.send_message.await_count == 1

    def test_media_group_deletes_each_item_but_sends_one_warning(self):
        from botapp.bot_start_gate import enforce_bot_start_message

        bot = self.bot()
        for message_id in range(20, 25):
            assert async_to_sync(enforce_bot_start_message)(
                self.message(message_id, media_group_id="album-1"),
                bot,
                bot_username="NuyaRobot",
            ) is True

        assert bot.delete_message.await_count == 5
        assert bot.send_message.await_count == 1
        assert BotStartGateEvent.objects.count() == 1

    def test_start_succeeds_when_warning_cleanup_has_network_error(self):
        from botapp.management.commands.runbot import start
        from botapp.models import GroupUserGateState

        GroupUserGateState.objects.create(
            group=self.group,
            telegram_user_id=42,
            warning_message_id=900,
        )
        message = SimpleNamespace(
            chat=SimpleNamespace(type="private"),
            from_user=self.user,
            answer=AsyncMock(),
        )
        bot = AsyncMock()
        bot.delete_message.side_effect = TelegramNetworkError(method=AsyncMock(), message="offline")

        async_to_sync(start)(message, bot)

        user = TelegramUser.objects.get(telegram_user_id=42)
        assert user.started is True and user.blocked is False
        message.answer.assert_awaited_once()

    def test_edited_message_observer_installs_gate_middleware(self):
        from botapp.bot_start_gate import BotStartGateMiddleware
        from botapp.forced_membership_handlers import router as forced_router
        from botapp.management.commands.runbot import build_dispatcher, router as main_router

        try:
            dispatcher = build_dispatcher("NuyaRobot")
            assert any(
                isinstance(middleware, BotStartGateMiddleware)
                for middleware in dispatcher.edited_message.outer_middleware._middlewares
            )
        finally:
            forced_router._parent_router = None
            main_router._parent_router = None

    def test_any_private_message_marks_access_available(self):
        from botapp.bot_start_gate import BotStartGateMiddleware

        TelegramUser.objects.create(telegram_user_id=42, started=False, blocked=True)
        event = Message(
            message_id=50,
            date=datetime.now(dt_timezone.utc),
            chat=Chat(id=42, type="private", first_name="Ali"),
            from_user=User(id=42, is_bot=False, first_name="Ali"),
            text="سلام",
        )
        handler = AsyncMock(return_value="handled")
        bot = AsyncMock()

        assert async_to_sync(BotStartGateMiddleware("NuyaRobot"))(
            handler,
            event,
            {"bot": bot, "event_update": Update(update_id=500, message=event)},
        ) == "handled"
        user = TelegramUser.objects.get(telegram_user_id=42)
        assert user.started is True and user.blocked is False
