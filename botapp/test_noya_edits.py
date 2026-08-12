import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from asgiref.sync import async_to_sync
from django.test import SimpleTestCase

from botapp.noya_edits import NoyaEditCoordinator, message_body


def _msg(chat_id=-1001, message_id=50, text=None, caption=None, bot=None, rich_message=None):
    return SimpleNamespace(
        chat=SimpleNamespace(id=chat_id),
        message_id=message_id,
        text=text,
        caption=caption,
        rich_message=rich_message,
        bot=bot or SimpleNamespace(id=1),
    )


def _rich(text: str):
    return SimpleNamespace(blocks=[SimpleNamespace(type="paragraph", text=text)])


class NoyaEditCoordinatorTest(SimpleTestCase):
    def setUp(self):
        self.coord = NoyaEditCoordinator(
            settle_seconds=0.15,
            max_wait_seconds=2.0,
            answered_ttl_seconds=60,
        )

    def tearDown(self):
        self.coord.reset_for_tests()

    def test_empty_shell_then_settled_edit_dispatches_once(self):
        answers = []

        async def on_answer(message):
            answers.append(message_body(message))

        self.coord.set_answer_callback(on_answer)

        async def scenario():
            empty = _msg(text="")
            await self.coord.observe_empty_shell(empty, reason="test")
            await asyncio.sleep(0.05)
            await self.coord.observe_edit(_msg(text="سلام نویا مرحله ۱"), reason="e1")
            await asyncio.sleep(0.05)
            await self.coord.observe_edit(_msg(text="سلام نویا مرحله ۲ نهایی"), reason="e2")
            await asyncio.sleep(0.35)
            # Late cosmetic edit must not answer again.
            await self.coord.observe_edit(_msg(text="سلام نویا مرحله ۲ نهایی."), reason="e3")
            await asyncio.sleep(0.25)

        async_to_sync(scenario)()
        self.assertEqual(answers, ["سلام نویا مرحله ۲ نهایی"])

    def test_edit_without_empty_shell_still_settles(self):
        answers = []

        async def on_answer(message):
            answers.append(message_body(message))

        self.coord.set_answer_callback(on_answer)

        async def scenario():
            await self.coord.observe_edit(_msg(text="میرا اینجام"), reason="solo")
            await asyncio.sleep(0.3)

        async_to_sync(scenario)()
        self.assertEqual(answers, ["میرا اینجام"])

    def test_timeout_without_body_drops_session(self):
        answers = []
        self.coord = NoyaEditCoordinator(settle_seconds=0.1, max_wait_seconds=0.25)
        self.coord.set_answer_callback(AsyncMock(side_effect=lambda m: answers.append(1)))

        async def scenario():
            await self.coord.observe_empty_shell(_msg(text=""), reason="empty")
            await asyncio.sleep(0.4)

        async_to_sync(scenario)()
        self.assertEqual(answers, [])
        self.assertEqual(self.coord._sessions, {})

    def test_rich_message_edit_settles(self):
        """Mira-style RICH_MESSAGE: empty text, body lives in rich_message blocks."""
        answers = []

        async def on_answer(message):
            answers.append(message_body(message))

        self.coord.set_answer_callback(on_answer)

        async def scenario():
            await self.coord.observe_empty_shell(_msg(text="", rich_message=_rich("")), reason="shell")
            await asyncio.sleep(0.05)
            await self.coord.observe_edit(
                _msg(text="", rich_message=_rich("آره سینا جان، من اینجام")),
                reason="rich1",
            )
            await asyncio.sleep(0.35)

        async_to_sync(scenario)()
        self.assertEqual(answers, ["آره سینا جان، من اینجام"])
