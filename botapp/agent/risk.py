"""Risk classification for agent tools.

The Tool Registry is the single source of truth for a tool's risk level and
whether it requires confirmation. If the AI proposes a lower risk than the
registry declares, the registry value always wins (see ``resolve_risk``).
"""

from __future__ import annotations

LOW = "low"
MEDIUM = "medium"
HIGH = "high"

RISK_ORDER = {LOW: 0, MEDIUM: 1, HIGH: 2}


def normalize_risk(value: str | None) -> str:
    value = (value or "").strip().lower()
    return value if value in RISK_ORDER else LOW


def resolve_risk(registry_risk: str, ai_risk: str | None) -> str:
    """Return the stricter of the registry risk and the AI-proposed risk.

    The registry can only be *raised* by the AI, never lowered.
    """
    registry_risk = normalize_risk(registry_risk)
    ai_risk = normalize_risk(ai_risk)
    return registry_risk if RISK_ORDER[registry_risk] >= RISK_ORDER[ai_risk] else ai_risk
