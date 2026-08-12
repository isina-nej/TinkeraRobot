import asyncio
from types import SimpleNamespace

from asgiref.sync import async_to_sync
from django.test import SimpleTestCase

from botapp.noya_bot_chat import (
    notify_bot_reply_edit,
    reset_bot_reply_limits_for_tests,
    wait_for_bot_reply_body,
    watch_empty_bot_reply,
)


class NoyaBotEditWaitTest(SimpleTestCase):
    def setUp(self):
        reset_bot_reply_limits_for_tests()

    def test_wait_receives_edited_body(self):
        empty = SimpleNamespace(
            chat=SimpleNamespace(id=-1001),
            message_id=50,
            text=None,
            caption=None,
        )
        edited = SimpleNamespace(
            chat=SimpleNamespace(id=-1001),
            message_id=50,
            text="هه، چی شد نویا؟ من اومدم",
            caption=None,
        )

        async def scenario():
            await watch_empty_bot_reply(empty)

            async def late_edit():
                await asyncio.sleep(0.05)
                await notify_bot_reply_edit(edited)

            asyncio.create_task(late_edit())
            filled = await wait_for_bot_reply_body(empty, timeout=1.0)
            return filled

        filled = async_to_sync(scenario)()
        self.assertEqual(filled.text, "هه، چی شد نویا؟ من اومدم")
