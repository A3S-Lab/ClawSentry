"""Standard a3s-code AHP stdio harness bridged to ClawSentry Gateway."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from typing import Any, Optional

try:
    from .a3s_adapter import A3SCodeAdapter
    from ..gateway.models import CanonicalDecision, DecisionVerdict
except ImportError:
    # Support direct script execution:
    # python src/clawsentry/adapters/a3s_gateway_harness.py
    from pathlib import Path

    _SRC_ROOT = str(Path(__file__).resolve().parent.parent.parent)
    if _SRC_ROOT not in sys.path:
        sys.path.insert(0, _SRC_ROOT)
    from clawsentry.adapters.a3s_adapter import A3SCodeAdapter  # type: ignore[no-redef]
    from clawsentry.gateway.models import CanonicalDecision, DecisionVerdict  # type: ignore[no-redef]

logger = logging.getLogger("a3s-gateway-harness")

_EVENT_TO_HOOK: dict[str, str] = {
    "pre_action": "PreToolUse",
    "pre_tool_use": "PreToolUse",
    "post_action": "PostToolUse",
    "post_tool_use": "PostToolUse",
    "pre_prompt": "PrePrompt",
    "generate_start": "GenerateStart",
    "session_start": "SessionStart",
    "session_end": "SessionEnd",
    "error": "OnError",
}


import re as _re

_CAMEL_RE1 = _re.compile(r"(?<=[a-z0-9])([A-Z])")
_CAMEL_RE2 = _re.compile(r"(?<=[A-Z])([A-Z][a-z])")


def _camel_to_snake(name: str) -> str:
    """Convert CamelCase to snake_case: PreToolUse -> pre_tool_use."""
    s = _CAMEL_RE1.sub(r"_\1", name)
    s = _CAMEL_RE2.sub(r"_\1", s)
    return s.lower()


def _log_stderr(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [a3s-gateway-harness] {msg}", file=sys.stderr, flush=True)


def _resolve_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        payload = dict(raw)
    else:
        payload = {}

    if "arguments" not in payload and isinstance(payload.get("args"), dict):
        payload["arguments"] = payload["args"]

    if "tool" not in payload and isinstance(payload.get("tool_name"), str):
        payload["tool"] = payload["tool_name"]

    args = payload.get("arguments")
    if isinstance(args, dict):
        for key in ("command", "path", "target", "file_path"):
            if key in args and key not in payload:
                payload[key] = args[key]

    return payload


def _resolve_string(*values: Any) -> Optional[str]:
    for v in values:
        if isinstance(v, str) and v.strip():
            return v
    return None


def _decision_to_ahp_result(decision: CanonicalDecision) -> dict[str, Any]:
    action = "continue"
    if decision.decision == DecisionVerdict.BLOCK:
        action = "block"
    elif decision.decision == DecisionVerdict.MODIFY:
        action = "modify"
    elif decision.decision == DecisionVerdict.DEFER:
        action = "defer"

    result: dict[str, Any] = {
        "action": action,
        "decision": decision.decision.value,
        "reason": decision.reason,
        "metadata": {
            "source": "clawsentry-gateway-harness",
            "policy_id": decision.policy_id,
            "risk_level": decision.risk_level.value,
            "decision_source": decision.decision_source.value,
            "final": decision.final,
        },
    }
    if decision.modified_payload is not None:
        result["modified_payload"] = decision.modified_payload
    if decision.retry_after_ms is not None:
        result["retry_after_ms"] = decision.retry_after_ms

    return result


class A3SGatewayHarness:
    """Bridge AHP stdio requests to ClawSentry Gateway decisions."""

    def __init__(
        self,
        adapter: A3SCodeAdapter,
        *,
        protocol_version: str = "2.0",
        harness_name: str = "a3s-gateway-harness",
        harness_version: str = "1.0.0",
        default_session_id: str = "ahp-session",
        default_agent_id: str = "ahp-agent",
        async_mode: bool = False,
    ) -> None:
        self.adapter = adapter
        self.protocol_version = protocol_version
        self.harness_name = harness_name
        self.harness_version = harness_version
        self.default_session_id = default_session_id
        self.default_agent_id = default_agent_id
        self.async_mode = async_mode

    def _handshake_result(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "harness_info": {
                "name": self.harness_name,
                "version": self.harness_version,
                "capabilities": [
                    "pre_action",
                    "post_action",
                    "pre_prompt",
                    "session",
                    "error",
                ],
            },
        }

    async def _handle_event(self, params: dict[str, Any]) -> dict[str, Any]:
        event_type_raw = str(params.get("event_type", "")).strip().lower()
        payload = _resolve_payload(params.get("payload"))

        hook_type = _EVENT_TO_HOOK.get(event_type_raw)
        if hook_type is None:
            return {
                "action": "continue",
                "decision": "allow",
                "reason": f"Unmapped event_type: {event_type_raw or 'unknown'}",
                "metadata": {"source": "clawsentry-gateway-harness"},
            }

        session_id = _resolve_string(
            params.get("session_id"),
            params.get("sessionKey"),
            payload.get("session_id"),
            payload.get("sessionKey"),
            self.default_session_id,
        )
        agent_id = _resolve_string(
            params.get("agent_id"),
            params.get("agentId"),
            payload.get("agent_id"),
            payload.get("agentId"),
            self.default_agent_id,
        )

        evt = self.adapter.normalize_hook_event(
            hook_type,
            payload,
            session_id=session_id,
            agent_id=agent_id,
        )
        if evt is None:
            return {
                "action": "continue",
                "decision": "allow",
                "reason": f"Event filtered: hook_type={hook_type}",
                "metadata": {"source": "clawsentry-gateway-harness"},
            }

        decision = await self.adapter.request_decision(evt)
        return _decision_to_ahp_result(decision)

    def _convert_native_hook(self, msg: dict[str, Any]) -> dict[str, Any]:
        """Convert native Claude Code hook JSON to harness event params."""
        params: dict[str, Any] = {}

        # event_type can be top-level or inferred from hook_type
        event_type = msg.get("event_type") or msg.get("hook_type", "")
        # Normalize CamelCase: PreToolUse -> pre_tool_use
        if event_type and not event_type.islower():
            event_type = _camel_to_snake(event_type)
        params["event_type"] = event_type

        # payload can be nested or the msg itself is the payload
        payload = msg.get("payload")
        if payload is None:
            payload = {k: v for k, v in msg.items() if k not in ("event_type", "hook_type")}
        params["payload"] = payload

        # Lift session_id / agent_id to params level for _handle_event
        for key in ("session_id", "agent_id"):
            if key in msg:
                params[key] = msg[key]
            elif isinstance(payload, dict) and key in payload:
                params[key] = payload[key]

        return params

    async def dispatch_async(self, msg: dict[str, Any]) -> Optional[dict[str, Any]]:
        req_id = msg.get("id")
        method = msg.get("method")

        # --- JSON-RPC 2.0 path (a3s-code AHP protocol) ---
        if method is not None:
            params_raw = msg.get("params")
            params = params_raw if isinstance(params_raw, dict) else {}

            if method == "ahp/handshake":
                if req_id is None:
                    return None
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": self._handshake_result(),
                }

            try:
                result = await self._handle_event(params)
            except Exception:  # noqa: BLE001
                logger.exception("Failed handling AHP event")
                if req_id is None:
                    return None
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32000,
                        "message": "AHP harness internal error",
                        "data": {"detail": "Internal harness error. Check server logs for details."},
                    },
                }

            if req_id is None:
                return None

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": result,
            }

        # --- Native hook path (Claude Code / direct hook command) ---
        params = self._convert_native_hook(msg)
        if self.async_mode:
            # Dispatch in background — don't block the hook
            asyncio.ensure_future(self._async_dispatch(params))
            return {"result": {"action": "continue", "reason": "async: event dispatched"}}
        try:
            result = await self._handle_event(params)
        except Exception:  # noqa: BLE001
            logger.exception("Failed handling native hook event")
            return {"result": {"action": "continue", "reason": "harness internal error"}}
        return {"result": result}

    async def _async_dispatch(self, params: dict[str, Any]) -> None:
        """Background dispatch to gateway. Errors are logged, not raised."""
        try:
            await self._handle_event(params)
        except Exception:  # noqa: BLE001
            logger.debug("Async dispatch failed (non-blocking)", exc_info=True)

    def run_stdio(self) -> None:
        _log_stderr("harness started")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            for raw_line in sys.stdin:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError as exc:
                    _log_stderr(f"invalid json: {exc}")
                    continue

                response = loop.run_until_complete(self.dispatch_async(msg))
                if response is not None:
                    print(json.dumps(response, ensure_ascii=False), flush=True)
        finally:
            # Wait for any --async background tasks to complete
            pending = asyncio.all_tasks(loop)
            if pending:
                loop.run_until_complete(asyncio.wait(pending, timeout=5.0))
            loop.close()


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a3s-code AHP stdio harness bridged to ClawSentry Gateway."
    )
    parser.add_argument(
        "--uds-path",
        default=os.getenv("CS_UDS_PATH", "/tmp/clawsentry.sock"),
    )
    parser.add_argument(
        "--default-deadline-ms",
        type=int,
        default=int(os.getenv("A3S_GATEWAY_DEFAULT_DEADLINE_MS", "4500")),
    )
    parser.add_argument(
        "--max-rpc-retries",
        type=int,
        default=int(os.getenv("A3S_GATEWAY_MAX_RPC_RETRIES", "1")),
    )
    parser.add_argument(
        "--retry-backoff-ms",
        type=int,
        default=int(os.getenv("A3S_GATEWAY_RETRY_BACKOFF_MS", "50")),
    )
    parser.add_argument(
        "--framework",
        default=os.getenv("CS_FRAMEWORK", "a3s-code"),
        help="Source framework identifier (default: a3s-code).",
    )
    parser.add_argument(
        "--default-session-id",
        default=os.getenv("A3S_GATEWAY_DEFAULT_SESSION_ID", "ahp-session"),
    )
    parser.add_argument(
        "--default-agent-id",
        default=os.getenv("A3S_GATEWAY_DEFAULT_AGENT_ID", "ahp-agent"),
    )
    parser.add_argument(
        "--async",
        dest="async_mode",
        action="store_true",
        default=False,
        help="Return immediately for native hook events (fire-and-forget).",
    )
    return parser


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    adapter = A3SCodeAdapter(
        uds_path=args.uds_path,
        default_deadline_ms=args.default_deadline_ms,
        max_rpc_retries=args.max_rpc_retries,
        retry_backoff_ms=args.retry_backoff_ms,
        source_framework=args.framework,
    )
    harness = A3SGatewayHarness(
        adapter,
        default_session_id=args.default_session_id,
        default_agent_id=args.default_agent_id,
        async_mode=args.async_mode,
    )
    harness.run_stdio()


if __name__ == "__main__":
    main()
