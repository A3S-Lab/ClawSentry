"""Mock OpenClaw Gateway WebSocket server for integration testing.

Implements the minimal OpenClaw Gateway protocol:
- connect.challenge → connect → hello-ok handshake
- exec.approval.resolve → {ok: true}
- exec.approval.requested event broadcasting to operator clients
- Tracks resolved approvals for test assertions
"""
from __future__ import annotations

import json
import uuid
from typing import Any

import websockets


class MockOpenClawGateway:
    """Minimal mock of OpenClaw Gateway WebSocket server."""

    def __init__(self, *, require_token: str = "test-token") -> None:
        self.require_token = require_token
        self.resolved_approvals: list[dict[str, Any]] = []
        self._server: Any = None
        self._port: int = 0
        self._operator_clients: list[Any] = []

    @property
    def port(self) -> int:
        return self._port

    @property
    def ws_url(self) -> str:
        return f"ws://127.0.0.1:{self._port}"

    async def start(self) -> None:
        self._server = await websockets.serve(
            self._handler,
            "127.0.0.1",
            0,  # OS-assigned port
        )
        for sock in self._server.sockets:
            addr = sock.getsockname()
            self._port = addr[1]
            break

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        self._operator_clients.clear()

    async def broadcast_approval_request(
        self,
        approval_id: str,
        tool: str = "bash",
        command: str = "",
        **extra: Any,
    ) -> None:
        """Broadcast an exec.approval.requested event to all connected operator clients."""
        event = {
            "type": "event",
            "event": "exec.approval.requested",
            "payload": {
                "id": approval_id,
                "tool": tool,
                "command": command,
                **extra,
            },
        }
        frame = json.dumps(event)
        closed = []
        for ws in self._operator_clients:
            try:
                await ws.send(frame)
            except websockets.exceptions.ConnectionClosed:
                closed.append(ws)
        for ws in closed:
            self._operator_clients.remove(ws)

    async def _handler(self, websocket: Any) -> None:
        # Send challenge
        challenge = {
            "type": "event",
            "event": "connect.challenge",
            "payload": {"nonce": uuid.uuid4().hex, "ts": 1234567890000},
        }
        await websocket.send(json.dumps(challenge))

        # Wait for connect request
        connect_raw = await websocket.recv()
        connect_msg = json.loads(connect_raw)

        if connect_msg.get("method") != "connect":
            await websocket.close()
            return

        # Verify token
        token = connect_msg.get("params", {}).get("auth", {}).get("token", "")
        if token != self.require_token:
            error_resp = {
                "type": "res",
                "id": connect_msg.get("id"),
                "ok": False,
                "error": {"code": "AUTH_FAILED", "message": "invalid token"},
            }
            await websocket.send(json.dumps(error_resp))
            await websocket.close()
            return

        # Send hello-ok
        hello = {
            "type": "res",
            "id": connect_msg.get("id"),
            "ok": True,
            "payload": {
                "type": "hello-ok",
                "protocol": 3,
                "auth": {
                    "role": "operator",
                    "scopes": [
                        "operator.read",
                        "operator.write",
                        "operator.approvals",
                    ],
                },
            },
        }
        await websocket.send(json.dumps(hello))

        # Register as operator client for event broadcasting
        self._operator_clients.append(websocket)

        # Handle subsequent messages
        try:
            async for message in websocket:
                msg = json.loads(message)
                if msg.get("method") == "exec.approval.resolve":
                    params = msg.get("params", {})
                    self.resolved_approvals.append(params)
                    resp = {
                        "type": "res",
                        "id": msg.get("id"),
                        "ok": True,
                        "payload": {"ok": True},
                    }
                    await websocket.send(json.dumps(resp))
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            if websocket in self._operator_clients:
                self._operator_clients.remove(websocket)
