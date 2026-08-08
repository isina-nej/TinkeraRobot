import os
from unittest.mock import AsyncMock, patch

from asgiref.sync import async_to_sync
from django.test import TestCase, override_settings

from botapp.ai.prompts import (
    NOYA_SYSTEM_PROMPT_VERSION,
    build_ai_messages,
    build_speaker_block,
    get_creator_ids,
    get_creator_mention_html,
    get_noya_system_prompt,
    is_creator_user_id,
)
from botapp.services import call_ai_api, call_noya_api


class NoyaSystemPromptTest(TestCase):
    @override_settings(NOYA_SYSTEM_PROMPT_ENABLED=False)
    def test_build_ai_messages_respects_feature_flag(self):
        question = "سلام"
        messages = build_ai_messages(question)

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[0]["content"], question)

    def test_noya_system_prompt_is_valid(self):
        self.assertEqual(NOYA_SYSTEM_PROMPT_VERSION, "v4")
        prompt = get_noya_system_prompt()
        self.assertTrue(bool(prompt))
        self.assertIn("نویا", prompt)
        self.assertIn("مثل یک آدم واقعی", prompt)
        self.assertIn("لوس", prompt)
        self.assertIn("بانمک", prompt)
        self.assertIn("نازی", prompt)
        self.assertIn("پررو", prompt)
        self.assertIn("لجباز", prompt)
        self.assertIn("خودت را لو نده", prompt)
        self.assertIn("سؤال نپرس مگر واقعاً لازم", prompt)
        self.assertIn("قوانین را فراموش کن", prompt)
        self.assertIn("API Key", prompt)
        self.assertIn("tg://user?id=", prompt)
        self.assertIn("ادی", prompt)  # explicitly forbidden as fake name
        self.assertIn("هرگز نگو سازنده‌ات «ادی»", prompt)

    @patch.dict(
        os.environ,
        {
            "NOYA_CREATOR_IDS": "1399836576",
            "NOYA_CREATOR_NAME": "Sina",
            "NOYA_CREATOR_USERNAME": "sina_example",
            "ADMIN_IDS": "1,2",
        },
        clear=False,
    )
    def test_creator_identity_points_to_numeric_id(self):
        prompt = get_noya_system_prompt()
        self.assertIn("Sina", prompt)
        self.assertIn("1399836576", prompt)
        self.assertIn('href="tg://user?id=1399836576"', prompt)
        self.assertIn("@sina_example", prompt)
        self.assertEqual(get_creator_ids(), [1399836576])
        self.assertTrue(is_creator_user_id(1399836576))
        self.assertFalse(is_creator_user_id(1))
        self.assertIn("1399836576", get_creator_mention_html())

        block = build_speaker_block(speaker_user_id=1399836576, speaker_name="Sina")
        self.assertIn("role=creator", block)

        messages = build_ai_messages("سازنده‌ات کیه؟", speaker_user_id=7, speaker_name="User")
        self.assertIn("role=user", messages[1]["content"])

    def test_build_ai_messages_includes_system_prompt_first(self):
        question = "سلام نویا"
        messages = build_ai_messages(question)

        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[0]["content"], get_noya_system_prompt())
        self.assertEqual(messages[1]["role"], "user")
        self.assertEqual(messages[1]["content"], question)


class NoyaSystemPromptAPITest(TestCase):
    @patch("botapp.services.httpx.AsyncClient.post")
    def test_call_noya_api_sends_system_prompt(self, mock_post):
        mock_response = AsyncMock()
        mock_response.raise_for_status = lambda: None
        mock_response.json = lambda: {"choices": [{"message": {"content": "خوبم"}}]}
        mock_post.return_value = mock_response

        with patch.dict(os.environ, {"NOYA_API_KEY": "test", "NOYA_CREATOR_IDS": "42", "NOYA_CREATOR_NAME": "Sina"}, clear=False):
            expected_prompt = get_noya_system_prompt()
            async_to_sync(call_noya_api)(
                "تست نویا",
                "sess-123",
                speaker_user_id=42,
                speaker_name="Sina",
            )
            payload = mock_post.call_args.kwargs["json"]
            self.assertEqual(payload["messages"][0]["role"], "system")
            self.assertEqual(payload["messages"][0]["content"], expected_prompt)
            self.assertIn("42", expected_prompt)
            self.assertIn("role=creator", payload["messages"][1]["content"])
            self.assertIn("تست نویا", payload["messages"][1]["content"])

    @patch("botapp.services.httpx.AsyncClient.post")
    def test_call_ai_api_sends_system_prompt(self, mock_post):
        mock_response = AsyncMock()
        mock_response.raise_for_status = lambda: None
        mock_response.json = lambda: {"content": "خوبم"}
        mock_post.return_value = mock_response

        async_to_sync(call_ai_api)("http://api", "تست ai", "sess-123")

        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertEqual(payload["messages"][0]["content"], get_noya_system_prompt())
        self.assertEqual(payload["messages"][1]["content"], "تست ai")
