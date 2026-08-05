"""Minimal execution context passed to tools and (a redacted subset) to the AI.

Only the information a tool or the model actually needs is collected here. We
never place tokens, secrets, other groups' data, full histories or raw logs in
the context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from django.utils import timezone

from .permissions import AdminIdentity, BotCapabilities

REPLY_EXCERPT_LIMIT = 240


@dataclass
class ReplyTarget:
    user_id: int | None
    is_bot: bool
    full_name: str = ""
    username: str = ""
    message_id: int | None = None
    excerpt: str = ""


@dataclass
class AgentContext:
    chat_id: int
    chat_type: str
    chat_title: str
    admin: AdminIdentity
    bot_capabilities: BotCapabilities
    command_text: str = ""
    reply: ReplyTarget | None = None
    group_settings: Any | None = None
    timezone_name: str = ""
    now: datetime = field(default_factory=timezone.now)
    # Chat where the admin issued the command (private UI vs operational chat).
    request_chat_id: int | None = None
    target_source: str = "current"

    @property
    def is_channel(self) -> bool:
        return "channel" in str(self.chat_type).lower()

    def label(self) -> str:
        return "کانال" if self.is_channel else "گروه"

    def ai_payload(self, tool_catalog: list[dict]) -> dict:
        """Redacted context sent to the model. No secrets, no cross-group data."""
        settings = self.group_settings
        relevant_settings: dict[str, Any] = {}
        if settings is not None:
            relevant_settings = {
                "moderation_enabled": settings.moderation_enabled,
                "anti_spam_enabled": settings.anti_spam_enabled,
                "anti_link_enabled": settings.anti_link_enabled,
                "anti_forward_enabled": settings.anti_forward_enabled,
                "max_warnings": settings.max_warnings,
                "flood_limit": settings.flood_limit,
                "mute_duration_minutes": settings.mute_duration_minutes,
            }
        return {
            "chat_id": self.chat_id,
            "chat_type": self.chat_type,
            "chat_kind": "channel" if "channel" in str(self.chat_type).lower() else "group",
            "request_chat_id": self.request_chat_id,
            "admin_user_id": self.admin.user_id,
            "admin_role": self.admin.role,
            "bot_permissions": {
                "can_restrict_members": self.bot_capabilities.can_restrict_members,
                "can_delete_messages": self.bot_capabilities.can_delete_messages,
                "can_pin_messages": self.bot_capabilities.can_pin_messages,
                "can_post_messages": self.bot_capabilities.can_post_messages,
            },
            "reply_target": (
                {
                    "user_id": self.reply.user_id,
                    "message_id": self.reply.message_id,
                    "is_bot": self.reply.is_bot,
                }
                if self.reply
                else None
            ),
            "available_tools": tool_catalog,
            "relevant_group_settings": relevant_settings,
            "timezone": self.timezone_name,
            "current_datetime": self.now.isoformat(),
        }


def _excerpt(text: str | None) -> str:
    clean = (text or "").strip().replace("\n", " ")
    if len(clean) > REPLY_EXCERPT_LIMIT:
        return clean[:REPLY_EXCERPT_LIMIT] + "…"
    return clean


def reply_target_from_message(message) -> ReplyTarget | None:
    replied = getattr(message, "reply_to_message", None)
    if not replied:
        return None
    user = getattr(replied, "from_user", None)
    user_id = getattr(user, "id", None) if user else None
    return ReplyTarget(
        user_id=int(user_id) if user_id is not None else None,
        is_bot=bool(getattr(user, "is_bot", False)) if user else False,
        full_name=getattr(user, "full_name", "") or "",
        username=getattr(user, "username", "") or "",
        message_id=int(replied.message_id),
        excerpt=_excerpt(getattr(replied, "text", None) or getattr(replied, "caption", None)),
    )
