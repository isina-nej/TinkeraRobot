"""Role resolution, permission policy and bot capability guard.

Two independent sources of truth are combined before any operation runs:

1. The *admin's* real Telegram role in this chat (creator/administrator) plus
   any project-internal admin allowlist.
2. The *bot's* own Telegram capabilities (can_restrict_members, etc.).

Both must allow an operation for it to proceed.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError

from .errors import AgentPermissionDenied, BotCapabilityMissing

# --- Roles -------------------------------------------------------------------

CREATOR = "creator"
ADMINISTRATOR = "administrator"
MODERATOR = "moderator"
VIEWER = "viewer"
NONE = "none"

ROLE_ORDER = {NONE: 0, VIEWER: 1, MODERATOR: 2, ADMINISTRATOR: 3, CREATOR: 4}

# --- Permissions -------------------------------------------------------------

GROUP_READ = "group.read"
MEMBERS_READ = "members.read"
MEMBERS_WARN = "members.warn"
MEMBERS_RESTRICT = "members.restrict"
MEMBERS_BAN = "members.ban"
MESSAGES_DELETE = "messages.delete"
MESSAGES_BULK_DELETE = "messages.bulk_delete"
MESSAGES_PIN = "messages.pin"
SETTINGS_READ = "settings.read"
SETTINGS_WRITE = "settings.write"
ANALYTICS_READ = "analytics.read"
AUDIT_READ = "audit.read"

# Minimum role required to hold each permission.
PERMISSION_MIN_ROLE = {
    GROUP_READ: VIEWER,
    MEMBERS_READ: VIEWER,
    ANALYTICS_READ: VIEWER,
    AUDIT_READ: VIEWER,
    SETTINGS_READ: VIEWER,
    MEMBERS_WARN: MODERATOR,
    MEMBERS_RESTRICT: MODERATOR,
    MESSAGES_DELETE: MODERATOR,
    MESSAGES_PIN: MODERATOR,
    MESSAGES_BULK_DELETE: ADMINISTRATOR,
    MEMBERS_BAN: ADMINISTRATOR,
    SETTINGS_WRITE: ADMINISTRATOR,
}

# --- Bot capabilities --------------------------------------------------------

CAP_RESTRICT = "can_restrict_members"
CAP_DELETE = "can_delete_messages"
CAP_PIN = "can_pin_messages"


def _env_admin_ids() -> frozenset[int]:
    return frozenset(
        int(value.strip())
        for value in os.getenv("ADMIN_IDS", "").split(",")
        if value.strip()
    )


@dataclass
class AdminIdentity:
    user_id: int
    role: str
    display_name: str = ""
    permissions: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_admin(self) -> bool:
        return ROLE_ORDER.get(self.role, 0) >= ROLE_ORDER[VIEWER]

    def has_permission(self, permission: str) -> bool:
        if permission in self.permissions:
            return True
        min_role = PERMISSION_MIN_ROLE.get(permission)
        if min_role is None:
            return False
        return ROLE_ORDER.get(self.role, 0) >= ROLE_ORDER[min_role]


@dataclass
class BotCapabilities:
    is_admin: bool
    can_restrict_members: bool = False
    can_delete_messages: bool = False
    can_pin_messages: bool = False

    def has(self, capability: str) -> bool:
        if not capability:
            return True
        return bool(getattr(self, capability, False))


# --- Short-lived cache for admin-status lookups ------------------------------

_ROLE_CACHE: dict[tuple[int, int], tuple[float, str]] = {}
_ROLE_CACHE_TTL = 30.0


def _cache_get(chat_id: int, user_id: int) -> str | None:
    entry = _ROLE_CACHE.get((chat_id, user_id))
    if not entry:
        return None
    expires_at, role = entry
    if expires_at < time.monotonic():
        _ROLE_CACHE.pop((chat_id, user_id), None)
        return None
    return role


def _cache_set(chat_id: int, user_id: int, role: str) -> None:
    _ROLE_CACHE[(chat_id, user_id)] = (time.monotonic() + _ROLE_CACHE_TTL, role)


def _role_from_member(member) -> str:
    status = getattr(member, "status", None)
    if status == ChatMemberStatus.CREATOR:
        return CREATOR
    if status != ChatMemberStatus.ADMINISTRATOR:
        return NONE
    # Distinguish a full administrator from a limited "moderator".
    can_restrict = bool(getattr(member, "can_restrict_members", False))
    can_delete = bool(getattr(member, "can_delete_messages", False))
    can_promote = bool(getattr(member, "can_promote_members", False))
    can_change_info = bool(getattr(member, "can_change_info", False))
    if can_promote or can_change_info:
        return ADMINISTRATOR
    if can_restrict or can_delete:
        return MODERATOR
    return ADMINISTRATOR


async def resolve_admin_identity(bot, chat_id: int, user, *, use_cache: bool = True) -> AdminIdentity:
    """Resolve the sender's effective role in ``chat_id`` from Telegram."""
    user_id = int(getattr(user, "id", user))
    display_name = getattr(user, "full_name", "") or getattr(user, "username", "") or str(user_id)

    if user_id in _env_admin_ids():
        return AdminIdentity(user_id=user_id, role=ADMINISTRATOR, display_name=display_name)

    cached = _cache_get(chat_id, user_id) if use_cache else None
    if cached is not None:
        return AdminIdentity(user_id=user_id, role=cached, display_name=display_name)

    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except TelegramAPIError:
        return AdminIdentity(user_id=user_id, role=NONE, display_name=display_name)

    role = _role_from_member(member)
    if use_cache:
        _cache_set(chat_id, user_id, role)
    return AdminIdentity(user_id=user_id, role=role, display_name=display_name)


async def resolve_bot_capabilities(bot, chat_id: int) -> BotCapabilities:
    try:
        me = await bot.me()
        member = await bot.get_chat_member(chat_id, me.id)
    except TelegramAPIError:
        return BotCapabilities(is_admin=False)

    if getattr(member, "status", None) != ChatMemberStatus.ADMINISTRATOR:
        return BotCapabilities(is_admin=False)

    return BotCapabilities(
        is_admin=True,
        can_restrict_members=bool(getattr(member, "can_restrict_members", False)),
        can_delete_messages=bool(getattr(member, "can_delete_messages", False)),
        can_pin_messages=bool(getattr(member, "can_pin_messages", False)),
    )


CAPABILITY_LABELS = {
    CAP_RESTRICT: "Restrict Members",
    CAP_DELETE: "Delete Messages",
    CAP_PIN: "Pin Messages",
}


def ensure_admin_permission(identity: AdminIdentity, permission: str) -> None:
    if not identity.is_admin:
        raise AgentPermissionDenied()
    if not identity.has_permission(permission):
        raise AgentPermissionDenied(
            "❌ سطح دسترسی شما برای این عملیات کافی نیست."
        )


def ensure_bot_capability(capabilities: BotCapabilities, capability: str | None) -> None:
    if not capability:
        return
    if not capabilities.has(capability):
        label = CAPABILITY_LABELS.get(capability, capability)
        raise BotCapabilityMissing(
            "❌ امکان انجام این عملیات وجود ندارد.\n\n"
            f"دسترسی موردنیاز ربات:\n{label}"
        )


def clear_role_cache() -> None:
    _ROLE_CACHE.clear()
