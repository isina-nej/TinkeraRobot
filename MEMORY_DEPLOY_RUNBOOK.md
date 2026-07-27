# Memory System Deployment Runbook

این مستند راهنمای استقرار و بررسی سلامت سیستم حافظه ربات در محیط Staging و Production است.

## ۱. پیکربندی (Environment Variables)

برای استقرار اولیه (Staging/Rollout محافظه‌کارانه)، مقادیر زیر را در فایل `.env` سرور قرار دهید:

```env
# فعال‌سازی قابلیت‌های حافظه به صورت مرحله‌ای
MEMORY_RETRIEVAL_ENABLED=true
MEMORY_INGESTION_ENABLED=false
MEMORY_EXTRACTION_ENABLED=false
MEMORY_USER_COMMANDS_ENABLED=true
MEMORY_FAIL_OPEN=true

# زمان نگهداری حافظه‌ها (TTL)
SHORT_TERM_TTL_HOURS=24
MEDIUM_TERM_TTL_DAYS=14
LONG_TERM_TTL_DAYS=60

# محدودیت‌های پردازشی
MEMORY_MAX_CONTEXT_TOKENS=600

# لاگ تاخیر اجرا (Latency Instrumentation) - در صورت نیاز برای دیباگ فعال کنید
MEMORY_LATENCY_LOGGING_ENABLED=false
```

### برنامه فعال‌سازی مرحله‌ای (Rollout Plan)

**مرحله A (فعلی در Staging):** 
فقط بازیابی (`retrieval`) و دستورات کاربر (`commands`) روشن باشند. ثبت حافظه جدید خاموش است.

**مرحله B:**
پس از پایداری مرحله A، `MEMORY_INGESTION_ENABLED=true` و `MEMORY_EXTRACTION_ENABLED=true` را تنظیم کرده و ربات را ری‌استارت کنید.

---

## ۲. عملیات Migration و پشتیبان‌گیری

پیش از اجرای Migration روی سرور، پشتیبان‌گیری از دیتابیس ضروری است.

**بکاپ‌گیری از SQLite:**
```bash
cp db.sqlite3 backups/db.sqlite3.before-memory-deploy-$(date +%Y%m%d%H%M%S)
```

**بررسی Migration‌ها:**
```bash
python manage.py showmigrations botapp
python manage.py makemigrations --check
python manage.py migrate --plan
```

**اعمال Migration‌ها:**
```bash
python manage.py migrate
```

پس از اجرای این دستور، Migration‌های زیر باید به عنوان اعمال‌شده (X) ثبت شوند:
* `0017_telegramuser_welcomed_at`
* `0018_harden_bot_start_gate`
* `0019_memory_core`
* `0020_memory_scope_privacy`

---

## ۳. تست پیش از اجرا (Pre-flight Checks)

پیش از روشن کردن کامل ربات در محیط جدید، این دستورات باید خطایی برنگردانند:

```bash
python manage.py check
python -m compileall botapp config
python manage.py test botapp.test_memory botapp.test_memory_integration botapp.test_memory_admin
```

---

## ۴. بررسی سلامت (Smoke Test)

بدون نیاز به ارسال پیام در تلگرام یا تماس با AI API، اسکریپت تست سلامت را اجرا کنید:

```bash
python manage.py memory_smoke_test
```
خروجی باید `All smoke tests passed successfully!` باشد و در نهایت پیغام `Cleanup complete.` را نمایش دهد.

---

## ۵. زمان‌بندی حذف داده‌های منقضی‌شده (Lifecycle Scheduling)

برای پاک‌سازی حافظه‌های موقت که مهلت آنها (TTL) تمام شده، دستور زیر باید اجرا شود. 
نمونه Cron job پیشنهادی (یک‌بار در روز یا هر چند ساعت):

```cron
0 * * * * cd /path/to/project && .venv/bin/python manage.py process_memory_lifecycle >> /path/to/logs/memory_lifecycle.log 2>&1
```

---

## ۶. مسیر بازگشت (Rollback Plan)

در صورت بروز مشکل حاد در سیستم حافظه، مراحل زیر را طی کنید:

**اقدام فوری (خاموش کردن حافظه بدون تغییر کد):**
در فایل `.env` مقادیر زیر را قرار دهید و سرویس را ری‌استارت کنید:
```env
MEMORY_RETRIEVAL_ENABLED=false
MEMORY_INGESTION_ENABLED=false
MEMORY_EXTRACTION_ENABLED=false
MEMORY_USER_COMMANDS_ENABLED=false
```
(مقدار `MEMORY_FAIL_OPEN` را همچنان `true` نگه دارید تا خطاهای احتمالی باعث قطع پاسخ ربات نشوند).

**بازگشت کد و دیتابیس (فقط در موارد بحرانی):**
1. سرویس ربات را متوقف کنید.
2. با `git checkout <commit_hash>` به کامیت قبل از مرحله ۲ برگردید.
3. در صورت نیاز به بازگشت دیتابیس، فایل پشتیبان `.sqlite3` را جایگزین فایل فعلی کنید (هشدار: داده‌های جدید ثبت‌شده پس از بکاپ از بین می‌روند).
4. سرویس ربات را دوباره راه‌اندازی کنید.
