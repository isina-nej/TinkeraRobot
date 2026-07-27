from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from botapp.models import MemoryItem, MemoryLifecycleEvent


@transaction.atomic
def forget_memories(
    user_id: int,
    query: str = "",
    conversation_id: int | None = None,
    memory_scope: str | None = None,
) -> int:
    queryset = MemoryItem.objects.select_for_update().filter(
        owner_user__telegram_user_id=user_id,
        status__in=[MemoryItem.Status.ACTIVE, MemoryItem.Status.EXPIRED, MemoryItem.Status.SUPERSEDED],
    )
    if conversation_id is not None:
        queryset = queryset.filter(conversation_id=conversation_id)
    if memory_scope is not None:
        if isinstance(memory_scope, (tuple, list, set)):
            queryset = queryset.filter(memory_scope__in=memory_scope)
        else:
            queryset = queryset.filter(memory_scope=memory_scope)
    terms = [term for term in " ".join((query or "").casefold().split()).split() if term]
    items = [
        item for item in queryset
        if not terms or all(term in f"{item.content} {item.category}".casefold() for term in terms)
    ]
    now = timezone.now()
    for item in items:
        old_status = item.status
        item.status = MemoryItem.Status.DELETED
        item.deleted_at = now
        item.save(update_fields=["status", "deleted_at", "updated_at"])
        MemoryLifecycleEvent.objects.create(
            memory=item,
            actor_user=item.owner_user,
            event_type="deleted",
            old_status=old_status,
            new_status=MemoryItem.Status.DELETED,
            reason="user forget request",
        )
    return len(items)
