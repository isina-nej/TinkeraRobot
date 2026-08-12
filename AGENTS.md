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
  stored hashed) OR a logged-in staff session + CSRF token. Optional
  `StaffAPIKey.allowed_chat_ids` (JSON list) scopes a key to specific Telegram
  `chat_id`s; empty list keeps legacy unrestricted behavior.
- When `MESSAGE_ARCHIVE_ENABLED=true`, schedule `manage.py purge_message_snapshots`
  via cron/systemd — there is no in-process scheduler for it (see README).
- Stale moderation worker rows: `mute`/`ban`/`lock` stuck in `processing` are
  failed (not auto-retried) to avoid double Telegram side effects; release
  actions (`unmute`/`unban`/`unlock`) are requeued.
- Default DB is SQLite (`db.sqlite3`, gitignored); MySQL is optional via the `DB_*` env vars.
- The test suite (`manage.py test`) logs expected AI-API failure tracebacks for the
  fail-open paths — those are not test failures; watch the final `OK` / ran-count line.
- Admin deep analysis uses `harness.investigate` (ReAct): read-only tools + optional
  sandboxed Python (`botapp/agent/sandbox.py`). Phrases like «بررسی کامل» /
  «تحلیل عمیق» route there; plain «تحلیل کن» still uses `analytics.generate_briefing`.
  Toggle with `AGENT_HARNESS_ENABLED` / `AGENT_HARNESS_AI_ENABLED` (deterministic
  read-tool pass when AI planner is off).
- Group Noya chat context (`botapp/noya_context.py`): when someone addresses Noya
  (name / @mention / reply), the model payload includes the replied message, one
  parent reply when Telegram provides it, and a short in-memory recent-chat buffer
  filled by `ArchiveMiddleware` (works even if `MESSAGE_ARCHIVE_ENABLED=false`).
  Telegram cannot backfill older history the bot never received.
- Noya vision: photos/stickers are downloaded via Bot API, stickers normalized to
  JPEG (`botapp/telegram_media.py`, needs Pillow), and sent as OpenAI-style
  `image_url` data URLs. Optional `NOYA_VISION_MODEL` overrides `NOYA_MODEL` only
  when images are attached. On the current 9router stack, `NoyaBest`, `fast`,
  `gemini/*`, `sina-pro`, and several `gc/gemini-*` aliases accept vision.
- Bot-to-bot: Telegram does **not** deliver other bots' group messages unless
  **Bot-to-Bot Communication Mode** is enabled in @BotFather (Mini App → Bot
  Settings). This is separate from **Guest Mode** (`supports_guest_queries` in
  `getMe`). Code answers other bots on reply/@mention/«نویا» with self-skip +
  rate limits (`botapp/noya_bot_chat.py`). Incoming peer updates log as
  `noya_peer_update` in `group-bot` journal — if Mira replies and that line is
  missing, Telegram never delivered the update. For broader receive, disable
  Group Privacy (`/setprivacy` → Disable; re-add bot to group) and keep Noya admin.
- Streaming bot edits: Mira-like bots often send `text=''` then grow the body via
  `edited_message`. `botapp/noya_edits.py` (`NoyaEditCoordinator`) debounces the
  stream (settle ~1.5s, max wait ~15s) and answers **once**. Watch journal lines
  `noya_edit_session_open` / `noya_edit_tracked` / `noya_edit_dispatch`.
- Mira (and some other AI bots) send Telegram **Rich Messages**
  (`content_type=RICH_MESSAGE`) with empty `text`/`caption`. Readable content is
  in `message.rich_message` — flatten via `botapp/telegram_rich.py`
  (`extract_message_body`). Peer logs with `rich_message` + `rich_plain_len=N`
  mean extraction worked; `RICH_MESSAGE` with `rich_plain_len` missing/0 means
  the payload is still empty/unparsed.
- Native Telegram modal «The owner of this bot has restricted access…» on
  `/start` means **managed-bot access restriction**
  (`BotAccessSettings.is_access_restricted`). The update never reaches Django.
  Noya’s own token cannot clear it (`BOT_ACCESS_FORBIDDEN`). Fix with the
  *manager* bot token: `manage.py unrestrict_bot_access` (needs
  `MANAGER_BOT_TOKEN`), or disable Access restriction in the manager /
  BotFather UI. Check the bot profile for «Created and managed by @…».
