from django.db.models import Q
from django.utils import timezone

from botapp.models import MemoryItem, MemoryLifecycleEvent


def expire_memories(now=None) -> int:
    now = now or timezone.now()
    items = list(MemoryItem.objects.filter(
        status=MemoryItem.Status.ACTIVE,
        expires_at__lte=now,
    ).exclude(retention_level=MemoryItem.Retention.CRITICAL))
    if not items:
        return 0
    MemoryItem.objects.filter(pk__in=[item.pk for item in items]).update(
        status=MemoryItem.Status.EXPIRED,
        updated_at=now,
    )
    MemoryLifecycleEvent.objects.bulk_create([
        MemoryLifecycleEvent(
            memory=item,
            event_type="expired",
            old_status=MemoryItem.Status.ACTIVE,
            new_status=MemoryItem.Status.EXPIRED,
            reason="retention TTL reached",
        )
        for item in items
    ])
    return len(items)
