from types import SimpleNamespace

from django.test import SimpleTestCase

from botapp.telegram_rich import extract_message_body, rich_plain_text


def _paragraph(text):
    return SimpleNamespace(type="paragraph", text=text)


def _bold(inner):
    return SimpleNamespace(type="bold", text=inner)


def _rich_message(*blocks):
    return SimpleNamespace(blocks=list(blocks), is_rtl=True)


class TelegramRichExtractionTest(SimpleTestCase):
    def test_plain_text_preferred(self):
        msg = SimpleNamespace(text=" hello ", caption="cap", rich_message=_rich_message(_paragraph("rich")))
        self.assertEqual(extract_message_body(msg), "hello")

    def test_caption_when_no_text(self):
        msg = SimpleNamespace(text=None, caption="  عکس  ", rich_message=None)
        self.assertEqual(extract_message_body(msg), "عکس")

    def test_rich_message_when_text_empty(self):
        rich = _rich_message(
            SimpleNamespace(type="heading", text="سلام", size=1),
            _paragraph([_bold("سینا"), " جان، من اینجام"]),
        )
        msg = SimpleNamespace(text="", caption=None, rich_message=rich)
        body = extract_message_body(msg)
        self.assertIn("سلام", body)
        self.assertIn("سینا", body)
        self.assertIn("جان، من اینجام", body)

    def test_nested_list_and_details(self):
        item = SimpleNamespace(
            label="1.",
            blocks=[_paragraph("اول")],
            has_checkbox=False,
        )
        details = SimpleNamespace(
            type="details",
            summary="بیشتر",
            blocks=[_paragraph("جزئیات")],
            is_open=False,
        )
        rich = _rich_message(
            SimpleNamespace(type="list", items=[item]),
            details,
        )
        body = rich_plain_text(rich)
        self.assertIn("اول", body)
        self.assertIn("بیشتر", body)
        self.assertIn("جزئیات", body)

    def test_custom_emoji_and_math(self):
        para = _paragraph(
            [
                SimpleNamespace(type="custom_emoji", custom_emoji_id="1", alternative_text="🫡"),
                " ",
                SimpleNamespace(type="math", expression="a+b"),
            ]
        )
        body = rich_plain_text(_rich_message(para))
        self.assertIn("🫡", body)
        self.assertIn("a+b", body)

    def test_empty_rich_is_empty_body(self):
        msg = SimpleNamespace(text="", caption="", rich_message=_rich_message())
        self.assertEqual(extract_message_body(msg), "")
