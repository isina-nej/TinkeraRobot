from django.contrib import admin

from botapp.models import (
    MemoryConversation,
    MemoryConversationMember,
    MemoryItem,
    MemoryLifecycleEvent,
    MemorySource,
)


@admin.register(MemoryConversation)
class MemoryConversationAdmin(admin.ModelAdmin):
    list_display = ("conversation_id", "platform", "chat_id", "thread_id", "chat_type", "last_activity_at")
    list_filter = ("platform", "chat_type", "last_activity_at")
    search_fields = ("conversation_id", "=chat_id", "title")
    readonly_fields = tuple(field.name for field in MemoryConversation._meta.fields)
    list_per_page = 50


@admin.register(MemoryConversationMember)
class MemoryConversationMemberAdmin(admin.ModelAdmin):
    list_display = ("conversation", "user", "role", "last_activity_at")
    list_filter = ("role", "last_activity_at")
    search_fields = ("conversation__conversation_id", "=user__telegram_user_id")
    readonly_fields = tuple(field.name for field in MemoryConversationMember._meta.fields)
    list_per_page = 50

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("conversation", "user")


@admin.register(MemoryItem)
class MemoryItemAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "owner_user",
        "memory_scope",
        "category",
        "importance",
        "visibility",
        "status",
        "retention_level",
        "mention_count",
        "updated_at",
    )
    list_filter = ("memory_scope", "category", "importance", "visibility", "status", "retention_level")
    search_fields = ("content", "normalized_content", "=owner_user__telegram_user_id", "conversation__conversation_id")
    readonly_fields = tuple(field.name for field in MemoryItem._meta.fields)
    list_per_page = 50

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("owner_user", "subject_user", "conversation", "superseded_by")


@admin.register(MemorySource)
class MemorySourceAdmin(admin.ModelAdmin):
    list_display = ("memory", "platform", "source_chat_id", "source_message_id", "source_thread_id", "source_kind", "occurred_at")
    list_filter = ("platform", "source_kind", "occurred_at")
    search_fields = ("=source_chat_id", "=source_message_id", "memory__content")
    readonly_fields = tuple(field.name for field in MemorySource._meta.fields)
    list_per_page = 50

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("memory", "speaker_user")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MemoryLifecycleEvent)
class MemoryLifecycleEventAdmin(admin.ModelAdmin):
    list_display = ("memory", "event_type", "old_status", "new_status", "reason", "created_at")
    list_filter = ("event_type", "old_status", "new_status", "created_at")
    search_fields = ("reason", "=memory__id", "=actor_user__telegram_user_id")
    readonly_fields = tuple(field.name for field in MemoryLifecycleEvent._meta.fields)
    list_per_page = 50

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("memory", "actor_user")

    def has_delete_permission(self, request, obj=None):
        return False
