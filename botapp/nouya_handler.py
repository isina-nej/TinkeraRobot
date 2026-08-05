import random
import re

from aiogram import F, Router, types
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.types import InlineQueryResultArticle, InputTextMessageContent

from botapp.services import call_noya_api

router = Router()

# Persian-aware word boundary around «نویا». The previous pattern used a literal
# ``\\b`` string (backslash-b), so the mention handler never matched.
_NOYA_NAME_RE = re.compile(r"(?<![\wآ-ی])نویا(?![\wآ-ی])", re.IGNORECASE)
_AI_PREFIX_RE = re.compile(r"^(?:نویا|noya|nuya|noia|nuia)(?:\s|\u200c)", re.IGNORECASE)


def _guest_question(message: types.Message, bot_username: str = "") -> str:
    text = message.text or message.caption or ""
    if bot_username:
        text = re.sub(rf"@{re.escape(bot_username)}\b", "", text, flags=re.IGNORECASE)
    text = text.strip()
    replied = getattr(message, "reply_to_message", None)
    replied_text = getattr(replied, "text", None) or getattr(replied, "caption", None)
    if replied_text:
        text = f"[پیام مورد اشاره]\n{replied_text}\n\n[درخواست فعلی]\n{text}"
    return text.strip()


def _channel_question(text: str, bot_username: str = "") -> str | None:
    text = text.strip()
    mention = bool(
        bot_username
        and re.search(rf"@{re.escape(bot_username)}\b", text, flags=re.IGNORECASE)
    )
    name_call = bool(_NOYA_NAME_RE.search(text))
    if not (mention or name_call):
        return None
    if bot_username:
        text = re.sub(rf"@{re.escape(bot_username)}\b", "", text, flags=re.IGNORECASE)
    text = _NOYA_NAME_RE.sub("", text)
    return text.strip() or "به این پست پاسخ بده."


@router.channel_post(F.text)
async def channel_nouya_handler(message: types.Message):
    bot_user = await message.bot.get_me()
    question = _channel_question(message.text or "", bot_user.username or "")
    if question is None:
        return
    progress = await message.reply("در حال بررسی…")
    answer = await call_noya_api(
        question,
        session_id=f"telegram:channel:{message.chat.id}:{message.message_id}",
    )
    await progress.edit_text(answer)


@router.guest_message()
async def guest_nouya_handler(message: types.Message):
    if not message.guest_query_id:
        return
    bot_user = await message.bot.get_me()
    question = _guest_question(message, bot_user.username or "")
    if not question:
        question = "به پیام اشاره‌شده پاسخ بده."
    progress = InlineQueryResultArticle(
        id="noya-guest-progress",
        title="Noya",
        input_message_content=InputTextMessageContent(message_text="در حال بررسی…"),
    )
    sent = await message.answer_guest_query(result=progress)
    answer = await call_noya_api(
        question,
        session_id=f"telegram:guest:{message.chat.id}:{message.message_id}",
    )
    await message.bot.edit_message_text(
        inline_message_id=sent.inline_message_id,
        text=answer,
    )

RESPONSES = [
    "جانم؟ ✨",
    "بله؟ در خدمتم!",
    "کاری داشتید؟ 😊",
    "صدام کردید؟",
    "بفرما، من اینجام.",
]


@router.message(F.text.regexp(_NOYA_NAME_RE))
async def nouya_mention_handler(message: types.Message):
    """Ack bare «نویا» mentions; never compete with the main AI / agent path."""
    text = (message.text or "").strip()
    if text.startswith("/"):
        raise SkipHandler()

    bot_user = await message.bot.get_me()
    username = (bot_user.username or "").lower()
    if username and f"@{username}" in text.lower():
        raise SkipHandler()

    # Prefix + question (or reply-to-bot) belongs to handle_text_message / agent.
    if _AI_PREFIX_RE.match(text):
        raise SkipHandler()
    replied = getattr(message, "reply_to_message", None)
    if replied and getattr(replied, "from_user", None) and replied.from_user.id == bot_user.id:
        raise SkipHandler()

    await message.reply(random.choice(RESPONSES))
