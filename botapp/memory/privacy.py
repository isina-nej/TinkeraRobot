from django.utils import timezone

from botapp.models import MemoryItem


def is_retrievable(
    item: MemoryItem,
    user_id: int,
    conversation_id: int | None,
    chat_type: str | None = None,
) -> bool:
    if item.status != MemoryItem.Status.ACTIVE:
        return False
    if not item.owner_user or item.owner_user.telegram_user_id != user_id:
        return False
    if item.expires_at and item.expires_at <= timezone.now() and item.retention_level != MemoryItem.Retention.CRITICAL:
        return False
    if item.visibility == MemoryItem.Visibility.SYSTEM_ONLY:
        return False
    if item.visibility == MemoryItem.Visibility.PRIVATE:
        return item.conversation_id == conversation_id
    if item.visibility == MemoryItem.Visibility.CONVERSATION_ONLY:
        return item.conversation_id == conversation_id
    if item.memory_scope == MemoryItem.Scope.USER:
        return (
            chat_type == "private"
            and item.visibility == MemoryItem.Visibility.USER_GLOBAL
        )
    return item.conversation_id == conversation_id
