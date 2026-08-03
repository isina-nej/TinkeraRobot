# TinkeraRobot

ربات مدیریت گروه تلگرام با Django و aiogram؛ شامل moderation قابل تنظیم برای هر گروه، سهمیه هوش مصنوعی و پنل Django.

قابلیت‌های مدیریت شامل ضدفلود و تشخیص تکرار پیام، ضدلینک با دامنه‌های مجاز، ضدفوروارد، فیلتر کلمات، اخطار با انقضا و mute خودکار، mute/ban/unban دستی، قوانین، خوش‌آمد/خداحافظی، لاگ اقدامات و retention جداگانه برای هر گروه است.

نکته: ربات باید در گروه دسترسی‌های `Delete messages` و `Restrict members` داشته باشد. برای دریافت رویداد ورود/خروج اعضا، `ChatMemberUpdated` نیز باید در تنظیمات polling دریافت شود.

دستورات اصلی داخل گروه:

`/rules` نمایش قوانین، `/setrules متن` تنظیم قوانین، `/warn` در پاسخ به پیام کاربر، `/warns` نمایش اخطارها، `/mute`، `/unmute`، `/ban`، `/unban`، `/setwelcome متن` تنظیم خوش‌آمد، `/filter add|del کلمه` مدیریت کلمات ممنوع، `/allowdomain add|del example.com` مدیریت دامنه‌های مجاز، `/id` نمایش شناسه، و `/prompt سؤال` برای استفاده از AI.

فرمان‌های مجازات بدون اسلش هم کار می‌کنند. در پاسخ به پیام کاربر می‌توان نوشت: `warn`، `اخطار`، `هشدار`، `mute`، `میوت`، `سکوت`، `unmute`، `آنمیوت`، `ban`، `بن`، `مسدود`، `unban`، `آنبن`، `warns` یا `اخطارها`. ادمین‌ها و خود ربات در برابر warn، mute و ban محافظت می‌شوند.

## عملیات دائمی و زمان‌بندی‌شده

دستورهای `mute` و `ban` چهار حالت دارند. بدون عدد، عملیات فوری و دائمی است. با یک عدد، فوری و زمان‌دار است. با دو عدد، عدد اول تأخیر شروع و عدد دوم مدت عملیات است. واژه `دائمی` به‌جای مدت یعنی عملیات بعد از تأخیر شروع شود و پایان خودکار نداشته باشد. همه اعداد بر حسب دقیقه هستند.

```text
mute                    # سکوت فوری و دائمی
mute 30 spam            # سکوت فوری برای ۳۰ دقیقه
mute 60 دائمی spam      # شروع سکوت دائمی بعد از ۶۰ دقیقه
mute 60 30 spam         # شروع بعد از ۶۰ دقیقه، آزادی بعد از ۳۰ دقیقه
ban                     # بن فوری و دائمی
ban 30 abuse            # بن فوری برای ۳۰ دقیقه
ban 60 دائمی abuse      # بن دائمی با یک ساعت تأخیر
ban 60 30 abuse         # یک ساعت بعد بن؛ ۳۰ دقیقه بعد آزادسازی
```

قفل گروه هدف کاربر ندارد:

```text
/lock                   # قفل فوری و دائمی
/lock 30                # قفل فوری برای ۳۰ دقیقه
/lock 60 دائمی          # قفل دائمی با یک ساعت تأخیر
/lock 60 30             # یک ساعت بعد قفل؛ ۳۰ دقیقه بعد باز
/unlock                 # باز کردن فوری
```

معادل بدون اسلش فارسی `قفل`، `قفل‌گروه`، `باز`، `بازکردن` و `رفع‌قفل` نیز پشتیبانی می‌شود. باز کردن گروه، permissionهای قبل از قفل را بازیابی می‌کند.

سیاست سقف اخطار فقط یک مجازات از نوع `mute` یا `ban` دارد و سه مقدار مستقل می‌گیرد: `max_warnings_action`، `max_warnings_action_delay_minutes` و `max_warnings_action_duration_minutes`. مقدار duration خالی یعنی دائمی. این تنظیمات از پنل Django یا API قابل تغییرند.

## Backend و API

منطق زمان‌بندی در `botapp/moderation.py` مستقل از تلگرام است. اتصال Telegram در `botapp/telegram_gateway.py` و `botapp/telegram_moderation.py` قرار دارد؛ سایت آینده می‌تواند همان backend را از API استفاده کند.

مسیرهای API:

```text
GET|POST /api/groups/<chat_id>/settings/
POST     /api/moderation/actions/
GET      /api/moderation/actions/<id>/
POST     /api/moderation/actions/<id>/cancel/
```

احراز هویت با session کاربر staff و CSRF یا هدر `X-API-Key` انجام می‌شود. کلید API به‌صورت hash ذخیره می‌شود و متن آن فقط هنگام ساخت نمایش داده می‌شود:

```bash
.venv/bin/python manage.py create_api_key dashboard --username admin
```

ایجاد action از API نمونه:

```json
{
  "chat_id": -100123456,
  "action": "ban",
  "target_user_id": 42,
  "delay_minutes": 60,
  "duration_minutes": 30,
  "reason": "spam"
}
```

هدر `Idempotency-Key` از ثبت تکراری یک درخواست جلوگیری می‌کند. actionهای معتبر: `lock`، `unlock`، `mute`، `unmute`، `ban` و `unban`.

متن‌های قابل تنظیم در `GroupSettings.message_templates` ذخیره می‌شوند. کلیدهای فعلی: `warn`، `warning_ceiling`، `lock`، `unlock`، `mute`، `unmute`، `ban`، `unban`، `scheduled` و `admin_protected`. placeholderها بسته به پیام شامل `{target}`، `{count}`، `{max_warnings}`، `{action}` و `{execute_at}` هستند.

## پیام خوش‌آمد

قالب پیش‌فرض:

```text
سلام #name عزیز به گروه #title خوش آمدی 🌷 ✅ ساعت: ( #time ) ✅ تاریخ: ( #date )
```

قالب را می‌توان با `/setwelcome متن` تغییر داد. placeholderها:

```text
#name    نام قابل کلیک کاربر
#title   نام گروه
#time    ساعت محلی دقیق
#date    تاریخ میلادی همان روز
#datesh  تاریخ شمسی همان روز
```

## قفل روزانه در ساعت مشخص

برنامه‌های روزانه طبق `TIME_ZONE` پروژه اجرا می‌شوند و به worker نیاز دارند:

```text
/lockat 23:30       # هر روز ساعت ۲۳:۳۰ گروه قفل شود
/unlockat 08:00     # هر روز ساعت ۰۸:۰۰ گروه باز شود
/lockat off         # حذف برنامه قفل
/unlockat off       # حذف برنامه بازکردن
```

## حذف پیام

```text
حذف                # در پاسخ به یک پیام؛ پیام هدف و فرمان حذف می‌شوند
delete / del        # معادل انگلیسی
حذف 100            # حذف ۱۰۰ پیام قبل به‌همراه فرمان؛ سقف امن ۱۰۰۰
حذف تا اینجا       # در پاسخ به پیام مقصد؛ از آن پیام تا فرمان حذف می‌شود
سکوت حذف           # سکوت کاربر و حذف پیام هدف، فرمان و پاسخ ربات
بن حذف             # بن کاربر و حذف پیام‌ها
اخطار حذف          # اخطار و حذف پیام‌ها
```

محدودیت Telegram همچنان اعمال می‌شود: پیام‌های بسیار قدیمی یا برخی پیام‌های سرویس ممکن است قابل حذف نباشند. ربات باید دسترسی `Delete messages` داشته باشد.

worker عملیات موعددار باید کنار bot اجرا شود:

```bash
.venv/bin/python manage.py run_moderation_worker
```

برای اجرای یک batch و خروج:

```bash
.venv/bin/python manage.py run_moderation_worker --once
```


با ارسال واژه «پنل» توسط ادمین، پنل تنظیمات درون گروه باز می‌شود.

برای پاک‌سازی لاگ‌های قدیمی طبق retention هر گروه:

```bash
.venv/bin/python manage.py purge_moderation_logs
```

برای اجرای دوره‌ای این دستور از cron یا systemd timer استفاده کنید.

---

## راه‌اندازی

Python 3.11 یا جدیدتر لازم است.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
# مقادیر .env را تنظیم کنید.
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runbot
```

برای اجرای وب‌اپ مدیریتی و health check:

```bash
.venv/bin/python manage.py runserver
```

مسیر سلامت سرویس `GET /health/` است و پنل Django در `/admin/` قرار دارد.

## بررسی پروژه

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py test
```

## امنیت

فایل `.env`، دیتابیس، لاگ و PID در مخزن نگهداری نمی‌شوند. توکن‌های افشاشده را در BotFather لغو و جایگزین کنید. در محیط production باید `DEBUG=false` و `DJANGO_SECRET_KEY` و `ALLOWED_HOSTS` معتبر تنظیم شوند.
# TinkeraRobot

## ۶. راهنمای هوش مصنوعی و System Prompt

پرامپت سیستمی اصلی شخصیت «نویا» در مسیر زیر قرار دارد:
`botapp/ai/prompts.py`

- **نسخه پرامپت**: `NOYA_SYSTEM_PROMPT_VERSION = "v1"`
- **نحوه اتصال:** در فایل `botapp/services.py` از تابع `build_ai_messages` استفاده شده تا پرامپت دقیقاً در نقش `system` و قبل از متون کاربر و Context حافظه به `Payload` اضافه‌شود.
- **ویژگی‌ها:**
  - در یک Request فقط یک بار System Prompt ارسال می‌شود.
  - متن Prompt در دیتابیس (حافظه)، لاگ‌های عمومی یا متن پیام‌های فورواردشده ذخیره نمی‌شود.
  - با استفاده از فلگ متغیرمحیطی `NOYA_SYSTEM_PROMPT_ENABLED=false` می‌توان در زمان دیباگ یا رول‌بک آن را غیرفعال کرد.

## ۷. دستیار مدیریتی هوشمند (Agent)

ادمین می‌تواند با زبان طبیعی فارسی به ربات دستور مدیریتی بدهد. این قابلیت به‌صورت افزودنی روی معماری فعلی ساخته شده و همه‌ی فرمان‌ها و رفتارهای قبلی دست‌نخورده‌اند.

### تریگرها

```text
/agent <دستور>
/adminai <دستور>
نویا، <دستور مدیریتی>
```

فرمان‌های قطعی موجود (mute، ban، حذف، قفل و…) و فرمان‌های بدون اسلش همان‌طور که بودند کار می‌کنند. تریگر «نویا،» فقط برای ادمین و فقط وقتی که یک Intent مدیریتی مطمئن تشخیص داده شود فعال می‌شود؛ در غیر این‌صورت پیام به گفت‌وگوی عادی نویا می‌رود و `/prompt` بدون تغییر باقی می‌ماند.

### جریان اجرا

`Trigger → Admin Verification → Deterministic Parser → (AI Structured Parser) → Schema Validation → Registry Lookup → App Permission → Bot Capability → Target Resolution → Risk → Confirmation → Existing-Service Execution → Audit → Persian Response`

- ابتدا یک Parser قطعی و کم‌هزینه فارسی اجرا می‌شود؛ فقط اگر نتیجه نداد و `AGENT_AI_ENABLED=true` باشد، درخواست برای مدل ارسال می‌شود.
- مدل AI فقط یک `AgentDecision` معتبر و allowlist‌شده تولید می‌کند؛ هرگز مستقیماً عملیات تلگرام یا دیتابیس انجام نمی‌دهد.
- عملیات state‌دار مدیریتی از همان Pipeline موجود (`queue_or_execute` → `ModerationAction`) استفاده می‌کنند.
- کاربر هدف فقط از Reply تعیین می‌شود؛ مدل اجازه‌ی ساختن `user_id` را ندارد.
- محتوای Reply/نقل‌قول به‌عنوان `<untrusted_message>` (داده، نه دستور) به مدل داده می‌شود.

### تأیید عملیات حساس

عملیات پرخطر (ban، mute، قفل، حذف، تغییر تنظیمات امنیتی) پیش از اجرا یک پیام تأیید با دکمه‌های «✅ تأیید / ❌ لغو» نمایش می‌دهند. فقط درخواست‌دهنده، در همان گروه، و تا قبل از انقضا (پیش‌فرض ۱۲۰ ثانیه) می‌تواند تأیید کند. Tool Registry منبع نهایی سطح ریسک است؛ اگر مدل ریسک کمتری اعلام کند، مقدار Registry اعمال می‌شود. Token تأیید فقط به‌صورت hash ذخیره می‌شود.

### آرشیو پیام (اختیاری)

با `MESSAGE_ARCHIVE_ENABLED=true` ربات پیام‌های دریافتی گروه را آرشیو می‌کند و حذف‌هایی را که خودش انجام می‌دهد ثبت می‌کند. مطابق محدودیت واقعی Telegram، حذف دستی کاربران در گروه‌های عادی برای ربات قابل مشاهده نیست و ربات چنین ادعایی نمی‌کند. پاک‌سازی دوره‌ای:

```bash
.venv/bin/python manage.py purge_message_snapshots
```

### متغیرهای محیطی

```text
AGENT_ENABLED=true
AGENT_AI_ENABLED=true
AGENT_MODEL=
AGENT_CONFIRMATION_TTL_SECONDS=120
AGENT_MIN_CONFIDENCE=0.80
AGENT_MAX_COMMAND_LENGTH=2000
MESSAGE_ARCHIVE_ENABLED=false
MESSAGE_ARCHIVE_RETENTION_DAYS=30
```

مدل‌های جدید `AgentConfirmation`، `AgentAuditLog` و `MessageSnapshot` در پنل Django قابل مشاهده‌اند. برای Rollback بدون تغییر کد کافی است `AGENT_ENABLED=false` تنظیم شود.

