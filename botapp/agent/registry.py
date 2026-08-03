"""Central, allowlisted registry of agent tools.

Only tools registered here can ever be executed. The AI receives a *derived*
description of these tools and may only reference them by name; unknown tool
names are rejected before any execution path runs.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from .errors import UnknownTool
from .risk import normalize_risk


@dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    input_schema: type[BaseModel]
    permission: str
    risk_level: str
    requires_confirmation: bool
    handler: Callable[..., Any]
    # Optional bot capability (see permissions.CAPABILITY_*) required to run.
    capability: str | None = None
    # How the target is resolved: "none", "member", "message".
    target_kind: str = "none"
    # Short Persian verb used in confirmation previews, e.g. "محدودکردن کاربر".
    human_verb: str = ""
    # AI may reference this tool. Read-only tools are usually deterministic-only
    # but exposing them to the AI is harmless.
    ai_selectable: bool = True

    def validate_params(self, raw: dict[str, Any]) -> BaseModel:
        from .errors import InvalidToolInput

        try:
            return self.input_schema.model_validate(raw or {})
        except Exception as exc:  # pydantic ValidationError and friends
            raise InvalidToolInput(
                "❌ پارامترهای این دستور نامعتبر است."
            ) from exc


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, AgentTool] = {}

    def register(self, tool: AgentTool) -> AgentTool:
        if tool.name in self._tools:
            raise ValueError(f"duplicate agent tool name: {tool.name}")
        object.__setattr__(tool, "risk_level", normalize_risk(tool.risk_level))
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> AgentTool:
        tool = self._tools.get((name or "").strip())
        if tool is None:
            raise UnknownTool()
        return tool

    def has(self, name: str) -> bool:
        return (name or "").strip() in self._tools

    def names(self) -> list[str]:
        return sorted(self._tools)

    def all(self) -> list[AgentTool]:
        return [self._tools[name] for name in sorted(self._tools)]

    def ai_catalog(self) -> list[dict[str, Any]]:
        """Serialise the allowlist for the AI prompt.

        Only names, descriptions and coarse metadata are exposed. Handlers,
        schemas and internal policy are never sent to the model.
        """
        catalog = []
        for tool in self.all():
            if not tool.ai_selectable:
                continue
            catalog.append(
                {
                    "tool": tool.name,
                    "description": tool.description,
                    "risk_level": tool.risk_level,
                    "target_kind": tool.target_kind,
                }
            )
        return catalog


# Process-wide singleton. Tool modules populate it on import.
registry = ToolRegistry()


def register_tool(**kwargs: Any) -> AgentTool:
    return registry.register(AgentTool(**kwargs))
