from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram.exceptions import TelegramNetworkError
from aiogram.types import ChatPermissions
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


class LockSnapshotTest(TestCase):
    def _lock(self, bot, group):
        from botapp.telegram_gateway import execute_telegram_action

        action = ModerationAction.objects.create(
            group=group, action="lock", idempotency_key=f"t-{ModerationAction.objects.count()}"
        )
        async_to_sync(execute_telegram_action)(bot, action)

    def test_locking_already_locked_group_keeps_open_snapshot(self):
        group = GroupSettings.objects.create(chat_id=-9100, chat_title="g")

        bot = AsyncMock()
        # First lock: group is currently OPEN -> snapshot must capture open perms.
        bot.get_chat.return_value = SimpleNamespace(
            permissions=ChatPermissions(can_send_messages=True, can_add_web_page_previews=True)
        )
        self._lock(bot, group)
        group.refresh_from_db()
        self.assertTrue(group.open_permissions_snapshot.get("can_send_messages"))
        good_snapshot = group.open_permissions_snapshot

        # Second lock while ALREADY locked: must NOT overwrite the good snapshot
        # with the locked (can_send_messages=False) state.
        bot.get_chat.return_value = SimpleNamespace(
            permissions=ChatPermissions(can_send_messages=False)
        )
        self._lock(bot, group)
        group.refresh_from_db()
        self.assertEqual(group.open_permissions_snapshot, good_snapshot)
        self.assertTrue(group.open_permissions_snapshot.get("can_send_messages"))
