import logging
import os
import re
from collections import defaultdict, deque
from datetime import timedelta
from urllib.parse import urlsplit

import httpx
from asgiref.sync import sync_to_async
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from botapp.models import GroupQuota, GroupSettings, ModerationLog, Warning

logger = logging.getLogger(__name__)
_flood_events = defaultdict(deque)
_duplicate_events = defaultdict(deque)


def normalize_text(text: str) -> str:
    return " ".join(text.casefold().split())


def contains_blocked_word(text: str, blocked_words: list[str]) -> bool:
    normalized = normalize_text(text)
    return any(word.strip().casefold() in normalized for word in blocked_words if word.strip())


def extract_urls(text: str) -> list[str]:
    return re.findall(r"(?i)(?:https?://|www\.)[^\s<>()]+", text)


def is_allowed_url(url: str, allowed_domains: list[str]) -> bool:
    normalized_url = url if "://" in url else f"https://{url}"
    host = (urlsplit(normalized_url).hostname or "").lower().removeprefix("www.")
    for domain in allowed_domains:
        allowed = domain.strip().lower().removeprefix("www.")
        if allowed and (host == allowed or host.endswith(f".{allowed}")):
            return True
    return False


def is_flooding(chat_id: int, user_id: int, limit: int, window_seconds: int, now=None) -> bool:
    now = now or timezone.now()
    events = _flood_events[(chat_id, user_id)]
    cutoff = now.timestamp() - max(window_seconds, 1)
    while events and events[0] <= cutoff:
        events.popleft()
    events.append(now.timestamp())
    return len(events) > max(limit, 1)


def is_duplicate_message(chat_id: int, user_id: int, text: str, limit: int, window_seconds: int, now=None) -> bool:
    now = now or timezone.now()
    events = _duplicate_events[(chat_id, user_id)]
    cutoff = now.timestamp() - max(window_seconds, 1)
    while events and events[0][0] <= cutoff:
        events.popleft()
    normalized = normalize_text(text)
    events.append((now.timestamp(), normalized))
    return sum(value == normalized for _, value in events) >= max(limit, 2)


@sync_to_async(thread_sensitive=True)
def get_or_create_moderation_settings(chat_id: int, chat_title: str = "") -> GroupSettings:
    group, _ = GroupSettings.objects.get_or_create(
        chat_id=chat_id,
        defaults={"chat_title": chat_title},
    )
    if chat_title and group.chat_title != chat_title:
        group.chat_title = chat_title
        group.save(update_fields=["chat_title", "updated_at"])
    return group


@sync_to_async(thread_sensitive=True)
def create_moderation_log(
    group_id,
    action,
    target_user_id=None,
    target_name="",
    actor_user_id=None,
    actor_name="",
    reason="",
    duration_minutes=None,
):
    return ModerationLog.objects.create(
        group_id=group_id,
        target_user_id=target_user_id,
        target_name=target_name,
        actor_user_id=actor_user_id,
        actor_name=actor_name,
        action=action,
        reason=reason,
        duration_minutes=duration_minutes,
    )


@sync_to_async(thread_sensitive=True)
def add_warning(
    group_id,
    user_id,
    user_name,
    issued_by_user_id,
    issued_by_name,
    reason,
    expiry_days,
):
    now = timezone.now()
    Warning.objects.filter(
        group_id=group_id,
        user_id=user_id,
        revoked_at__isnull=True,
        expires_at__lt=now,
    ).update(revoked_at=now)
    Warning.objects.create(
        group_id=group_id,
        user_id=user_id,
        user_name=user_name,
        issued_by_user_id=issued_by_user_id,
        issued_by_name=issued_by_name,
        reason=reason,
        expires_at=now + timedelta(days=max(expiry_days, 1)),
    )
    return Warning.objects.filter(
        group_id=group_id,
        user_id=user_id,
        revoked_at__isnull=True,
        expires_at__gt=now,
    ).count()


@sync_to_async(thread_sensitive=True)
def clear_warnings(group_id, user_id):
    return Warning.objects.filter(
        group_id=group_id,
        user_id=user_id,
        revoked_at__isnull=True,
    ).update(revoked_at=timezone.now())


@sync_to_async(thread_sensitive=True)
def get_active_warning_count(group_id, user_id):
    now = timezone.now()
    return Warning.objects.filter(
        group_id=group_id,
        user_id=user_id,
        revoked_at__isnull=True,
        expires_at__gt=now,
    ).count()


@sync_to_async(thread_sensitive=True)
def purge_old_moderation_logs(group_id, retention_days):
    cutoff = timezone.now() - timedelta(days=max(retention_days, 1))
    return ModerationLog.objects.filter(group_id=group_id, created_at__lt=cutoff).delete()[0]


@sync_to_async(thread_sensitive=True)
def consume_group_quota(chat_id: int, chat_title: str = "") -> bool:
    """Atomically consume one daily request from a group's quota."""
    today = timezone.localdate()

    with transaction.atomic():
        quota, _ = GroupQuota.objects.select_for_update().get_or_create(
            chat_id=chat_id,
            defaults={"chat_title": chat_title},
        )

        changed_fields = []
        if chat_title and quota.chat_title != chat_title:
            quota.chat_title = chat_title
            changed_fields.append("chat_title")
        if quota.last_reset < today:
            quota.tokens_used_today = 0
            quota.last_reset = today
            changed_fields.extend(("tokens_used_today", "last_reset"))
        if changed_fields:
            quota.save(update_fields=list(dict.fromkeys(changed_fields)))

        if quota.daily_prompt_limit <= 0 or quota.tokens_used_today >= quota.daily_prompt_limit:
            return False

        GroupQuota.objects.filter(pk=quota.pk).update(
            tokens_used_today=F("tokens_used_today") + 1,
        )
        return True


from botapp.ai import build_ai_messages

async def call_noya_api(question: str, session_id: str) -> str:
    api_key = os.getenv("NOYA_API_KEY", "").strip()
    if not api_key:
        logger.error("NOYA_API_KEY is not configured")
        return "خطا در ارتباط با نویا. لطفاً دوباره تلاش کنید."

    url = os.getenv("NOYA_API_URL", "http://127.0.0.1:20128/v1/chat/completions").strip()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": os.getenv("NOYA_MODEL", "TinkeraBot").strip(),
        "stream": False,
        "messages": build_ai_messages(question),
    }
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        logger.exception("Noya AI API request failed")
        return "خطا در ارتباط با نویا. لطفاً دوباره تلاش کنید."


async def call_ai_api(api_url: str, question: str, session_id: str) -> str:
    payload = {
        "sessionId": session_id,
        "messages": build_ai_messages(question),
    }
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(api_url, json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.TimeoutException:
        return "زمان پاسخ تمام شد. لطفا دوباره تلاش کنید."
    except (httpx.HTTPError, ValueError):
        logger.exception("AI API request failed")
        return "خطا در ارتباط با هوش مصنوعی. لطفا دوباره تلاش کنید."

    content = data.get("content") if isinstance(data, dict) else None
    return content if isinstance(content, str) and content.strip() else "پاسخی دریافت نشد."
