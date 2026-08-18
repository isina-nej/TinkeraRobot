"""Live Tehran clock for Noya: Gregorian + Jalali, injected first."""

from __future__ import annotations

import re
from datetime import datetime

from django.utils import timezone

from botapp.template_renderer import gregorian_to_jalali

_CLOCK_RE = re.compile(
    r"(ساعت(?:\s+تهران)?\s*(?:چنده|چند است|چند)|"
    r"تاریخ(?:\s+امروز)?|"
    r"امروز\s+چند(?:مه|م)|"
    r"چه\s+روزی(?:ه| است)|"
    r"چه\s+تاریخی(?:ه| است)|"
    r"(?:time|date)\s+(?:in\s+)?tehran|"
    r"what(?:'s| is)\s+the\s+time)",
    re.IGNORECASE,
)
_NOT_CLOCK_RE = re.compile(r"خواب|مفید|از\s+ساعت|تا\s+ساعت|بیدار", re.IGNORECASE)

_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

_WEEKDAY_FA = (
    "دوشنبه",
    "سه‌شنبه",
    "چهارشنبه",
    "پنجشنبه",
    "جمعه",
    "شنبه",
    "یکشنبه",
)
_WEEKDAY_EN = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
_MONTH_FA = (
    "",
    "فروردین",
    "اردیبهشت",
    "خرداد",
    "تیر",
    "مرداد",
    "شهریور",
    "مهر",
    "آبان",
    "آذر",
    "دی",
    "بهمن",
    "اسفند",
)
_MONTH_EN = (
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def _fa_num(value: int, width: int = 0) -> str:
    text = str(value).zfill(width) if width else str(value)
    return text.translate(_FA_DIGITS)


def format_now_block(now: datetime | None = None) -> str:
    """Exact local (Asia/Tehran) clock in both calendars."""
    local = timezone.localtime(now or timezone.now())
    jy, jm, jd = gregorian_to_jalali(local.date())
    wd = local.weekday()
    return "\n".join(
        [
            "[NOW]",
            "این بلوک منبع حقیقت برای تاریخ و ساعت است. حدس نزن؛ از همین استفاده کن.",
            f"timezone={local.tzname() or 'Asia/Tehran'}",
            (
                f"gregorian={_WEEKDAY_EN[wd]} {local.day} {_MONTH_EN[local.month]} "
                f"{local.year}  {local.strftime('%H:%M:%S')}"
            ),
            (
                f"jalali={_WEEKDAY_FA[wd]} {_fa_num(jd)} {_MONTH_FA[jm]} {_fa_num(jy)}  "
                f"ساعت {_fa_num(local.hour, 2)}:{_fa_num(local.minute, 2)}:{_fa_num(local.second, 2)}"
            ),
            f"iso={local.isoformat(timespec='seconds')}",
            f"date_gregorian={local.strftime('%Y-%m-%d')}",
            f"date_jalali={jy:04d}-{jm:02d}-{jd:02d}",
            f"time_24h={local.strftime('%H:%M:%S')}",
            "[/NOW]",
        ]
    )


def _ask_text(text: str) -> str:
    raw = (text or "").strip()
    marker = "[درخواست فعلی]"
    if marker in raw:
        raw = raw.rsplit(marker, 1)[-1]
    return re.sub(r"\s+", " ", raw).strip()


def is_clock_question(text: str) -> bool:
    ask = _ask_text(text)
    if not ask or _NOT_CLOCK_RE.search(ask):
        return False
    return bool(_CLOCK_RE.search(ask))


def format_clock_reply(now: datetime | None = None) -> str:
    """Human reply so clock questions never depend on the model."""
    local = timezone.localtime(now or timezone.now())
    jy, jm, jd = gregorian_to_jalali(local.date())
    wd = local.weekday()
    return (
        f"الان تهران {_WEEKDAY_FA[wd]} {_fa_num(jd)} {_MONTH_FA[jm]} {_fa_num(jy)}، "
        f"ساعت {_fa_num(local.hour, 2)}:{_fa_num(local.minute, 2)}.\n"
        f"{_WEEKDAY_EN[wd]} {local.day} {_MONTH_EN[local.month]} {local.year}, "
        f"{local.strftime('%H:%M')}."
    )
