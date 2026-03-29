"""Codex event normalization adapter.

Normalizes Codex tool call events (function_call, function_call_output,
session_meta, session_end) into CanonicalEvent for ClawSentry Gateway evaluation.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ..gateway.models import (
    CanonicalEvent,
    EventType,
    FrameworkMeta,
    NormalizationMeta,
    extract_risk_hints,
)
from .a3s_adapter import infer_content_origin
from .event_id import generate_event_id

logger = logging.getLogger(__name__)

# Codex hook_type → EventType mapping
_HOOK_TYPE_MAP: dict[str, EventType] = {
    "function_call": EventType.PRE_ACTION,
    "function_call_output": EventType.POST_ACTION,
    "session_meta": EventType.SESSION,
    "session_end": EventType.SESSION,
}


class CodexAdapter:
    """Normalize Codex events → CanonicalEvent."""

    _DEFAULT_SOURCE_FRAMEWORK = "codex"

    def __init__(
        self,
        source_framework: str | None = None,
    ) -> None:
        self.source_framework = source_framework or self._DEFAULT_SOURCE_FRAMEWORK

    def normalize_hook_event(
        self,
        hook_type: str,
        payload: dict[str, Any],
        session_id: str | None = None,
        agent_id: str | None = None,
    ) -> CanonicalEvent | None:
        """Normalize a Codex event to CanonicalEvent."""
        event_type = _HOOK_TYPE_MAP.get(hook_type)
        if event_type is None:
            logger.debug("Unknown Codex hook_type: %s", hook_type)
            return None

        # Extract tool name and arguments
        tool_name = payload.get("name") or payload.get("tool_name")
        arguments = payload.get("arguments", {})

        # Build unified payload
        unified_payload: dict[str, Any] = {**payload}
        if arguments and isinstance(arguments, dict):
            unified_payload.update(arguments)

        # Risk hints (reuse shared utility)
        command_str = str(arguments.get("command", "")) if isinstance(arguments, dict) else ""
        risk_hints = extract_risk_hints(tool_name, command_str)

        # Content origin
        origin = infer_content_origin(tool_name, unified_payload)
        unified_payload["_clawsentry_meta"] = {"content_origin": origin}

        # Event subtype
        if event_type == EventType.SESSION:
            subtype = "session:start" if hook_type == "session_meta" else "session:end"
        elif event_type == EventType.PRE_ACTION:
            subtype = "pre_action"
        else:
            subtype = "post_action"

        # Generate event ID
        now = datetime.now(timezone.utc)
        event_id = generate_event_id(
            self.source_framework, session_id or "unknown",
            subtype, now.isoformat(), unified_payload,
        )

        # Session/agent fallbacks
        effective_session = session_id or f"unknown_session:{self.source_framework}"
        effective_agent = agent_id or f"unknown_agent:{self.source_framework}"
        missing: list[str] = []
        if session_id is None:
            missing.append("session_id")
        if agent_id is None:
            missing.append("agent_id")

        norm_meta = NormalizationMeta(
            rule_id="codex-hook-direct-map",
            inferred=False,
            confidence="high",
            raw_event_type=hook_type,
            raw_event_source=self.source_framework,
            missing_fields=missing,
            fallback_rule="sentinel_value" if missing else None,
        )

        return CanonicalEvent(
            schema_version="ahp.1.0",
            event_id=event_id,
            trace_id=payload.get("call_id", event_id),
            event_type=event_type,
            session_id=effective_session,
            agent_id=effective_agent,
            source_framework=self.source_framework,
            occurred_at=now.isoformat(),
            payload=unified_payload,
            tool_name=tool_name,
            risk_hints=risk_hints,
            event_subtype=subtype,
            framework_meta=FrameworkMeta(normalization=norm_meta),
        )

