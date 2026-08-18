import base64
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from asgiref.sync import async_to_sync
from django.test import SimpleTestCase, override_settings
from PIL import Image

from botapp.ai.prompts import build_ai_messages
from botapp.telegram_media import (
    collect_noya_images,
    image_bytes_from_sticker,
    normalize_image_bytes,
    to_data_url,
)


def _png_bytes(color=(255, 0, 0), size=(8, 8)) -> bytes:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _webp_bytes() -> bytes:
    img = Image.new("RGB", (16, 16), (0, 128, 255))
    buf = io.BytesIO()
    img.save(buf, format="WEBP")
    return buf.getvalue()


class TelegramMediaTest(SimpleTestCase):
    def test_normalize_image_bytes_returns_jpeg(self):
        mime, data = normalize_image_bytes(_png_bytes())
        self.assertEqual(mime, "image/jpeg")
        self.assertTrue(data.startswith(b"\xff\xd8"))
        with Image.open(io.BytesIO(data)) as img:
            self.assertEqual(img.format, "JPEG")

    def test_sticker_webp_converts_to_jpeg(self):
        bot = SimpleNamespace(
            get_file=AsyncMock(return_value=SimpleNamespace(file_path="stickers/x.webp")),
            download_file=AsyncMock(
                side_effect=lambda path, destination: destination.write(_webp_bytes())
            ),
        )
        sticker = SimpleNamespace(
            file_id="sticker-1",
            is_animated=False,
            is_video=False,
            thumbnail=None,
            thumb=None,
        )
        got = async_to_sync(image_bytes_from_sticker)(bot, sticker)
        self.assertIsNotNone(got)
        mime, data = got
        self.assertEqual(mime, "image/jpeg")
        self.assertTrue(data.startswith(b"\xff\xd8"))

    def test_animated_sticker_falls_back_to_thumbnail(self):
        webp = _webp_bytes()
        thumb_png = _png_bytes((10, 200, 10))

        async def download(path, destination):
            if "thumb" in path:
                destination.write(thumb_png)
            else:
                # fake undecodable animated payload
                destination.write(b"not-an-image")

        bot = SimpleNamespace(
            get_file=AsyncMock(
                side_effect=lambda file_id: SimpleNamespace(
                    file_path="stickers/thumb.webp" if file_id == "thumb-1" else "stickers/a.tgs"
                )
            ),
            download_file=AsyncMock(side_effect=download),
        )
        sticker = SimpleNamespace(
            file_id="anim-1",
            is_animated=True,
            is_video=False,
            thumbnail=SimpleNamespace(file_id="thumb-1"),
            thumb=None,
        )
        got = async_to_sync(image_bytes_from_sticker)(bot, sticker)
        self.assertIsNotNone(got)
        mime, data = got
        self.assertEqual(mime, "image/jpeg")

    def test_collect_from_message_and_reply(self):
        png = _png_bytes()

        async def download(path, destination):
            destination.write(png)

        bot = SimpleNamespace(
            get_file=AsyncMock(return_value=SimpleNamespace(file_path="photos/x.jpg")),
            download_file=AsyncMock(side_effect=download),
        )
        reply = SimpleNamespace(
            photo=[SimpleNamespace(file_id="p1", file_size=100, width=10, height=10)],
            sticker=None,
            document=None,
            reply_to_message=None,
        )
        message = SimpleNamespace(
            photo=None,
            sticker=SimpleNamespace(
                file_id="s1",
                is_animated=False,
                is_video=False,
                thumbnail=None,
                thumb=None,
            ),
            document=None,
            reply_to_message=reply,
        )
        # sticker path uses webp decode — feed webp for sticker file
        webp = _webp_bytes()

        async def download2(path, destination):
            destination.write(webp if "stickers" in path or path.endswith(".webp") else png)

        bot.get_file = AsyncMock(
            side_effect=lambda file_id: SimpleNamespace(
                file_path="stickers/s.webp" if file_id == "s1" else "photos/p.jpg"
            )
        )
        bot.download_file = AsyncMock(side_effect=download2)
        images = async_to_sync(collect_noya_images)(bot, message)
        self.assertGreaterEqual(len(images), 1)
        self.assertTrue(all(i["mime"] == "image/jpeg" for i in images))

    @override_settings(NOYA_SYSTEM_PROMPT_ENABLED=False)
    def test_build_ai_messages_multimodal(self):
        mime, data = normalize_image_bytes(_png_bytes())
        messages = build_ai_messages(
            "این چیه؟",
            images=[{"mime": mime, "data": data}],
        )
        content = messages[1]["content"]
        self.assertIsInstance(content, list)
        self.assertEqual(content[0]["type"], "text")
        self.assertEqual(content[1]["type"], "image_url")
        url = content[1]["image_url"]["url"]
        self.assertTrue(url.startswith("data:image/jpeg;base64,"))
        raw = base64.b64decode(url.split(",", 1)[1])
        self.assertTrue(raw.startswith(b"\xff\xd8"))
        self.assertEqual(to_data_url(mime, data), url)
