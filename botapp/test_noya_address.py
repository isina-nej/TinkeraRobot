from types import SimpleNamespace

from django.test import SimpleTestCase

from botapp.noya_address import is_addressing_noya


class NoyaAddressTest(SimpleTestCase):
    def test_reply_to_bot_counts(self):
        msg = SimpleNamespace(
            text="هه چی شد",
            caption=None,
            reply_to_message=SimpleNamespace(
                from_user=SimpleNamespace(id=111001, is_bot=True)
            ),
        )
        self.assertTrue(is_addressing_noya(msg, bot_id=111001, bot_username="BotUnderTest"))
        self.assertFalse(is_addressing_noya(msg, bot_id=1, bot_username="BotUnderTest"))

    def test_mention_and_name(self):
        msg = SimpleNamespace(text="@BotUnderTest سلام", caption=None, reply_to_message=None)
        self.assertTrue(is_addressing_noya(msg, bot_id=1, bot_username="BotUnderTest"))
        msg2 = SimpleNamespace(text="نویا جان کجایی", caption=None, reply_to_message=None)
        self.assertTrue(is_addressing_noya(msg2, bot_id=1, bot_username="BotUnderTest"))
        msg3 = SimpleNamespace(text="سلام به همه", caption=None, reply_to_message=None)
        self.assertFalse(is_addressing_noya(msg3, bot_id=1, bot_username="BotUnderTest"))
