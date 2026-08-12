"""Clear Telegram managed-bot access restriction so anyone can /start the bot.

The native Telegram modal
«The owner of this bot has restricted access. You are not authorized…»
is enforced by Telegram itself (updates never reach our handlers). It is
controlled by the *manager* bot via ``setManagedBotAccessSettings``.

Usage (on the server):

    MANAGER_BOT_TOKEN=...:.venv/bin/python manage.py unrestrict_bot_access
    # or
    .venv/bin/python manage.py unrestrict_bot_access --manager-token '123:ABC' --bot-id 8880029922
"""

from __future__ import annotations

import asyncio
import os

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Set is_access_restricted=False for a managed bot (requires manager token)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--manager-token",
            default="",
            help="Manager bot token (default: MANAGER_BOT_TOKEN env).",
        )
        parser.add_argument(
            "--bot-id",
            type=int,
            default=0,
            help="Managed bot user id (default: id from BOT_TOKEN / getMe).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only print current access settings; do not change them.",
        )

    def handle(self, *args, **options):
        manager_token = (options["manager_token"] or os.getenv("MANAGER_BOT_TOKEN", "")).strip()
        if not manager_token:
            raise CommandError(
                "MANAGER_BOT_TOKEN (or --manager-token) is required. "
                "This must be the bot that *manages* Noya (see the bot profile line "
                "«Created and managed by @…»), not Noya's own token."
            )

        bot_id = int(options["bot_id"] or 0)
        dry_run = bool(options["dry_run"])

        async def run():
            nonlocal bot_id
            manager = Bot(manager_token)
            target_token = os.getenv("BOT_TOKEN", "").strip()
            target = Bot(target_token) if target_token else None
            try:
                mgr_me = await manager.get_me()
                self.stdout.write(
                    f"manager={mgr_me.id} @{mgr_me.username} "
                    f"can_manage_bots={mgr_me.can_manage_bots}"
                )
                if not bot_id:
                    if target is None:
                        raise CommandError("Pass --bot-id or set BOT_TOKEN to resolve the target.")
                    target_me = await target.get_me()
                    bot_id = int(target_me.id)
                    self.stdout.write(f"target={bot_id} @{target_me.username}")

                before = await manager.get_managed_bot_access_settings(user_id=bot_id)
                self.stdout.write(f"before={before.model_dump()}")
                if dry_run:
                    return
                if not before.is_access_restricted:
                    self.stdout.write(self.style.SUCCESS("Already public (is_access_restricted=False)."))
                    return
                ok = await manager.set_managed_bot_access_settings(
                    user_id=bot_id,
                    is_access_restricted=False,
                )
                after = await manager.get_managed_bot_access_settings(user_id=bot_id)
                self.stdout.write(self.style.SUCCESS(f"updated={ok} after={after.model_dump()}"))
            except TelegramAPIError as exc:
                raise CommandError(f"Telegram API error: {exc}") from exc
            finally:
                await manager.session.close()
                if target is not None:
                    await target.session.close()

        asyncio.run(run())
