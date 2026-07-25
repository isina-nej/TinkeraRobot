from datetime import date
from html import escape

from django.utils import timezone


# Gregorian to Solar Hijri conversion; adapted from the public arithmetic algorithm.
def gregorian_to_jalali(value: date) -> tuple[int, int, int]:
    gy, gm, gd = value.year, value.month, value.day
    g_days = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        355666
        + 365 * gy
        + (gy2 + 3) // 4
        - (gy2 + 99) // 100
        + (gy2 + 399) // 400
        + gd
        + g_days[gm - 1]
    )
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return jy, jm, jd


def render_member_template(template, user, title, now=None):
    now = timezone.localtime(now or timezone.now())
    first_name = escape(user.first_name or user.full_name or "کاربر")
    mention = f'<a href="tg://user?id={user.id}">{first_name}</a>'
    jy, jm, jd = gregorian_to_jalali(now.date())
    replacements = {
        "#name": mention,
        "#title": escape(title or "گروه"),
        "#time": now.strftime("%H:%M:%S"),
        "#date": now.strftime("%Y/%m/%d"),
        "#datesh": f"{jy:04d}/{jm:02d}/{jd:02d}",
        # Backward compatibility.
        "{mention}": mention,
        "{name}": first_name,
        "{group}": escape(title or "گروه"),
    }
    result = template
    # Replace longer tokens first (#datesh before #date).
    for token in sorted(replacements, key=len, reverse=True):
        result = result.replace(token, replacements[token])
    return result
