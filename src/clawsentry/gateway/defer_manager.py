"""DEFER decision timeout manager.

Tracks pending DEFER requests and auto-resolves them based on
configured timeout action (block or allow) from DetectionConfig.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class _PendingDefer:
    event: asyncio.Event = field(default_factory=asyncio.Event)
    decision: str = ""
    reason: str = ""


class DeferManager:
    """Manage DEFER request lifecycle with configurable timeout."""

    def __init__(
        self,
        timeout_action: str = "block",
        timeout_s: float = 300.0,
    ) -> None:
        self.timeout_action = timeout_action
        self.timeout_s = timeout_s
        self._pending: dict[str, _PendingDefer] = {}

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def is_pending(self, request_id: str) -> bool:
        return request_id in self._pending

    def register_defer(self, request_id: str) -> None:
        """Register a new DEFER request for tracking."""
        self._pending[request_id] = _PendingDefer()

    def resolve_defer(self, request_id: str, decision: str, reason: str) -> None:
        """Resolve a pending DEFER with an explicit decision."""
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return
        pending.decision = decision
        pending.reason = reason
        pending.event.set()

    async def wait_for_resolution(
        self, request_id: str,
    ) -> tuple[str, str]:
        """Wait for resolution or timeout. Returns (decision, reason)."""
        pending = self._pending.get(request_id)
        if pending is None:
            return self.timeout_action, "request not found"

        try:
            await asyncio.wait_for(pending.event.wait(), timeout=self.timeout_s)
            return pending.decision, pending.reason
        except asyncio.TimeoutError:
            reason = (
                f"DEFER timeout ({self.timeout_s}s): "
                f"auto-{self.timeout_action}"
            )
            logger.warning(
                "DEFER %s timed out, action=%s", request_id, self.timeout_action,
            )
            return self.timeout_action, reason
        finally:
            self._pending.pop(request_id, None)
