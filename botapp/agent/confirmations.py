"""Glass-key confirmation lifecycle for sensitive agent operations.

Token model (important, matches the implementation exactly):

* A cryptographically-random, unguessable token is generated with
  ``secrets.token_urlsafe`` (>=128 bits of entropy).
* The RAW token is placed only inside the inline-keyboard ``callback_data``
  (``agent_confirm:<raw>`` / ``agent_cancel:<raw>``); it never enters the DB,
  logs or the audit log.
* Only the SHA-256 hash of the token is stored on the row (``token_hash``).
* On callback, the received raw token is hashed and the row is looked up by
  that hash; the raw value is discarded.
* ``callback_data`` length stays well under Telegram's 64-byte limit
  (prefix <=14 bytes + ``token_urlsafe(24)`` == 32 chars → <=46 bytes).

Execution is guarded by ``transaction.atomic`` + ``select_for_update`` so a
double click can never run the operation twice.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from botapp.models import AgentConfirmation

from .errors import (
    AgentPermissionDenied,
    ConfirmationAlreadyHandled,
    ConfirmationExpired,
)

CONFIRM_PREFIX = "agent_confirm:"
CANCEL_PREFIX = "agent_cancel:"

# Valid status transitions for the confirmation state machine.
VALID_TRANSITIONS = {
    AgentConfirmation.STATUS_PENDING: {
        AgentConfirmation.STATUS_EXECUTING,
        AgentConfirmation.STATUS_CONFIRMED,
        AgentConfirmation.STATUS_CANCELLED,
        AgentConfirmation.STATUS_EXPIRED,
    },
    AgentConfirmation.STATUS_CONFIRMED: {
        AgentConfirmation.STATUS_EXECUTING,
    },
    AgentConfirmation.STATUS_EXECUTING: {
        AgentConfirmation.STATUS_EXECUTED,
        AgentConfirmation.STATUS_FAILED,
    },
}


def generate_token() -> str:
    return secrets.token_urlsafe(24)


def hash_token(raw: str) -> str:
    return hashlib.sha256((raw or "").encode()).hexdigest()


def can_transition(current: str, target: str) -> bool:
    return target in VALID_TRANSITIONS.get(current, set())


def create_confirmation(
    *,
    chat_id: int,
    requester_user_id: int,
    requester_name: str,
    tool_name: str,
    validated_parameters: dict,
    human_summary: str,
    risk_level: str,
    target_user_id: int | None = None,
    request_message_id: int | None = None,
    ttl_seconds: int = 120,
) -> tuple[AgentConfirmation, str]:
    raw = generate_token()
    confirmation = AgentConfirmation.objects.create(
        token_hash=hash_token(raw),
        chat_id=chat_id,
        requester_user_id=requester_user_id,
        requester_name=requester_name[:255],
        tool_name=tool_name,
        target_user_id=target_user_id,
        validated_parameters=validated_parameters,
        human_summary=human_summary[:300],
        risk_level=risk_level,
        request_message_id=request_message_id,
        expires_at=timezone.now() + timedelta(seconds=max(ttl_seconds, 10)),
    )
    return confirmation, raw


@transaction.atomic
def claim_for_execution(raw_token: str, *, requester_user_id: int, chat_id: int) -> AgentConfirmation:
    """Atomically transition a pending confirmation to ``executing``.

    Enforces ownership, chat scoping, expiry and single-use. Raises a domain
    error otherwise. The row is locked for the duration of the transaction so
    concurrent clicks cannot both succeed.
    """
    confirmation = (
        AgentConfirmation.objects.select_for_update()
        .filter(token_hash=hash_token(raw_token))
        .first()
    )
    if confirmation is None:
        raise ConfirmationAlreadyHandled("❌ این درخواست معتبر نیست یا قبلاً پردازش شده است.")
    if confirmation.chat_id != chat_id or confirmation.requester_user_id != requester_user_id:
        raise AgentPermissionDenied("❌ فقط درخواست‌دهنده می‌تواند این عملیات را تأیید کند.")
    if confirmation.status != AgentConfirmation.STATUS_PENDING:
        raise ConfirmationAlreadyHandled()
    if confirmation.expires_at <= timezone.now():
        confirmation.status = AgentConfirmation.STATUS_EXPIRED
        confirmation.save(update_fields=["status"])
        raise ConfirmationExpired()

    now = timezone.now()
    confirmation.status = AgentConfirmation.STATUS_EXECUTING
    confirmation.confirmed_at = now
    confirmation.executing_started_at = now
    confirmation.save(update_fields=["status", "confirmed_at", "executing_started_at"])
    return confirmation


@transaction.atomic
def cancel_confirmation(raw_token: str, *, requester_user_id: int, chat_id: int) -> AgentConfirmation:
    confirmation = (
        AgentConfirmation.objects.select_for_update()
        .filter(token_hash=hash_token(raw_token))
        .first()
    )
    if confirmation is None:
        raise ConfirmationAlreadyHandled("❌ این درخواست معتبر نیست یا قبلاً پردازش شده است.")
    if confirmation.chat_id != chat_id or confirmation.requester_user_id != requester_user_id:
        raise AgentPermissionDenied("❌ فقط درخواست‌دهنده می‌تواند این عملیات را لغو کند.")
    if confirmation.status != AgentConfirmation.STATUS_PENDING:
        raise ConfirmationAlreadyHandled()
    confirmation.status = AgentConfirmation.STATUS_CANCELLED
    confirmation.cancelled_at = timezone.now()
    confirmation.save(update_fields=["status", "cancelled_at"])
    return confirmation


def mark_executed(confirmation: AgentConfirmation, result_summary: str = "") -> None:
    if not can_transition(confirmation.status, AgentConfirmation.STATUS_EXECUTED):
        return
    confirmation.status = AgentConfirmation.STATUS_EXECUTED
    confirmation.executed_at = timezone.now()
    confirmation.result_summary = (result_summary or "")[:500]
    confirmation.save(update_fields=["status", "executed_at", "result_summary"])


def mark_failed(confirmation: AgentConfirmation, error_code: str = "") -> None:
    if not can_transition(confirmation.status, AgentConfirmation.STATUS_FAILED):
        return
    confirmation.status = AgentConfirmation.STATUS_FAILED
    confirmation.error_code = (error_code or "")[:64]
    confirmation.save(update_fields=["status", "error_code"])


def expire_stale(now=None) -> int:
    now = now or timezone.now()
    return AgentConfirmation.objects.filter(
        status=AgentConfirmation.STATUS_PENDING,
        expires_at__lte=now,
    ).update(status=AgentConfirmation.STATUS_EXPIRED)


def find_stuck_executing(stuck_minutes: int = 5, now=None):
    """Return confirmations left in ``executing`` beyond ``stuck_minutes``.

    A record can get stuck if the process died after ``claim_for_execution`` but
    before the tool finished. These are surfaced for admin review; the
    dangerous operation is NEVER retried automatically.
    """
    now = now or timezone.now()
    cutoff = now - timedelta(minutes=max(stuck_minutes, 1))
    return AgentConfirmation.objects.filter(
        status=AgentConfirmation.STATUS_EXECUTING,
        executing_started_at__lt=cutoff,
    ).order_by("executing_started_at")


def fail_stuck_executing(stuck_minutes: int = 5, now=None) -> int:
    """Mark stuck ``executing`` records as ``failed`` (no automatic re-run).

    Returns the number of records transitioned. The operation itself is not
    retried; an admin must decide whether to re-issue the command.
    """
    stuck = list(find_stuck_executing(stuck_minutes, now).values_list("pk", flat=True))
    if not stuck:
        return 0
    return AgentConfirmation.objects.filter(pk__in=stuck).update(
        status=AgentConfirmation.STATUS_FAILED,
        error_code="stuck_executing_recovered",
    )


def idempotency_key(confirmation: AgentConfirmation) -> str:
    return f"agent-conf:{confirmation.token_hash[:32]}"
