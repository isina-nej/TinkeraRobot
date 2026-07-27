from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from botapp.models import (
    MemoryConversation,
    MemoryItem,
    MemoryLifecycleEvent,
    MemorySource,
    TelegramUser,
)
from .extraction import MemoryCandidate, extract_candidates, normalize_content, validate_candidate


def _expires_at(candidate: MemoryCandidate, now):
    from django.conf import settings

    if candidate.retention_level == MemoryItem.Retention.CRITICAL:
        return None
    if candidate.retention_level == MemoryItem.Retention.SHORT:
        return now + timedelta(hours=int(getattr(settings, "MEMORY_SHORT_TERM_TTL_HOURS", 24)))
    if candidate.retention_level == MemoryItem.Retention.MEDIUM:
        return now + timedelta(days=int(getattr(settings, "MEMORY_MEDIUM_TERM_TTL_DAYS", 14)))
    return now + timedelta(days=int(getattr(settings, "MEMORY_LONG_TERM_TTL_DAYS", 60)))


def _candidate_scope(candidate: MemoryCandidate, conversation: MemoryConversation):
    if (
        conversation.chat_type == "private"
        and candidate.visibility == MemoryItem.Visibility.USER_GLOBAL
        and candidate.is_explicit
    ):
        return MemoryItem.Scope.USER, None
    return MemoryItem.Scope.USER_CONVERSATION, conversation


def _is_conflict(item: MemoryItem, candidate: MemoryCandidate) -> bool:
    if item.category != candidate.category:
        return False
    old = normalize_content(item.content)
    new = normalize_content(candidate.content)
    if old == new:
        return False
    if candidate.category == "identity":
        return True
    if candidate.category == "preference":
        return any(word in old and word not in new for word in ("فارسی", "انگلیسی", "پایتون", "فلاتر"))
    return False


@transaction.atomic
def ingest_candidate(
    user_id: int,
    conversation: MemoryConversation,
    candidate: MemoryCandidate,
    *,
    message_id: int | None = None,
    timestamp=None,
    source_kind: str = "message",
):
    if not validate_candidate(candidate):
        return None
    timestamp = timestamp or timezone.now()
    user, _ = TelegramUser.objects.get_or_create(telegram_user_id=user_id)
    member, _ = conversation.members.get_or_create(user=user)
    member.last_activity_at = timestamp
    member.save(update_fields=["last_activity_at", "updated_at"])
    conversation.last_activity_at = timestamp
    conversation.save(update_fields=["last_activity_at", "updated_at"])
    scope, item_conversation = _candidate_scope(candidate, conversation)
    effective_visibility = (
        MemoryItem.Visibility.CONVERSATION_ONLY
        if scope != MemoryItem.Scope.USER and candidate.visibility == MemoryItem.Visibility.USER_GLOBAL
        else candidate.visibility
    )
    normalized = normalize_content(candidate.content)
    queryset = MemoryItem.objects.select_for_update().filter(
        owner_user=user,
        category=candidate.category,
        status=MemoryItem.Status.ACTIVE,
        normalized_content=normalized,
    )
    if scope == MemoryItem.Scope.USER:
        queryset = queryset.filter(memory_scope=MemoryItem.Scope.USER)
    else:
        queryset = queryset.filter(conversation=conversation, memory_scope=scope)
    source_exists = False
    if message_id is not None:
        source_exists = MemorySource.objects.filter(
            platform=conversation.platform,
            source_chat_id=conversation.chat_id,
            source_message_id=message_id,
        ).exists()
    item = queryset.first()
    if item:
        if not source_exists:
            item.mention_count += 1
        item.last_confirmed_at = timestamp
        item.confidence = max(item.confidence, candidate.confidence)
        item.save(update_fields=["mention_count", "last_confirmed_at", "confidence", "updated_at"])
    else:
        conflicting = MemoryItem.objects.select_for_update().filter(
            owner_user=user,
            category=candidate.category,
            status=MemoryItem.Status.ACTIVE,
        )
        if scope == MemoryItem.Scope.USER:
            conflicting = conflicting.filter(memory_scope=MemoryItem.Scope.USER)
        else:
            conflicting = conflicting.filter(conversation=conversation, memory_scope=scope)
        item = MemoryItem.objects.create(
            owner_user=user,
            subject_user=user,
            conversation=item_conversation,
            memory_scope=scope,
            category=candidate.category,
            content=candidate.content,
            normalized_content=normalized,
            importance=candidate.importance,
            retention_level=candidate.retention_level,
            visibility=effective_visibility,
            confidence=candidate.confidence,
            is_explicit=candidate.is_explicit,
            expires_at=_expires_at(candidate, timestamp),
            last_confirmed_at=timestamp,
        )
        for old in conflicting:
            if _is_conflict(old, candidate):
                old.status = MemoryItem.Status.SUPERSEDED
                old.superseded_by = item
                old.save(update_fields=["status", "superseded_by", "updated_at"])
                MemoryLifecycleEvent.objects.create(
                    memory=old,
                    event_type="superseded",
                    old_status=MemoryItem.Status.ACTIVE,
                    new_status=MemoryItem.Status.SUPERSEDED,
                    reason="new conflicting memory",
                )
    if message_id is not None:
        source, created = MemorySource.objects.get_or_create(
            memory=item,
            platform=conversation.platform,
            source_chat_id=conversation.chat_id,
            source_message_id=message_id,
            defaults={
                "speaker_user": user,
                "source_thread_id": conversation.thread_id,
                "source_kind": source_kind,
                "occurred_at": timestamp,
            },
        )
        if created:
            item.source_count = item.sources.count()
            item.save(update_fields=["source_count", "updated_at"])
    return item


def ingest_message(user_id, conversation, message_id, text, timestamp=None, **flags):
    extraction_flags = {
        key: value
        for key, value in flags.items()
        if key in {"is_command", "is_forwarded", "is_moderation", "operation"}
    }
    candidates = extract_candidates(text, **extraction_flags)
    return [
        item
        for candidate in candidates
        if (item := ingest_candidate(
            user_id,
            conversation,
            candidate,
            message_id=message_id,
            timestamp=timestamp,
            source_kind=flags.get("source_kind", "message"),
        ))
    ]
