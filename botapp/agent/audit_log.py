"""Structured audit logging for agent requests.

Never stores tokens, keys, secrets, authorization headers or full prompts.
"""

from __future__ import annotations

from django.utils import timezone

from botapp.models import AgentAuditLog

_SENSITIVE_HINTS = ("token", "secret", "key", "authorization", "password", "cookie", "seed")


def sanitize_parameters(parameters: dict | None) -> dict:
    if not parameters:
        return {}
    clean: dict = {}
    for name, value in parameters.items():
        lname = str(name).lower()
        if any(hint in lname for hint in _SENSITIVE_HINTS):
            clean[name] = "[REDACTED]"
        elif isinstance(value, str):
            clean[name] = value[:200]
        else:
            clean[name] = value
    return clean


def record_audit(
    *,
    request_id: str,
    chat_id: int,
    requester_user_id: int,
    requester_role: str = "",
    original_command: str = "",
    parser_type: str = "",
    detected_intent: str = "",
    tool_name: str = "",
    parameters: dict | None = None,
    risk_level: str = "",
    confirmation_status: str = "",
    execution_status: str = "",
    error_code: str = "",
    duration_ms: int = 0,
    executed: bool = False,
) -> AgentAuditLog:
    return AgentAuditLog.objects.create(
        request_id=request_id,
        chat_id=chat_id,
        requester_user_id=requester_user_id,
        requester_role=requester_role[:16],
        original_command=(original_command or "")[:2000],
        parser_type=parser_type[:16],
        detected_intent=(detected_intent or "")[:64],
        tool_name=(tool_name or "")[:64],
        sanitized_parameters=sanitize_parameters(parameters),
        risk_level=(risk_level or "")[:8],
        confirmation_status=(confirmation_status or "")[:16],
        execution_status=(execution_status or "")[:16],
        error_code=(error_code or "")[:64],
        duration_ms=max(int(duration_ms), 0),
        executed_at=timezone.now() if executed else None,
    )
