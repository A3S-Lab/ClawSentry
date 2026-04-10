"""
OpenClaw Adapter — main entry composing all Phase 2 modules.

Design basis:
  - 03-openclaw-adapter-design.md section 3.4.1 (single-process embedded model)
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Optional

from ..gateway.models import CanonicalDecision, DecisionVerdict, EventType, RiskLevel

from .openclaw_approval import ApprovalStateMachine
from .openclaw_normalizer import OpenClawNormalizer
from .webhook_security import WebhookSecurityConfig

_RISK_LEVEL_MAP = {
    "low": RiskLevel.LOW,
    "medium": RiskLevel.MEDIUM,
    "high": RiskLevel.HIGH,
    "critical": RiskLevel.CRITICAL,
}

logger = logging.getLogger("openclaw-adapter")

RAW_RETENTION_SECONDS = 30 * 24 * 3600
SUMMARY_RETENTION_SECONDS = 180 * 24 * 3600


def _infer_risk_level(payload: dict[str, Any]) -> str:
    level = payload.get("risk_level")
    if isinstance(level, str):
        normalized = level.lower()
        if normalized in {"low", "medium", "high", "critical"}:
            return normalized

    command = str(payload.get("command", "")).lower()
    tool = str(payload.get("tool") or payload.get("tool_name") or "").lower()
    if "rm -rf" in command or "sudo" in command:
        return "high"
    if tool in {"bash", "shell", "exec", "sudo"}:
        return "medium"
    return "low"


class InvalidEventChannel:
    """In-memory invalid_event channel with alerts and review queue."""

    # Hard cap for in-memory lists to prevent unbounded growth under sustained
    # bursts within the retention window.
    MAX_RAW_EVENTS: int = 100_000
    MAX_SUMMARIES: int = 100_000
    MAX_ALERTS: int = 10_000
    MAX_REVIEW_QUEUE: int = 50_000

    def __init__(self) -> None:
        self._raw_events: list[dict[str, Any]] = []
        self._summaries: list[dict[str, Any]] = []
        self._alerts: list[dict[str, Any]] = []
        self._manual_review_queue: list[dict[str, Any]] = []
        self._event_ts: deque[float] = deque()
        self._invalid_ts: deque[float] = deque()
        self._last_alert_ts: dict[tuple[str, str], float] = {}

    def record_total_event(self, now: Optional[float] = None) -> None:
        now_ts = now or time.time()
        self._event_ts.append(now_ts)
        self._prune(now_ts)

    def record_invalid_event(
        self,
        *,
        event_type: str,
        payload: dict[str, Any],
        error: str,
        session_id: Optional[str],
        agent_id: Optional[str],
        risk_level: str,
        now: Optional[float] = None,
    ) -> None:
        now_ts = now or time.time()
        self._prune(now_ts)

        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "event_type": event_type,
                    "payload": payload,
                    "error": error,
                    "session_id": session_id,
                    "agent_id": agent_id,
                },
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        ).hexdigest()

        self._raw_events.append(
            {
                "event_type": event_type,
                "payload": payload,
                "session_id": session_id,
                "agent_id": agent_id,
                "error": error,
                "risk_level": risk_level,
                "fingerprint": fingerprint,
                "recorded_at_ts": now_ts,
                "expires_at_ts": now_ts + RAW_RETENTION_SECONDS,
            }
        )
        self._summaries.append(
            {
                "event_type": event_type,
                "fingerprint": fingerprint,
                "risk_level": risk_level,
                "error": error,
                "recorded_at_ts": now_ts,
                "expires_at_ts": now_ts + SUMMARY_RETENTION_SECONDS,
            }
        )
        self._invalid_ts.append(now_ts)

        if risk_level in {"medium", "high", "critical"}:
            self._manual_review_queue.append(
                {
                    "event_type": event_type,
                    "fingerprint": fingerprint,
                    "risk_level": risk_level,
                    "error": error,
                    "recorded_at_ts": now_ts,
                    "expires_at_ts": now_ts + SUMMARY_RETENTION_SECONDS,
                }
            )

        # Enforce hard caps after appending
        self._enforce_caps()
        self._evaluate_alerts(now_ts)

    @property
    def summaries(self) -> list[dict[str, Any]]:
        return list(self._summaries)

    @property
    def alerts(self) -> list[dict[str, Any]]:
        return list(self._alerts)

    @property
    def manual_review_queue(self) -> list[dict[str, Any]]:
        return list(self._manual_review_queue)

    def invalid_count(self) -> int:
        return len(self._raw_events)

    def _count_recent(self, ts_deque: deque[float], now_ts: float, window_s: int) -> int:
        cutoff = now_ts - window_s
        return sum(1 for ts in ts_deque if ts >= cutoff)

    def _evaluate_alerts(self, now_ts: float) -> None:
        invalid_1m = self._count_recent(self._invalid_ts, now_ts, 60)
        if invalid_1m > 20:
            self._emit_alert(
                metric="invalid_event_count_1m",
                severity="critical",
                value=invalid_1m,
                threshold=">20/min",
                now_ts=now_ts,
            )

        total_5m = self._count_recent(self._event_ts, now_ts, 300)
        invalid_5m = self._count_recent(self._invalid_ts, now_ts, 300)
        if total_5m > 0:
            rate_5m = invalid_5m / total_5m
            if rate_5m > 0.01:
                self._emit_alert(
                    metric="invalid_event_rate_5m",
                    severity="critical",
                    value=rate_5m,
                    threshold=">1%/5m",
                    now_ts=now_ts,
                )

        total_15m = self._count_recent(self._event_ts, now_ts, 900)
        invalid_15m = self._count_recent(self._invalid_ts, now_ts, 900)
        if total_15m > 0:
            rate_15m = invalid_15m / total_15m
            if 0.001 <= rate_15m <= 0.01:
                self._emit_alert(
                    metric="invalid_event_rate_15m",
                    severity="medium",
                    value=rate_15m,
                    threshold="0.1%-1%/15m",
                    now_ts=now_ts,
                )

    def _emit_alert(
        self,
        *,
        metric: str,
        severity: str,
        value: float,
        threshold: str,
        now_ts: float,
    ) -> None:
        dedupe_key = (metric, severity)
        last_ts = self._last_alert_ts.get(dedupe_key)
        if last_ts is not None and now_ts - last_ts < 60:
            return
        self._last_alert_ts[dedupe_key] = now_ts
        self._alerts.append(
            {
                "metric": metric,
                "severity": severity,
                "value": value,
                "threshold": threshold,
                "recorded_at_ts": now_ts,
            }
        )

    def _enforce_caps(self) -> None:
        """Drop oldest entries if any list exceeds its hard cap."""
        if len(self._raw_events) > self.MAX_RAW_EVENTS:
            self._raw_events = self._raw_events[-self.MAX_RAW_EVENTS:]
        if len(self._summaries) > self.MAX_SUMMARIES:
            self._summaries = self._summaries[-self.MAX_SUMMARIES:]
        if len(self._alerts) > self.MAX_ALERTS:
            self._alerts = self._alerts[-self.MAX_ALERTS:]
        if len(self._manual_review_queue) > self.MAX_REVIEW_QUEUE:
            self._manual_review_queue = self._manual_review_queue[-self.MAX_REVIEW_QUEUE:]

    def _prune(self, now_ts: float) -> None:
        cutoff_15m = now_ts - 900
        while self._event_ts and self._event_ts[0] < cutoff_15m:
            self._event_ts.popleft()
        while self._invalid_ts and self._invalid_ts[0] < cutoff_15m:
            self._invalid_ts.popleft()

        self._raw_events = [
            item for item in self._raw_events if item["expires_at_ts"] > now_ts
        ]
        self._summaries = [
            item for item in self._summaries if item["expires_at_ts"] > now_ts
        ]
        self._manual_review_queue = [
            item for item in self._manual_review_queue if item["expires_at_ts"] > now_ts
        ]
        self._enforce_caps()


@dataclass
class OpenClawAdapterConfig:
    """Configuration for the OpenClaw Adapter."""
    source_protocol_version: str = "1.0"
    git_short_sha: str = "unknown"
    profile_version: int = 1
    webhook_token: str = ""
    webhook_secret: Optional[str] = None
    require_https: bool = True
    max_retry_budget: int = 3
    gateway_http_url: str = "http://127.0.0.1:8080/ahp"
    gateway_uds_path: str = "/tmp/clawsentry.sock"


class OpenClawAdapter:
    """
    Main adapter composing normalizer + state machine + security + gateway client.

    Responsibilities:
    - Hook Collector: receive events, normalize, send to Gateway.
    - invalid_event channel: log and count failed events.
    - Approval state machine: track approval lifecycles.
    """

    def __init__(
        self,
        config: OpenClawAdapterConfig,
        gateway_client: Any,  # OpenClawGatewayClient (duck-typed)
        approval_client: Any = None,  # OpenClawApprovalClient (duck-typed)
    ) -> None:
        self.config = config
        self._gateway_client = gateway_client
        self._approval_client = approval_client

        self.normalizer = OpenClawNormalizer(
            source_protocol_version=config.source_protocol_version,
            git_short_sha=config.git_short_sha,
            profile_version=config.profile_version,
        )
        self.approval_sm = ApprovalStateMachine(
            max_retry_budget=config.max_retry_budget,
        )

        self._invalid_channel = InvalidEventChannel()

    @property
    def invalid_event_count(self) -> int:
        return self._invalid_channel.invalid_count()

    @property
    def invalid_event_summaries(self) -> list[dict[str, Any]]:
        return self._invalid_channel.summaries

    @property
    def invalid_event_alerts(self) -> list[dict[str, Any]]:
        return self._invalid_channel.alerts

    @property
    def manual_review_queue(self) -> list[dict[str, Any]]:
        return self._invalid_channel.manual_review_queue

    async def handle_hook_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        run_id: Optional[str] = None,
        source_seq: Optional[int] = None,
    ) -> Optional[CanonicalDecision]:
        """
        Handle a Hook event: normalize -> Gateway RPC -> return decision.

        Per 03 section 2.3: Hook failures only log, don't block main flow.
        Returns None for unmapped events or errors.
        """
        self._invalid_channel.record_total_event()

        # Normalize
        canonical_event = self.normalizer.normalize(
            event_type=event_type,
            payload=payload,
            session_id=session_id,
            agent_id=agent_id,
            run_id=run_id,
            source_seq=source_seq,
        )

        if canonical_event is None:
            self._invalid_channel.record_invalid_event(
                event_type=event_type,
                payload=payload,
                error="unmapped_or_invalid_event",
                session_id=session_id,
                agent_id=agent_id,
                risk_level=_infer_risk_level(payload),
            )
            return None

        # Wire ApprovalStateMachine for events with approval_id
        approval_id = payload.get("approval_id")
        approval_record = None
        if approval_id:
            approval_record = self.approval_sm.get(approval_id)
            if approval_record is None:
                risk_str = _infer_risk_level(payload)
                approval_record = self.approval_sm.create(
                    approval_id,
                    _RISK_LEVEL_MAP.get(risk_str, RiskLevel.LOW),
                )
            if approval_record.state.value == "requested":
                self.approval_sm.transition_to_pending(approval_record)

        # Send to Gateway
        try:
            decision = await self._gateway_client.request_decision(canonical_event)
            # Resolve approval based on gateway decision
            if approval_record and not approval_record.final:
                if decision.decision == DecisionVerdict.ALLOW:
                    self.approval_sm.resolve(approval_record, "allow-once")
                elif decision.decision == DecisionVerdict.BLOCK:
                    self.approval_sm.resolve(approval_record, "deny")

            # Dispatch enforcement callback to OpenClaw Gateway
            if (
                self._approval_client
                and approval_id
                and approval_record
                and approval_record.final
            ):
                from .openclaw_ws_client import map_verdict_to_openclaw

                # Build reason for user feedback
                reason = decision.reason if decision.reason else (
                    f"blocked by policy engine (risk={decision.risk_level.value})"
                    if decision.decision == DecisionVerdict.BLOCK
                    else f"allowed by policy engine (risk={decision.risk_level.value})"
                )

                openclaw_decision = map_verdict_to_openclaw(decision.decision)
                if openclaw_decision is not None:
                    try:
                        await self._approval_client.resolve(
                            approval_id, openclaw_decision, reason=reason
                        )
                    except Exception:
                        logger.exception(
                            "Enforcement callback failed for approval %s",
                            approval_id,
                        )

            return decision
        except Exception as e:
            logger.error(
                "Gateway request failed for event %s: %s",
                canonical_event.event_id, e,
            )
            self._invalid_channel.record_invalid_event(
                event_type=event_type,
                payload=payload,
                error=str(e),
                session_id=session_id,
                agent_id=agent_id,
                risk_level=_infer_risk_level(payload),
            )
            # Handle approval on gateway failure
            if approval_record and not approval_record.final:
                self.approval_sm.no_route(approval_record)
            # Fail-closed for pre_action, fail-open for others
            if canonical_event.event_type == EventType.PRE_ACTION:
                from ..gateway.policy_engine import make_fallback_decision
                has_high_danger = bool(
                    set(canonical_event.risk_hints or [])
                    & {"destructive_pattern", "shell_execution"}
                )
                return make_fallback_decision(
                    canonical_event,
                    risk_hints_contain_high_danger=has_high_danger,
                )
            return None

    async def handle_ws_approval_event(self, payload: dict[str, Any]) -> None:
        """Handle an inbound exec.approval.requested event from WS.

        Reuses the same normalize → gateway → decision pipeline as
        handle_hook_event, then auto-resolves via the approval client.
        """
        approval_id = payload.get("id", "")
        # Real OpenClaw events nest fields under payload.request
        request = payload.get("request", {})
        tool = request.get("tool", "") or payload.get("tool", "")
        command = request.get("command", "") or payload.get("command", "")
        session_id = request.get("sessionKey") or payload.get("sessionId")
        agent_id = request.get("agentId") or payload.get("agentId")

        logger.info(
            "WS approval event received: id=%s tool=%s command=%s",
            approval_id, tool, command,
        )

        hook_payload = {
            "approval_id": approval_id,
            "tool": tool,
            "tool_name": tool,
            "command": command,
            **{k: v for k, v in request.items()
               if k not in {"tool", "command", "sessionKey", "agentId"}},
            **{k: v for k, v in payload.items()
               if k not in {"id", "request", "tool", "command",
                             "sessionId", "agentId"}},
        }

        decision = await self.handle_hook_event(
            event_type="exec.approval.requested",
            payload=hook_payload,
            session_id=session_id,
            agent_id=agent_id,
        )

        if decision is not None:
            logger.info(
                "WS approval %s → %s (risk=%s)",
                approval_id, decision.decision.value, decision.risk_level.value,
            )
