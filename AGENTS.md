# AGENTS.md

TinkeraRobot is a Django 5.2 + aiogram 3 Telegram group-management bot. See `README.md`
(Persian) and `MEMORY_DEPLOY_RUNBOOK.md` for feature/deploy details.

## Cursor Cloud specific instructions

### Services in this repo

- Django web app — admin panel (`/admin/`), health check (`GET /health/`), and the
  moderation REST API (`/api/...`). Runnable with no external secrets.
- Telegram bot — `manage.py runbot` (aiogram long-polling). Requires a real BotFather
  token; see below.
- Moderation worker — `manage.py run_moderation_worker` executes scheduled/due moderation
  actions. Also requires a bot token, but only calls Telegram when there are due actions.

All commands use the project virtualenv, e.g. `.venv/bin/python manage.py <cmd>`.
Standard run/check/test commands are documented in `README.md` (§راه‌اندازی / §بررسی پروژه)
and `MEMORY_DEPLOY_RUNBOOK.md`.

### Non-obvious gotchas

- The committed `wheelhouse/` is stale and mismatched: it ships `python_telegram_bot`
  wheels but the code imports `aiogram` (see `requirements.txt`). Do NOT install from
  `wheelhouse/`; install from PyPI with `.venv/bin/pip install -r requirements.txt`
  (the update script already does this).
- Creating the venv needs the `python3.12-venv` system package (already installed in the
  environment snapshot).
- `.env` is optional in development: `config/settings.py` runs `load_dotenv()` but falls
  back to safe defaults, and with `DEBUG=true` the `django-insecure-` secret-key guard is
  skipped, so the web app boots without `.env`. A committed-out-of-tree `.env` (from
  `.env.example`) is used here to hold a dev secret key and config; it is gitignored.
- Running the actual Telegram bot (`runbot`) needs a valid `BOT_TOKEN` (or `BOT_TOKENS`)
  from BotFather; with a placeholder/empty value aiogram raises `TokenValidationError`.
  Provide the token as the `BOT_TOKEN` secret to exercise live Telegram polling. The
  moderation backend and REST API do not need it.
- IMPORTANT: the provided `BOT_TOKEN` secret belongs to the LIVE production bot
  (`@NuyaRobot`). Telegram allows only one `getUpdates` poller per token, so running
  `manage.py runbot` here raises `TelegramConflictError` ("terminated by other getUpdates
  request") and would steal updates from production. Do NOT run live long-polling against
  the production token. To validate the bot safely, either use `bot.get_me()` /
  non-polling Bot API calls, or use a SEPARATE test-bot token from BotFather. `runbot`
  reaching the polling loop (even with the conflict error) already confirms the token,
  dispatcher and handler wiring are valid.
- Moderation REST API auth: send header `X-API-Key: <key>` (create a key with
  `manage.py create_api_key <name> --username <user>`; the plaintext is shown only once and
  stored hashed) OR a logged-in staff session + CSRF token.
- Default DB is SQLite (`db.sqlite3`, gitignored); MySQL is optional via the `DB_*` env vars.
- The test suite (`manage.py test`) logs expected AI-API failure tracebacks for the
  fail-open paths — those are not test failures; watch the final `OK` / ran-count line.
