"""Run the bot against an INDEPENDENT test bot token.

This command exists so live testing never touches the production bot. It uses
``TEST_BOT_TOKEN`` exclusively and, if that variable is missing, exits with a
clear error. It NEVER falls back to the production ``BOT_TOKEN``.

Optional companion env vars (used only for convenience / documentation):
    TEST_GROUP_ID        a private throwaway supergroup for manual testing
    TEST_ADMIN_USER_ID   Telegram user id treated as a super-admin in the test bot
"""

import asyncio
import os
import socket

from aiogram import Bot
from django.core.management.base import BaseCommand, CommandError

from botapp.bot_start_gate import notice_cleanup_loop
from botapp.forced_membership_handlers import configure_super_admins
from botapp.management.commands.runbot import build_dispatcher, parse_bot_tokens


class Command(BaseCommand):
    help = "Run the bot with TEST_BOT_TOKEN only (never falls back to production BOT_TOKEN)."

    def handle(self, *args, **options):
        token = os.getenv("TEST_BOT_TOKEN", "").strip()
        if not token:
            raise CommandError(
                "TEST_BOT_TOKEN is not set. run_testbot never falls back to the "
                "production BOT_TOKEN. Create a SEPARATE bot in BotFather and set "
                "TEST_BOT_TOKEN to its token before running live tests."
            )

        # Defense-in-depth: refuse to poll the PRODUCTION bot even under the test
        # command. TEST_BOT_TOKEN must belong to a separate BotFather bot.
        production_tokens = set(
            parse_bot_tokens(os.getenv("BOT_TOKENS", ""), os.getenv("BOT_TOKEN", ""))
        )
        if token in production_tokens:
            raise CommandError(
                "TEST_BOT_TOKEN equals the production BOT_TOKEN/BOT_TOKENS. Refusing "
                "to poll the production bot. Create a SEPARATE bot in BotFather and "
                "use its token for TEST_BOT_TOKEN."
            )

        test_admin = os.getenv("TEST_ADMIN_USER_ID", "").strip()
        admin_ids = frozenset({int(test_admin)}) if test_admin.lstrip("-").isdigit() else frozenset()

        # Match runbot's IPv4-only DNS behaviour in constrained environments.
        original_getaddrinfo = socket.getaddrinfo

        def _ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
            return original_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

        socket.getaddrinfo = _ipv4_only

        async def run():
            bot = Bot(token=token)
            try:
                me = await bot.get_me()
                configure_super_admins(admin_ids)
                dispatcher = build_dispatcher(bot_usernames=(me.username or "",))
                cleanup = asyncio.create_task(notice_cleanup_loop(bot))
                self.stdout.write(f"Test bot running: @{me.username} (id={me.id})")
                if admin_ids:
                    self.stdout.write(f"Test super-admins: {sorted(admin_ids)}")
                try:
                    await dispatcher.start_polling(bot, close_bot_session=False)
                finally:
                    cleanup.cancel()
                    await asyncio.gather(cleanup, return_exceptions=True)
            finally:
                await bot.session.close()

        try:
            asyncio.run(run())
        finally:
            socket.getaddrinfo = original_getaddrinfo
