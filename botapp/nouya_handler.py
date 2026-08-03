import random
import re

from aiogram import F, Router, types
from aiogram.types import InlineQueryResultArticle, InputTextMessageContent

from botapp.services import call_noya_api

router = Router()


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
    name_call = bool(re.search(r"(?<![\wآ-ی])نویا(?![\wآ-ی])", text, flags=re.IGNORECASE))
    if not (mention or name_call):
        return None
    if bot_username:
        text = re.sub(rf"@{re.escape(bot_username)}\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<![\wآ-ی])نویا(?![\wآ-ی])", "", text, flags=re.IGNORECASE)
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


@router.message(F.text.regexp(r"\\bنویا\\b", flags=re.IGNORECASE))
async def nouya_mention_handler(message: types.Message):
    # Avoid triggering on commands or mentions of the bot itself
    if message.text.startswith("/") or f"@{message.bot.id}" in message.text:
        return

    # Check if the bot is mentioned by its username
    bot_user = await message.bot.get_me()
    if bot_user.username and f"@{bot_user.username}" in message.text.lower():
        return

    await message.reply(random.choice(RESPONSES))
