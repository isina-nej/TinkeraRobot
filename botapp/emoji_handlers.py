from aiogram import Router, types, F
from aiogram.filters import Command
from asgiref.sync import sync_to_async
from django.db import IntegrityError

from .models import CustomEmoji, GroupSettings
from .telegram_utils import aget_group_settings, aget_super_admin_ids, user_is_admin_in_group

router = Router()


@router.message(Command("add_emoji"))
async def add_emoji_command(message: types.Message):
    if message.from_user.id not in await aget_super_admin_ids():
        return

    if not message.reply_to_message or not message.reply_to_message.text:
        await message.reply("لطفا این دستور را در پاسخ به یک پیام که فقط شامل ایموجی سفارشی است ارسال کنید.")
        return

    args = message.text.split()
    if len(args) != 2:
        await message.reply("استفاده: /add_emoji <name>")
        return

    emoji_name = args[1]
    original_message = message.reply_to_message

    if not original_message.entities or len(original_message.entities) != 1:
        await message.reply("پیام مورد نظر باید فقط شامل یک ایموجی سفارشی باشد.")
        return

    entity = original_message.entities[0]
    if entity.type != types.MessageEntityType.CUSTOM_EMOJI:
        await message.reply("نوع ایموجی پشتیبانی نمی‌شود.")
        return

    custom_emoji_id = entity.custom_emoji_id

    try:
        await sync_to_async(CustomEmoji.objects.create)(
            name=emoji_name, custom_emoji_id=custom_emoji_id
        )
        await message.reply(f"ایموجی '{emoji_name}' با موفقیت اضافه شد.")
    except IntegrityError:
        await message.reply("یک ایموجی با این نام یا شناسه از قبل وجود دارد.")
    except Exception as e:
        await message.reply(f"خطایی رخ داد: {e}")


@router.message(Command("set_welcome_emoji"))
async def set_welcome_emoji_command(message: types.Message):
    if not await user_is_admin_in_group(message.chat, message.from_user.id):
        return

    args = message.text.split()
    if len(args) != 2:
        await message.reply("استفاده: /set_welcome_emoji <emoji_name>")
        return

    emoji_name = args[1]
    group_settings = await aget_group_settings(message.chat.id)
    if not group_settings:
        return

    try:
        emoji = await sync_to_async(CustomEmoji.objects.get)(name=emoji_name)
        group_settings.welcome_emoji = emoji
        await sync_to_async(group_settings.save)()
        await message.reply(f"ایموجی خوش آمدگویی گروه به '{emoji_name}' تغییر کرد.")
    except CustomEmoji.DoesNotExist:
        await message.reply(f"ایموجی با نام '{emoji_name}' پیدا نشد.")
    except Exception as e:
        await message.reply(f"خطایی رخ داد: {e}")

