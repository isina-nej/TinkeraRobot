"""Resolve the chat a remote admin command should operate on.

Admins can drive the agent from a private chat by naming a target
(``@channel``, ``-100…``) or by forwarding / replying to a forward from that
chat. In-group / in-channel commands keep the current chat as the target.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError

_CHAT_ID_RE = re.compile(r"^-?\d{6,}$")
_AT_USER_RE = re.compile(r"^@([a-zA-Z]\w{3,31})\b")
_TME_RE = re.compile(
    r"(?i)^(?:https?://)?(?:t\.me|telegram\.me)/([a-zA-Z]\w{3,31})\b"
)
_PREFIX_MARKERS = (
    "در کانال",
    "تو کانال",
    "برای کانال",
    "کانال",
    "در گروه",
    "تو گروه",
    "برای گروه",
    "گروه",
    "در چت",
    "برای",
    "در",
)


@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    chat_id: int
    cleaned_command: str
    source: str  # "current" | "explicit" | "forward"
    title: str = ""
    chat_type: str = ""


def _forward_origin_chat(message) -> int | None:
    for candidate in (
        message,
        getattr(message, "reply_to_message", None),
    ):
        if candidate is None:
            continue
        # aiogram 3: forward_origin may be MessageOriginChannel / Chat
        origin = getattr(candidate, "forward_origin", None)
        if origin is not None:
            chat = getattr(origin, "chat", None)
            if chat is not None and getattr(chat, "id", None) is not None:
                return int(chat.id)
        legacy = getattr(candidate, "forward_from_chat", None)
        if legacy is not None and getattr(legacy, "id", None) is not None:
            return int(legacy.id)
    return None


def extract_explicit_chat_ref(command: str) -> tuple[str | None, str]:
    """Pull a leading chat reference out of the command text.

    Returns ``(ref, remainder)`` where ``ref`` is ``@user`` or a numeric id
    string, or ``(None, original)`` when no leading target is present.
    """
    text = (command or "").strip()
    if not text:
        return None, ""

    working = text
    lowered = working.casefold()
    for marker in _PREFIX_MARKERS:
        if lowered.startswith(marker + " ") or lowered.startswith(marker + "\u200c"):
            working = working[len(marker):].strip()
            lowered = working.casefold()
            break

    at = _AT_USER_RE.match(working)
    if at:
        ref = f"@{at.group(1)}"
        return ref, working[at.end():].strip()

    tme = _TME_RE.match(working)
    if tme:
        ref = f"@{tme.group(1)}"
        return ref, working[tme.end():].strip()

    # Also accept "t.me/xxx rest" without being at the absolute start after marker.
    first, _, rest = working.partition(" ")
    if _CHAT_ID_RE.fullmatch(first):
        return first, rest.strip()
    if first.startswith("@") and _AT_USER_RE.match(first):
        return first, rest.strip()
    parsed = urlparse(first if "://" in first else f"https://{first}")
    if parsed.netloc.lower() in {"t.me", "telegram.me"}:
        part = next((p for p in parsed.path.split("/") if p), "")
        if part and not part.startswith(("+", "joinchat")):
            return f"@{part}", rest.strip()
    return None, text


async def resolve_target_chat(bot, message, command_text: str) -> ResolvedTarget:
    """Decide which chat the agent command should run against."""
    cleaned = (command_text or "").strip()
    current_type = str(getattr(message.chat, "type", "") or "")

    ref, remainder = extract_explicit_chat_ref(cleaned)
    if ref:
        try:
            chat = await bot.get_chat(ref)
        except TelegramAPIError as exc:
            raise ValueError(
                "❌ کانال/گروه هدف پیدا نشد. یوزرنیم یا شناسه را بررسی کنید و "
                "مطمئن شوید ربات در آن عضو (و برای مدیریت، ادمین) است."
            ) from exc
        return ResolvedTarget(
            chat_id=int(chat.id),
            cleaned_command=remainder,
            source="explicit",
            title=getattr(chat, "title", "") or "",
            chat_type=str(getattr(chat, "type", "") or ""),
        )

    forwarded_id = _forward_origin_chat(message)
    if forwarded_id is not None and current_type == ChatType.PRIVATE:
        try:
            chat = await bot.get_chat(forwarded_id)
        except TelegramAPIError as exc:
            raise ValueError(
                "❌ به چت فورواردشده دسترسی ندارم. ربات باید در آن گروه/کانال عضو باشد."
            ) from exc
        return ResolvedTarget(
            chat_id=int(chat.id),
            cleaned_command=cleaned,
            source="forward",
            title=getattr(chat, "title", "") or "",
            chat_type=str(getattr(chat, "type", "") or ""),
        )

    if current_type == ChatType.PRIVATE:
        raise ValueError(
            "❌ در پیوی باید گروه/کانال هدف را مشخص کنید.\n\n"
            "مثال‌ها:\n"
            "/agent @mychannel آمار امروز\n"
            "/agent -100123456789 تحلیل کن\n"
            "یا یک پیام از آن چت را فوروارد کنید و بعد دستور بدهید."
        )

    return ResolvedTarget(
        chat_id=int(message.chat.id),
        cleaned_command=cleaned,
        source="current",
        title=getattr(message.chat, "title", "") or "",
        chat_type=current_type,
    )
