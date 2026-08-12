from types import SimpleNamespace

from django.test import SimpleTestCase

from botapp.noya_bot_chat import (
    allow_bot_to_bot_reply,
    is_other_bot_sender,
    is_self_bot_message,
    reset_bot_reply_limits_for_tests,
)
from botapp.management.commands.runbot import is_bot_mentioned


class NoyaBotChatTest(SimpleTestCase):
    def setUp(self):
        reset_bot_reply_limits_for_tests()

    def test_identifies_other_bot_vs_self(self):
        other = SimpleNamespace(from_user=SimpleNamespace(id=99, is_bot=True))
        self_msg = SimpleNamespace(from_user=SimpleNamespace(id=7, is_bot=True))
        human = SimpleNamespace(from_user=SimpleNamespace(id=1, is_bot=False))
        self.assertTrue(is_other_bot_sender(other, self_bot_id=7))
        self.assertFalse(is_other_bot_sender(self_msg, self_bot_id=7))
        self.assertFalse(is_other_bot_sender(human, self_bot_id=7))
        self.assertTrue(is_self_bot_message(self_msg, self_bot_id=7))
        self.assertFalse(is_self_bot_message(other, self_bot_id=7))

    def test_rate_limit_blocks_loops(self):
        self.assertTrue(allow_bot_to_bot_reply(-100, 55, window_seconds=60, max_per_window=2))
        self.assertTrue(allow_bot_to_bot_reply(-100, 55, window_seconds=60, max_per_window=2))
        self.assertFalse(allow_bot_to_bot_reply(-100, 55, window_seconds=60, max_per_window=2))
        # Different bot is independent.
        self.assertTrue(allow_bot_to_bot_reply(-100, 56, window_seconds=60, max_per_window=2))

    def test_mention_detects_command_at_bot(self):
        msg = SimpleNamespace(
            text="/ask@NoyaBot hello",
            caption=None,
            reply_to_message=None,
            entities=None,
            caption_entities=None,
            bot=None,
        )
        self.assertTrue(is_bot_mentioned(msg, "NoyaBot"))
        self.assertFalse(is_bot_mentioned(msg, "OtherBot"))
