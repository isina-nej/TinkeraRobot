import random
import re
from aiogram import F, Router, types

router = Router()

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
