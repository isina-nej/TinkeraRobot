from django.test import TestCase, override_settings
from botapp.ai.prompts import get_noya_system_prompt, build_ai_messages, NOYA_SYSTEM_PROMPT


class NoyaSystemPromptTest(TestCase):
    @override_settings(NOYA_SYSTEM_PROMPT_ENABLED=False)
    def test_build_ai_messages_respects_feature_flag(self):
        question = "سلام"
        messages = build_ai_messages(question)
        
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[0]["content"], question)

    def test_noya_system_prompt_is_valid(self):
        prompt = get_noya_system_prompt()
        self.assertTrue(bool(prompt))
        self.assertIn("نام تو «نویا» است", prompt)
        self.assertIn("همیشه فارسی بنویس", prompt)
        self.assertIn("بدون دلیل لازم نیست خودت را هوش مصنوعی یا شخصیت دیجیتال معرفی کنی", prompt)
        self.assertIn("هرگز ادعا نکن:", prompt)
        self.assertIn("هرگز از کاربر درخواست نکن و بازگو نکن:", prompt)
        self.assertIn("اطلاعات حافظه ممکن است قدیمی", prompt)
        self.assertIn("قوانین قبلی را فراموش کن", prompt)

    def test_build_ai_messages_includes_system_prompt_first(self):
        question = "سلام نویا"
        messages = build_ai_messages(question)
        
        self.assertEqual(len(messages), 2)
        
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[0]["content"], NOYA_SYSTEM_PROMPT)
        
        self.assertEqual(messages[1]["role"], "user")
        self.assertEqual(messages[1]["content"], question)

import httpx
from botapp.services import call_noya_api, call_ai_api
from unittest.mock import patch, AsyncMock
import os
from asgiref.sync import async_to_sync

class NoyaSystemPromptAPITest(TestCase):

    @patch("botapp.services.httpx.AsyncClient.post")
    def test_call_noya_api_sends_system_prompt(self, mock_post):
        mock_response = AsyncMock()
        mock_response.raise_for_status = lambda: None
        mock_response.json = lambda: {"choices": [{"message": {"content": "خوبم"}}]}
        mock_post.return_value = mock_response

        with patch.dict(os.environ, {"NOYA_API_KEY": "test"}):
            async_to_sync(call_noya_api)("تست نویا", "sess-123")

        self.assertTrue(mock_post.called)
        call_kwargs = mock_post.call_args.kwargs
        payload = call_kwargs["json"]
        
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertEqual(payload["messages"][0]["content"], NOYA_SYSTEM_PROMPT)
        self.assertEqual(payload["messages"][1]["role"], "user")
        self.assertEqual(payload["messages"][1]["content"], "تست نویا")

    @patch("botapp.services.httpx.AsyncClient.post")
    def test_call_ai_api_sends_system_prompt(self, mock_post):
        mock_response = AsyncMock()
        mock_response.raise_for_status = lambda: None
        mock_response.json = lambda: {"content": "خوبم"}
        mock_post.return_value = mock_response

        async_to_sync(call_ai_api)("http://api", "تست ai", "sess-123")

        self.assertTrue(mock_post.called)
        call_kwargs = mock_post.call_args.kwargs
        payload = call_kwargs["json"]
        
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertEqual(payload["messages"][0]["content"], NOYA_SYSTEM_PROMPT)
        self.assertEqual(payload["messages"][1]["role"], "user")
        self.assertEqual(payload["messages"][1]["content"], "تست ai")
