from django.contrib import admin

from botapp.models import (
    BotMessageSettings,
    BotStartGateEvent,
    GroupUserGateState,
    ChatLink,
    GroupActionLog,
    GroupQuota,
    GroupSettings,
    ForcedMembershipEvent,
    ForcedMembershipInviteLink,
    ForcedMembershipRule,
    ForcedMembershipUserState,
    ModerationAction,
    ModerationLog,
    StaffAPIKey,
    TelegramUser,
    Warning,
)


@admin.register(TelegramUser)
class TelegramUserAdmin(admin.ModelAdmin):
    list_display = ("telegram_user_id", "started", "blocked", "last_live_check_at")
    list_filter = ("started", "blocked")
    search_fields = ("=telegram_user_id",)


@admin.register(GroupUserGateState)
class GroupUserGateStateAdmin(admin.ModelAdmin):
    list_display = (
        "group",
        "telegram_user_id",
        "warning_sent_at",
        "last_warning_update_at",
        "notice_delete_at",
        "message_deleted_count",
        "last_check_at",
    )
    list_filter = ("warning_sent_at", "last_check_at")
    search_fields = ("=telegram_user_id", "=group__chat_id", "group__chat_title")
    readonly_fields = (
        "group",
        "telegram_user_id",
        "first_message_at",
        "warning_sent_at",
        "last_warning_update_at",
        "warning_message_id",
        "notice_delete_at",
        "message_deleted_count",
        "last_check_at",
        "created_at",
        "updated_at",
    )


@admin.register(BotStartGateEvent)
class BotStartGateEventAdmin(admin.ModelAdmin):
    list_display = (
        "group",
        "telegram_user_id",
        "message_id",
        "telegram_update_id",
        "action",
        "status",
        "created_at",
    )
    list_filter = ("action", "status", "created_at")
    search_fields = ("=telegram_user_id", "=message_id", "=telegram_update_id", "=group__chat_id")
    readonly_fields = ("created_at", "updated_at")


@admin.register(BotMessageSettings)
class BotMessageSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "collaboration_enabled",
        "channel_join_required",
        "bot_start_required",
    )


@admin.register(GroupQuota)
class GroupQuotaAdmin(admin.ModelAdmin):
    list_display = (
        "chat_id",
        "chat_title",
        "tokens_used_today",
        "daily_prompt_limit",
        "last_reset",
    )
    list_filter = ("last_reset",)
    search_fields = ("=chat_id", "chat_title")


@admin.register(ChatLink)
class ChatLinkAdmin(admin.ModelAdmin):
    list_display = (
        "token_short",
        "group_chat_id",
        "group_title",
        "created_by_user_id",
        "created_at",
        "is_active",
    )
    list_filter = ("is_active", "created_at")
    search_fields = ("token", "group_title", "=group_chat_id")
    readonly_fields = ("token", "created_at")

    @admin.display(description="Token")
    def token_short(self, obj):
        return f"{obj.token[:12]}..."


@admin.register(GroupSettings)
class GroupSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "chat_id",
        "chat_title",
        "moderation_enabled",
        "anti_spam_enabled",
        "anti_link_enabled",
        "welcome_enabled",
        "collaboration_enabled",
        "updated_at",
    )
    list_filter = (
        "moderation_enabled",
        "anti_spam_enabled",
        "anti_link_enabled",
        "anti_forward_enabled",
        "welcome_enabled",
        "collaboration_enabled",
        "channel_join_required",
        "bot_start_required",
    )
    search_fields = ("=chat_id", "chat_title", "mandatory_channel")


@admin.register(GroupActionLog)
class GroupActionLogAdmin(admin.ModelAdmin):
    list_display = (
        "group",
        "action",
        "admin_user_id",
        "admin_name",
        "old_value",
        "new_value",
        "timestamp",
    )
    list_filter = ("action", "timestamp")
    search_fields = ("=admin_user_id", "admin_name", "=group__chat_id")
    readonly_fields = (
        "group",
        "admin_user_id",
        "admin_name",
        "action",
        "old_value",
        "new_value",
        "timestamp",
    )


@admin.register(Warning)
class WarningAdmin(admin.ModelAdmin):
    list_display = (
        "group",
        "user_id",
        "user_name",
        "issued_by_name",
        "reason",
        "created_at",
        "expires_at",
        "revoked_at",
    )
    list_filter = ("created_at", "expires_at", "revoked_at")
    search_fields = ("=group__chat_id", "=user_id", "user_name", "reason")
    readonly_fields = (
        "group",
        "user_id",
        "user_name",
        "issued_by_user_id",
        "issued_by_name",
        "reason",
        "created_at",
        "expires_at",
        "revoked_at",
    )


@admin.register(ModerationAction)
class ModerationActionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "group",
        "action",
        "target_user_id",
        "status",
        "execute_at",
        "duration_minutes",
        "source",
    )
    list_filter = ("action", "status", "source", "execute_at")
    search_fields = ("=group__chat_id", "=target_user_id", "target_name", "reason")
    readonly_fields = (
        "idempotency_key",
        "created_at",
        "started_at",
        "executed_at",
        "cancelled_at",
        "error",
    )


@admin.register(StaffAPIKey)
class StaffAPIKeyAdmin(admin.ModelAdmin):
    list_display = ("name", "prefix", "is_active", "created_by", "created_at", "last_used_at")
    list_filter = ("is_active", "created_at", "revoked_at")
    search_fields = ("name", "prefix")
    readonly_fields = ("prefix", "key_hash", "created_at", "last_used_at")


@admin.register(ForcedMembershipRule)
class ForcedMembershipRuleAdmin(admin.ModelAdmin):
    list_display = (
        "source_group",
        "destination_chat_title",
        "destination_chat_id",
        "created_by_user_id",
        "is_active",
        "last_validated_at",
        "created_at",
    )
    list_filter = ("is_active", "destination_chat_type", "created_at")
    search_fields = (
        "=source_group__chat_id",
        "source_group__chat_title",
        "=destination_chat_id",
        "destination_chat_title",
        "destination_username",
    )
    readonly_fields = ("created_at", "updated_at")
    actions = ("activate_rules", "deactivate_rules")

    @admin.action(description="فعال‌کردن قوانین انتخاب‌شده")
    def activate_rules(self, request, queryset):
        queryset.update(is_active=True)

    @admin.action(description="غیرفعال‌کردن قوانین انتخاب‌شده")
    def deactivate_rules(self, request, queryset):
        queryset.update(is_active=False)


@admin.register(ForcedMembershipUserState)
class ForcedMembershipUserStateAdmin(admin.ModelAdmin):
    list_display = (
        "rule",
        "telegram_user_id",
        "username",
        "current_membership_status",
        "has_ever_joined",
        "is_currently_member",
        "deleted_message_count",
        "rejoin_count",
        "updated_at",
    )
    list_filter = ("current_membership_status", "has_ever_joined", "is_currently_member")
    search_fields = ("=telegram_user_id", "username", "first_name", "last_name", "=rule__id")
    readonly_fields = tuple(field.name for field in ForcedMembershipUserState._meta.fields)


@admin.register(ForcedMembershipInviteLink)
class ForcedMembershipInviteLinkAdmin(admin.ModelAdmin):
    list_display = ("rule", "telegram_user_id", "is_revoked", "used_at", "expire_at", "created_at")
    list_filter = ("is_revoked", "used_at", "created_at")
    search_fields = ("=telegram_user_id", "invite_link", "=rule__id")
    readonly_fields = ("invite_link", "created_at", "updated_at")


@admin.register(ForcedMembershipEvent)
class ForcedMembershipEventAdmin(admin.ModelAdmin):
    list_display = ("rule", "telegram_user_id", "event_type", "telegram_update_id", "created_at")
    list_filter = ("event_type", "created_at")
    search_fields = ("=rule__id", "=telegram_user_id", "=telegram_update_id")
    readonly_fields = tuple(field.name for field in ForcedMembershipEvent._meta.fields)


@admin.register(ModerationLog)
class ModerationLogAdmin(admin.ModelAdmin):
    list_display = (
        "group",
        "action",
        "target_user_id",
        "target_name",
        "actor_name",
        "reason",
        "created_at",
    )
    list_filter = ("action", "created_at")
    search_fields = (
        "=group__chat_id",
        "=target_user_id",
        "target_name",
        "actor_name",
        "reason",
    )
    readonly_fields = (
        "group",
        "target_user_id",
        "target_name",
        "actor_user_id",
        "actor_name",
        "action",
        "reason",
        "duration_minutes",
        "created_at",
    )
