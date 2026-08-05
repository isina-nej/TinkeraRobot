"""Always-on lightweight activity counters for groups/channels.

Unlike MessageSnapshot archival (opt-in, stores text), this only increments
aggregates the bot can observe after enablement. Used by analytics tools so
questions like «امروز چند پیام داشتیم؟» get a real number instead of a
hallucinated «فایل JSON آپلود کن».
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from botapp.models import ChatDailyActivity, ChatDailySender

TRACKED_CHAT_TYPES = {"group", "supergroup", "channel"}


def _is_media(message) -> bool:
    return any(
        getattr(message, attr, None)
        for attr in ("photo", "video", "document", "audio", "voice", "sticker", "animation", "video_note")
    )


def record_message_activity(message) -> None:
    chat = getattr(message, "chat", None)
    if not chat or str(getattr(chat, "type", "")) not in TRACKED_CHAT_TYPES:
        return
    # Service / empty join notices without content still count as events the bot saw.
    occurred = getattr(message, "date", None) or timezone.now()
    day = timezone.localdate(occurred)
    chat_id = int(chat.id)
    user = getattr(message, "from_user", None)
    is_media = _is_media(message)

    with transaction.atomic():
        activity, _ = ChatDailyActivity.objects.select_for_update().get_or_create(
            chat_id=chat_id,
            day=day,
            defaults={
                "message_count": 0,
                "media_count": 0,
                "unique_sender_count": 0,
            },
        )
        updates = ["message_count", "updated_at"]
        activity.message_count = F("message_count") + 1
        if is_media:
            activity.media_count = F("media_count") + 1
            updates.append("media_count")
        activity.save(update_fields=updates)
        activity.refresh_from_db(fields=["message_count", "media_count", "unique_sender_count"])

        if user is None or getattr(user, "is_bot", False):
            return

        sender, created = ChatDailySender.objects.select_for_update().get_or_create(
            chat_id=chat_id,
            day=day,
            user_id=int(user.id),
            defaults={
                "display_name": (getattr(user, "full_name", "") or "")[:255],
                "username": (getattr(user, "username", "") or "")[:64],
                "message_count": 1,
            },
        )
        if created:
            ChatDailyActivity.objects.filter(pk=activity.pk).update(
                unique_sender_count=F("unique_sender_count") + 1,
            )
        else:
            name = (getattr(user, "full_name", "") or "")[:255]
            username = (getattr(user, "username", "") or "")[:64]
            ChatDailySender.objects.filter(pk=sender.pk).update(
                message_count=F("message_count") + 1,
                display_name=name or sender.display_name,
                username=username or sender.username,
            )


def get_activity(chat_id: int, day=None) -> ChatDailyActivity | None:
    day = day or timezone.localdate()
    return ChatDailyActivity.objects.filter(chat_id=chat_id, day=day).first()


def get_activity_range(chat_id: int, since_day, until_day=None):
    until_day = until_day or timezone.localdate()
    return list(
        ChatDailyActivity.objects.filter(
            chat_id=chat_id,
            day__gte=since_day,
            day__lte=until_day,
        ).order_by("day")
    )


def get_top_senders(chat_id: int, day=None, limit: int = 10):
    day = day or timezone.localdate()
    return list(
        ChatDailySender.objects.filter(chat_id=chat_id, day=day)
        .order_by("-message_count", "user_id")[:limit]
    )
