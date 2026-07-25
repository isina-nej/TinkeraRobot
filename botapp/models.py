import secrets

from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class TelegramUser(models.Model):
    user_id = models.BigIntegerField(unique=True)
    started = models.BooleanField(default=False)
    warned = models.BooleanField(default=False)
    blocked = models.BooleanField(default=False)
    welcomed_at = models.DateTimeField(null=True, blank=True)
    last_check_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return str(self.user_id)


class BotMessageSettings(models.Model):
    start_message = models.TextField(default="ربات استارت شد!")
    join_channel_message = models.TextField(
        default="{mention} برای ارسال پیام باید در {channel} عضو شوید."
    )
    collaboration_enabled = models.BooleanField(default=True)
    channel_join_required = models.BooleanField(default=True)
    bot_start_required = models.BooleanField(default=True)

    def __str__(self):
        return f"BotMessageSettings({self.pk})"


class GroupQuota(models.Model):
    """Daily AI request quota per group."""

    chat_id = models.BigIntegerField(unique=True)
    chat_title = models.CharField(max_length=255, blank=True, default="")
    daily_prompt_limit = models.PositiveIntegerField(
        default=100,
        validators=[MinValueValidator(1)],
    )
    tokens_used_today = models.PositiveIntegerField(default=0)
    last_reset = models.DateField(default=timezone.localdate)

    def __str__(self):
        return f"GroupQuota({self.chat_id}) - {self.tokens_used_today}/{self.daily_prompt_limit}"


def generate_token() -> str:
    return secrets.token_urlsafe(32)


class ChatLink(models.Model):
    token = models.CharField(max_length=64, unique=True, default=generate_token, editable=False)
    group_chat_id = models.BigIntegerField()
    group_title = models.CharField(max_length=255, blank=True, default="")
    created_by_user_id = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def is_valid(self) -> bool:
        return self.is_active and (
            self.expires_at is None or timezone.now() <= self.expires_at
        )

    def __str__(self):
        return f"ChatLink({self.token[:8]}...) -> {self.group_chat_id}"


class GroupSettings(models.Model):
    chat_id = models.BigIntegerField(unique=True)
    chat_title = models.CharField(max_length=255, blank=True, default="")
    channel_join_required = models.BooleanField(default=True)
    bot_start_required = models.BooleanField(default=True)
    collaboration_enabled = models.BooleanField(default=True)
    mandatory_channel = models.CharField(max_length=100, blank=True, default="")
    group_admins = models.JSONField(default=list, blank=True)

    moderation_enabled = models.BooleanField(default=True)
    anti_spam_enabled = models.BooleanField(default=True)
    anti_link_enabled = models.BooleanField(default=True)
    anti_forward_enabled = models.BooleanField(default=False)
    welcome_enabled = models.BooleanField(default=True)
    goodbye_enabled = models.BooleanField(default=False)
    rules_enabled = models.BooleanField(default=True)
    captcha_enabled = models.BooleanField(default=False)
    log_retention_days = models.PositiveIntegerField(default=90)
    flood_limit = models.PositiveIntegerField(default=6)
    flood_window_seconds = models.PositiveIntegerField(default=10)
    duplicate_limit = models.PositiveIntegerField(default=3)
    mute_duration_minutes = models.PositiveIntegerField(default=10)
    max_warnings = models.PositiveIntegerField(default=3)
    max_warnings_action = models.CharField(
        max_length=10,
        default="mute",
        choices=[("mute", "Mute"), ("ban", "Ban")],
    )
    max_warnings_action_delay_minutes = models.PositiveIntegerField(default=0)
    max_warnings_action_duration_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
        default=10,
    )
    warning_expiry_days = models.PositiveIntegerField(default=30)
    message_templates = models.JSONField(default=dict, blank=True)
    open_permissions_snapshot = models.JSONField(default=dict, blank=True)
    welcome_message = models.TextField(
        default=(
            "سلام #name عزیز به گروه #title خوش آمدی 🌷 "
            "✅ ساعت: ( #time ) ✅ تاریخ: ( #date )"
        )
    )
    goodbye_message = models.TextField(default="{name} از گروه خارج شد.")
    rules_text = models.TextField(default="قوانین گروه هنوز تنظیم نشده است.")
    blocked_words = models.JSONField(default=list, blank=True)
    allowed_domains = models.JSONField(default=list, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"GroupSettings({self.chat_id}) - {self.chat_title}"


class GroupActionLog(models.Model):
    group = models.ForeignKey(
        GroupSettings,
        on_delete=models.CASCADE,
        related_name="logs",
    )
    admin_user_id = models.BigIntegerField()
    admin_name = models.CharField(max_length=255, blank=True)
    action = models.CharField(max_length=100)
    old_value = models.BooleanField(null=True)
    new_value = models.BooleanField(null=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"Log({self.group.chat_id}) {self.action} by {self.admin_user_id}"


class Warning(models.Model):
    group = models.ForeignKey(
        GroupSettings,
        on_delete=models.CASCADE,
        related_name="warnings",
    )
    user_id = models.BigIntegerField()
    user_name = models.CharField(max_length=255, blank=True)
    issued_by_user_id = models.BigIntegerField()
    issued_by_name = models.CharField(max_length=255, blank=True)
    reason = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["group", "user_id", "-created_at"])]

    @property
    def is_active(self):
        return self.revoked_at is None and (
            self.expires_at is None or timezone.now() < self.expires_at
        )


class ModerationAction(models.Model):
    ACTIONS = (
        ("lock", "Lock group"),
        ("unlock", "Unlock group"),
        ("mute", "Mute user"),
        ("unmute", "Unmute user"),
        ("ban", "Ban user"),
        ("unban", "Unban user"),
    )
    STATUSES = (
        ("pending", "Pending"),
        ("processing", "Processing"),
        ("executed", "Executed"),
        ("cancelled", "Cancelled"),
        ("failed", "Failed"),
    )

    group = models.ForeignKey(
        GroupSettings,
        on_delete=models.CASCADE,
        related_name="actions",
    )
    action = models.CharField(max_length=10, choices=ACTIONS)
    target_user_id = models.BigIntegerField(null=True, blank=True)
    target_name = models.CharField(max_length=255, blank=True)
    actor_user_id = models.BigIntegerField(null=True, blank=True)
    actor_name = models.CharField(max_length=255, blank=True)
    reason = models.CharField(max_length=500, blank=True)
    execute_at = models.DateTimeField(default=timezone.now, db_index=True)
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=STATUSES, default="pending", db_index=True)
    idempotency_key = models.CharField(max_length=80, unique=True)
    source = models.CharField(max_length=20, default="telegram")
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["execute_at"]
        indexes = [
            models.Index(fields=["status", "execute_at"]),
            models.Index(fields=["group", "target_user_id", "status"]),
        ]


class GroupSchedule(models.Model):
    ACTIONS = (("lock", "Lock"), ("unlock", "Unlock"))

    group = models.ForeignKey(
        GroupSettings,
        on_delete=models.CASCADE,
        related_name="schedules",
    )
    action = models.CharField(max_length=10, choices=ACTIONS)
    time_of_day = models.TimeField()
    is_active = models.BooleanField(default=True)
    last_enqueued_date = models.DateField(null=True, blank=True)
    created_by_user_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["group", "action", "time_of_day"],
                name="unique_group_daily_schedule",
            )
        ]


class StaffAPIKey(models.Model):
    name = models.CharField(max_length=100)
    prefix = models.CharField(max_length=12, db_index=True)
    key_hash = models.CharField(max_length=64, unique=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_bot_api_keys",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)


class ModerationLog(models.Model):
    ACTIONS = (
        ("warn", "Warn"),
        ("unwarn", "Unwarn"),
        ("lock", "Lock"),
        ("unlock", "Unlock"),
        ("mute", "Mute"),
        ("unmute", "Unmute"),
        ("ban", "Ban"),
        ("unban", "Unban"),
        ("delete", "Delete"),
        ("filter", "Filter"),
    )

    group = models.ForeignKey(
        GroupSettings,
        on_delete=models.CASCADE,
        related_name="moderation_logs",
    )
    target_user_id = models.BigIntegerField(null=True, blank=True)
    target_name = models.CharField(max_length=255, blank=True)
    actor_user_id = models.BigIntegerField(null=True, blank=True)
    actor_name = models.CharField(max_length=255, blank=True)
    action = models.CharField(max_length=20, choices=ACTIONS)
    reason = models.CharField(max_length=500, blank=True)
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    moderation_action = models.ForeignKey(
        ModerationAction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="logs",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["group", "-created_at"])]


class BotStartUserState(models.Model):
    group = models.ForeignKey(
        GroupSettings,
        on_delete=models.CASCADE,
        related_name="bot_start_user_states",
    )
    telegram_user_id = models.BigIntegerField()
    first_message_at = models.DateTimeField(null=True, blank=True)
    warning_pending_at = models.DateTimeField(null=True, blank=True)
    warning_sent_at = models.DateTimeField(null=True, blank=True)
    last_notice_at = models.DateTimeField(null=True, blank=True)
    notice_message_id = models.BigIntegerField(null=True, blank=True)
    notice_delete_at = models.DateTimeField(null=True, blank=True)
    message_deleted_count = models.PositiveBigIntegerField(default=0)
    last_check_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["group", "telegram_user_id"],
                name="uniq_bot_start_state_group_user",
            )
        ]
        indexes = [models.Index(fields=["group", "telegram_user_id"])]


class BotStartGateEvent(models.Model):
    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    )

    group = models.ForeignKey(
        GroupSettings,
        on_delete=models.CASCADE,
        related_name="bot_start_gate_events",
    )
    telegram_user_id = models.BigIntegerField()
    message_id = models.BigIntegerField()
    telegram_update_id = models.BigIntegerField(null=True, blank=True)
    action = models.CharField(max_length=16)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["group", "message_id"],
                name="uniq_bot_start_event_group_message",
            )
        ]
        indexes = [models.Index(fields=["group", "telegram_user_id", "status"])]


class ForcedMembershipRule(models.Model):
    source_group = models.ForeignKey(
        GroupSettings,
        on_delete=models.CASCADE,
        related_name="forced_membership_rules",
    )
    destination_chat_id = models.BigIntegerField()
    destination_chat_title = models.CharField(max_length=255, blank=True, default="")
    destination_chat_type = models.CharField(max_length=20, blank=True, default="")
    destination_username = models.CharField(max_length=32, blank=True, default="")
    destination_join_url = models.URLField(max_length=500, blank=True, default="")
    created_by_user_id = models.BigIntegerField()
    is_active = models.BooleanField(default=True)
    last_validated_at = models.DateTimeField(null=True, blank=True)
    bot_source_permissions_valid = models.BooleanField(default=False)
    bot_destination_permissions_valid = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source_group", "destination_chat_id"],
                name="uniq_forced_rule_source_destination",
            )
        ]
        indexes = [
            models.Index(fields=["source_group", "is_active"]),
            models.Index(fields=["destination_chat_id", "is_active"]),
        ]

    def __str__(self):
        return f"{self.source_group.chat_id} -> {self.destination_chat_id}"


class ForcedMembershipUserState(models.Model):
    rule = models.ForeignKey(
        ForcedMembershipRule,
        on_delete=models.CASCADE,
        related_name="user_states",
    )
    telegram_user_id = models.BigIntegerField()
    username = models.CharField(max_length=32, blank=True, default="")
    first_name = models.CharField(max_length=255, blank=True, default="")
    last_name = models.CharField(max_length=255, blank=True, default="")
    current_membership_status = models.CharField(max_length=32, default="unknown")
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    first_warning_at = models.DateTimeField(null=True, blank=True)
    last_warning_at = models.DateTimeField(null=True, blank=True)
    first_joined_at = models.DateTimeField(null=True, blank=True)
    last_joined_at = models.DateTimeField(null=True, blank=True)
    left_at = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    message_count_while_not_member = models.PositiveBigIntegerField(default=0)
    deleted_message_count = models.PositiveBigIntegerField(default=0)
    join_count = models.PositiveIntegerField(default=0)
    leave_count = models.PositiveIntegerField(default=0)
    rejoin_count = models.PositiveIntegerField(default=0)
    has_ever_joined = models.BooleanField(default=False)
    is_currently_member = models.BooleanField(default=False)
    joined_via_tracked_invite = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["rule", "telegram_user_id"],
                name="uniq_forced_state_rule_user",
            )
        ]
        indexes = [
            models.Index(fields=["rule", "current_membership_status"]),
            models.Index(fields=["rule", "has_ever_joined"]),
            models.Index(fields=["rule", "is_currently_member"]),
        ]


class ForcedMembershipInviteLink(models.Model):
    rule = models.ForeignKey(
        ForcedMembershipRule,
        on_delete=models.CASCADE,
        related_name="invite_links",
    )
    telegram_user_id = models.BigIntegerField()
    invite_link = models.URLField(max_length=500, unique=True)
    telegram_invite_link_name = models.CharField(max_length=100, blank=True, default="")
    expire_at = models.DateTimeField(null=True, blank=True)
    member_limit = models.PositiveIntegerField(null=True, blank=True)
    is_revoked = models.BooleanField(default=False)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["rule", "telegram_user_id", "is_revoked"])]


class ForcedMembershipEvent(models.Model):
    rule = models.ForeignKey(
        ForcedMembershipRule,
        on_delete=models.CASCADE,
        related_name="events",
    )
    telegram_user_id = models.BigIntegerField(null=True, blank=True)
    event_type = models.CharField(max_length=40)
    source_message_id = models.BigIntegerField(null=True, blank=True)
    telegram_update_id = models.BigIntegerField(null=True, blank=True)
    old_status = models.CharField(max_length=32, blank=True, default="")
    new_status = models.CharField(max_length=32, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["rule", "telegram_update_id"],
                name="uniq_forced_event_rule_update",
            )
        ]
        indexes = [
            models.Index(fields=["rule", "event_type", "created_at"]),
            models.Index(fields=["telegram_update_id"]),
        ]
