from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from django.test import SimpleTestCase

from botapp.nouya_handler import (
    _channel_question,
    _guest_question,
    channel_nouya_handler,
    guest_nouya_handler,
    router,
)


class GuestBotTest(SimpleTestCase):
    def test_guest_question_removes_bot_mention_and_keeps_reply_context(self):
        message = SimpleNamespace(
            text="@NuyaRobot این را بررسی کن",
            caption=None,
            reply_to_message=SimpleNamespace(text="متن قبلی", caption=None),
        )

        self.assertEqual(
            _guest_question(message, "NuyaRobot"),
            "[پیام مورد اشاره]\nمتن قبلی\n\n[درخواست فعلی]\nاین را بررسی کن",
        )

    def test_guest_handler_answers_guest_query_with_model_result(self):
        answer_guest_query = AsyncMock(
            return_value=SimpleNamespace(inline_message_id="inline-123"),
        )
        edit_message_text = AsyncMock()
        message = SimpleNamespace(
            guest_query_id="guest-123",
            text="@NuyaRobot سلام",
            caption=None,
            reply_to_message=None,
            chat=SimpleNamespace(id=-100),
            message_id=42,
            bot=SimpleNamespace(
                get_me=AsyncMock(return_value=SimpleNamespace(username="NuyaRobot")),
                edit_message_text=edit_message_text,
            ),
            answer_guest_query=answer_guest_query,
        )

        with patch(
            "botapp.nouya_handler.call_noya_api",
            new=AsyncMock(return_value="سلام، من نویا هستم."),
        ) as call_ai:
            import asyncio

            asyncio.run(guest_nouya_handler(message))

        call_ai.assert_awaited_once_with(
            "سلام",
            session_id="telegram:guest:-100:42",
        )
        answer_guest_query.assert_awaited_once()
        progress = answer_guest_query.await_args.kwargs["result"]
        self.assertEqual(progress.type, "article")
        self.assertEqual(progress.input_message_content.message_text, "در حال بررسی…")
        edit_message_text.assert_awaited_once_with(
            inline_message_id="inline-123",
            text="سلام، من نویا هستم.",
        )

    def test_channel_question_targets_mention_or_name_only(self):
        self.assertEqual(_channel_question("@NuyaRobot امروز چه خبر؟", "NuyaRobot"), "امروز چه خبر؟")
        self.assertEqual(_channel_question("نویا این را خلاصه کن", "NuyaRobot"), "این را خلاصه کن")
        self.assertIsNone(_channel_question("یک پست عادی", "NuyaRobot"))

    def test_channel_handler_replies_to_targeted_post(self):
        message = SimpleNamespace(
            text="@NuyaRobot سلام",
            bot=SimpleNamespace(
                get_me=AsyncMock(return_value=SimpleNamespace(username="NuyaRobot")),
            ),
            chat=SimpleNamespace(id=-100),
            message_id=77,
            reply=AsyncMock(return_value=SimpleNamespace(edit_text=AsyncMock())),
        )
        with patch(
            "botapp.nouya_handler.call_noya_api",
            new=AsyncMock(return_value="پاسخ کانال"),
        ) as call_ai:
            import asyncio

            asyncio.run(channel_nouya_handler(message))
        call_ai.assert_awaited_once_with(
            "سلام",
            session_id="telegram:channel:-100:77",
        )
        message.reply.assert_awaited_once_with("در حال بررسی…")
        message.reply.return_value.edit_text.assert_awaited_once_with("پاسخ کانال")

    def test_guest_update_observer_is_registered(self):
        self.assertIn("guest_message", router.resolve_used_update_types())
        self.assertIn("channel_post", router.resolve_used_update_types())

    def test_channel_handler_ignores_regular_post(self):
        message = SimpleNamespace(
            text="یک پست عادی",
            bot=SimpleNamespace(
                get_me=AsyncMock(return_value=SimpleNamespace(username="NuyaRobot")),
            ),
            reply=AsyncMock(),
        )
        import asyncio

        asyncio.run(channel_nouya_handler(message))
        message.reply.assert_not_awaited()
