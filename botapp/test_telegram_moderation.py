from unittest.mock import AsyncMock, patch

from aiogram.exceptions import TelegramNetworkError
from asgiref.sync import async_to_sync
from django.test import TestCase

from botapp.models import GroupSettings, ModerationAction


class TelegramModerationFailureTest(TestCase):
    def test_network_error_marks_action_failed(self):
        from botapp.telegram_moderation import queue_or_execute

        group = GroupSettings.objects.create(chat_id=-9001, chat_title="moderation")
        bot = AsyncMock()
        bot.id = 999
        error = TelegramNetworkError(method=AsyncMock(), message="offline")

        with patch("botapp.telegram_moderation.execute_telegram_action", side_effect=error):
            with self.assertRaises(TelegramNetworkError):
                async_to_sync(queue_or_execute)(bot=bot, group=group, action="lock")

        action = ModerationAction.objects.get(group=group)
        assert action.status == "failed"
        assert "offline" in action.error
