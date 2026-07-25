import re
from dataclasses import dataclass
from urllib.parse import urlparse

from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone

from botapp.models import (
    ForcedMembershipEvent,
    ForcedMembershipInviteLink,
    ForcedMembershipRule,
    ForcedMembershipUserState,
    GroupSettings,
)


_PUBLIC_USERNAME_RE = re.compile(r"^[a-z][a-z0-9_]{4,31}$")
_PERSIAN_CHARACTERS = str.maketrans({"ي": "ی", "ك": "ک"})


@dataclass(frozen=True, slots=True)
class DestinationReference:
    kind: str
    value: str | int


def normalize_destination_reference(raw: str) -> DestinationReference:
    value = " ".join((raw or "").translate(_PERSIAN_CHARACTERS).split())
    if not value:
        raise ValueError("مقصد عضویت اجباری وارد نشده است.")

    if re.fullmatch(r"-\d+", value):
        return DestinationReference("chat_id", int(value))

    candidate = value
    if candidate.startswith("@"):
        candidate = candidate[1:]
    elif re.match(r"^(?:https?://)?(?:www\.)?t\.me/", candidate, re.IGNORECASE):
        parsed = urlparse(candidate if "://" in candidate else f"https://{candidate}")
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) != 1 or parts[0].startswith(("+", "joinchat")):
            raise ValueError("لینک مقصد خصوصی یا نامعتبر است؛ Chat ID مقصد لازم است.")
        candidate = parts[0]
    else:
        raise ValueError("مقصد باید @username، لینک عمومی t.me یا Chat ID عددی باشد.")

    candidate = candidate.casefold()
    if not _PUBLIC_USERNAME_RE.fullmatch(candidate):
        raise ValueError("نام کاربری مقصد تلگرام معتبر نیست.")
    return DestinationReference("public_username", f"@{candidate}")


@dataclass(frozen=True, slots=True)
class MembershipStatus:
    normalized: str
    is_member: bool


@dataclass(frozen=True, slots=True)
class GateDecision:
    action: str
    state_id: int


def normalize_membership_status(status: str, *, restricted_is_member: bool = False) -> MembershipStatus:
    normalized = str(getattr(status, "value", status)).casefold()
    if normalized == "banned":
        normalized = "kicked"
    is_member = normalized in {"creator", "administrator", "member"} or (
        normalized == "restricted" and restricted_is_member
    )
    return MembershipStatus(normalized, is_member)


def _user_defaults(user) -> dict:
    return {
        "username": user.username or "",
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
    }


def _event_exists(rule_id: int, update_id: int | None) -> bool:
    return update_id is not None and ForcedMembershipEvent.objects.filter(
        rule_id=rule_id,
        telegram_update_id=update_id,
    ).exists()


@sync_to_async(thread_sensitive=True)
def evaluate_nonmember_message(rule_id: int, user, message_id: int, update_id: int | None) -> GateDecision:
    with transaction.atomic():
        if _event_exists(rule_id, update_id):
            state = ForcedMembershipUserState.objects.get(rule_id=rule_id, telegram_user_id=user.id)
            return GateDecision("ignore", state.id)

        state, _ = ForcedMembershipUserState.objects.select_for_update().get_or_create(
            rule_id=rule_id,
            telegram_user_id=user.id,
            defaults=_user_defaults(user),
        )
        now = timezone.now()
        old_status = state.current_membership_status
        action = "warn" if state.first_warning_at is None and not state.has_ever_joined else "delete"
        if action == "warn":
            state.first_warning_at = now
        state.last_warning_at = now
        state.last_checked_at = now
        state.current_membership_status = "left"
        state.is_currently_member = False
        state.message_count_while_not_member += 1
        for field, value in _user_defaults(user).items():
            setattr(state, field, value)
        state.save()
        ForcedMembershipEvent.objects.create(
            rule_id=rule_id,
            telegram_user_id=user.id,
            event_type="initial_warning_sent" if action == "warn" else "message_delete_required",
            source_message_id=message_id,
            telegram_update_id=update_id,
            old_status=old_status,
            new_status="left",
        )
        return GateDecision(action, state.id)


@sync_to_async(thread_sensitive=True)
def observe_membership(
    rule_id: int,
    user,
    status: str,
    *,
    restricted_is_member: bool = False,
    update_id: int | None = None,
) -> GateDecision:
    membership = normalize_membership_status(status, restricted_is_member=restricted_is_member)
    with transaction.atomic():
        state, _ = ForcedMembershipUserState.objects.select_for_update().get_or_create(
            rule_id=rule_id,
            telegram_user_id=user.id,
            defaults=_user_defaults(user),
        )
        if _event_exists(rule_id, update_id):
            return GateDecision("ignore", state.id)

        now = timezone.now()
        old_status = state.current_membership_status
        event_type = "membership_checked"
        if membership.is_member and not state.is_currently_member:
            event_type = "rejoined" if state.has_ever_joined else "joined"
            state.join_count += 1
            if state.has_ever_joined:
                state.rejoin_count += 1
            else:
                state.first_joined_at = now
            state.has_ever_joined = True
            state.last_joined_at = now
        elif not membership.is_member and state.is_currently_member:
            event_type = "left"
            state.leave_count += 1
            state.left_at = now

        state.current_membership_status = membership.normalized
        state.is_currently_member = membership.is_member
        state.last_checked_at = now
        for field, value in _user_defaults(user).items():
            setattr(state, field, value)
        state.save()
        ForcedMembershipEvent.objects.create(
            rule_id=rule_id,
            telegram_user_id=user.id,
            event_type=event_type,
            telegram_update_id=update_id,
            old_status=old_status,
            new_status=membership.normalized,
        )
        return GateDecision("allow" if membership.is_member else "deny", state.id)


@dataclass(frozen=True, slots=True)
class ForcedMembershipReport:
    checked_users: int
    joined_users: int
    non_joined_users: int
    left_after_join_users: int
    deleted_messages: int
    rejoin_count: int


@sync_to_async(thread_sensitive=True)
def active_rules_for_source(chat_id: int) -> list[ForcedMembershipRule]:
    return list(
        ForcedMembershipRule.objects.select_related("source_group")
        .filter(source_group__chat_id=chat_id, is_active=True)
        .order_by("id")
    )


@sync_to_async(thread_sensitive=True)
def legacy_membership_setting(chat_id: int) -> tuple[int, str] | None:
    group = GroupSettings.objects.filter(
        chat_id=chat_id,
        channel_join_required=True,
    ).exclude(mandatory_channel="").first()
    if not group or group.forced_membership_rules.exists():
        return None
    return group.id, group.mandatory_channel


@sync_to_async(thread_sensitive=True)
def promote_legacy_membership_rule(group_id: int, destination) -> ForcedMembershipRule:
    rule, _ = ForcedMembershipRule.objects.get_or_create(
        source_group_id=group_id,
        destination_chat_id=destination.id,
        defaults={
            "destination_chat_title": destination.title or "",
            "destination_chat_type": str(getattr(destination.type, "value", destination.type)),
            "destination_username": destination.username or "",
            "destination_join_url": (
                f"https://t.me/{destination.username}" if destination.username else ""
            ),
            "created_by_user_id": 0,
            "is_active": True,
        },
    )
    return rule


@sync_to_async(thread_sensitive=True)
def active_rules_for_destination(chat_id: int) -> list[ForcedMembershipRule]:
    return list(
        ForcedMembershipRule.objects.select_related("source_group")
        .filter(destination_chat_id=chat_id, is_active=True)
        .order_by("id")
    )


@sync_to_async(thread_sensitive=True)
def tracked_invite_url(rule_id: int, user_id: int) -> str | None:
    return ForcedMembershipInviteLink.objects.filter(
        rule_id=rule_id,
        telegram_user_id=user_id,
        is_revoked=False,
        used_at__isnull=True,
    ).values_list("invite_link", flat=True).first()


@sync_to_async(thread_sensitive=True)
def save_tracked_invite(rule_id: int, user_id: int, invite) -> str:
    link, _ = ForcedMembershipInviteLink.objects.update_or_create(
        invite_link=invite.invite_link,
        defaults={
            "rule_id": rule_id,
            "telegram_user_id": user_id,
            "telegram_invite_link_name": invite.name or "",
            "expire_at": invite.expire_date,
            "member_limit": invite.member_limit,
            "is_revoked": invite.is_revoked,
        },
    )
    ForcedMembershipEvent.objects.create(
        rule_id=rule_id,
        telegram_user_id=user_id,
        event_type="invite_link_created",
    )
    return link.invite_link


@sync_to_async(thread_sensitive=True)
def mark_tracked_invite_used(rule_id: int, user_id: int, invite_url: str) -> None:
    updated = ForcedMembershipInviteLink.objects.filter(
        rule_id=rule_id,
        telegram_user_id=user_id,
        invite_link=invite_url,
        used_at__isnull=True,
    ).update(used_at=timezone.now())
    if updated:
        ForcedMembershipUserState.objects.filter(
            rule_id=rule_id,
            telegram_user_id=user_id,
        ).update(joined_via_tracked_invite=True)
        ForcedMembershipEvent.objects.create(
            rule_id=rule_id,
            telegram_user_id=user_id,
            event_type="invite_link_used",
        )


async def process_destination_member_update(
    *,
    chat_id: int,
    user,
    status,
    update_id: int | None,
    invite_url: str = "",
    restricted_is_member: bool = False,
) -> None:
    for rule in await active_rules_for_destination(chat_id):
        decision = await observe_membership(
            rule.id,
            user,
            status,
            restricted_is_member=restricted_is_member,
            update_id=update_id,
        )
        if invite_url and decision.action in {"allow", "ignore"}:
            await mark_tracked_invite_used(rule.id, user.id, invite_url)


@sync_to_async(thread_sensitive=True)
def rollback_initial_warning(state_id: int, rule_id: int, message_id: int, update_id: int | None) -> None:
    with transaction.atomic():
        event = ForcedMembershipEvent.objects.filter(
            rule_id=rule_id,
            telegram_update_id=update_id,
            source_message_id=message_id,
            event_type="initial_warning_sent",
        ).first()
        if not event:
            return
        state = ForcedMembershipUserState.objects.select_for_update().get(pk=state_id)
        state.first_warning_at = None
        state.last_warning_at = None
        state.message_count_while_not_member = max(0, state.message_count_while_not_member - 1)
        state.save(update_fields=[
            "first_warning_at",
            "last_warning_at",
            "message_count_while_not_member",
            "updated_at",
        ])
        event.delete()


@sync_to_async(thread_sensitive=True)
def mark_message_deleted(state_id: int, rule_id: int, message_id: int, update_id: int | None) -> None:
    with transaction.atomic():
        state = ForcedMembershipUserState.objects.select_for_update().get(pk=state_id)
        state.deleted_message_count += 1
        state.save(update_fields=["deleted_message_count", "updated_at"])
        ForcedMembershipEvent.objects.filter(
            rule_id=rule_id,
            telegram_update_id=update_id,
            source_message_id=message_id,
            event_type="message_delete_required",
        ).update(event_type="message_deleted")


@sync_to_async(thread_sensitive=True)
def forced_membership_report(rule_id: int) -> ForcedMembershipReport:
    states = ForcedMembershipUserState.objects.filter(rule_id=rule_id)
    return ForcedMembershipReport(
        checked_users=states.count(),
        joined_users=states.filter(has_ever_joined=True).count(),
        non_joined_users=states.filter(
            has_ever_joined=False,
            message_count_while_not_member__gt=0,
        ).count(),
        left_after_join_users=states.filter(
            has_ever_joined=True,
            is_currently_member=False,
        ).count(),
        deleted_messages=sum(states.values_list("deleted_message_count", flat=True)),
        rejoin_count=sum(states.values_list("rejoin_count", flat=True)),
    )
