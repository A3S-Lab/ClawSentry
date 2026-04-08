"""Opt-in smoke test for real a3s_code SDK HttpTransport session creation.

The Gateway runs in a child process to avoid the CS-028 same-process Uvicorn
thread topology that can produce false HTTP executor timeouts.
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import os
import socket
import tempfile

import httpx
import pytest

if not os.getenv("A3S_SDK_HTTP_SMOKE"):
    pytest.skip(
        "Skipping a3s-code HTTP SDK smoke test. Set A3S_SDK_HTTP_SMOKE=1 to run.",
        allow_module_level=True,
    )

try:
    from a3s_code import Agent, HttpTransport, SessionOptions  # type: ignore[import]
except ImportError:
    pytest.skip("a3s_code not installed", allow_module_level=True)


def _find_agent_config() -> str | None:
    if cfg := os.getenv("A3S_CONFIG"):
        if os.path.exists(cfg):
            return cfg
    candidates = [
        os.path.expanduser("~/cs-beta-test-a3s/agent.hcl"),
        os.path.expanduser("~/agent.hcl"),
        "agent.hcl",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def _require_config() -> str:
    cfg = _find_agent_config()
    if cfg is None:
        pytest.skip("No agent.hcl found for SDK HTTP smoke test")
    return cfg


def _reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return sock.getsockname()[1]


def _run_gateway_process(port: int, token: str, request_count) -> None:
    os.environ["CS_AUTH_TOKEN"] = token

    import uvicorn

    from clawsentry.gateway.server import SupervisionGateway, create_http_app

    gw = SupervisionGateway(trajectory_db_path=":memory:")
    app = create_http_app(gw)

    async def counting_app(scope, receive, send):
        if scope["type"] == "http" and scope.get("path") == "/ahp/a3s":
            with request_count.get_lock():
                request_count.value += 1
        await app(scope, receive, send)

    uvicorn.run(
        counting_app,
        host="127.0.0.1",
        port=port,
        log_level="error",
        access_log=False,
    )


@pytest.mark.asyncio
async def test_sdk_http_transport_handshake_hits_gateway(monkeypatch):
    cfg = _require_config()
    token = "sdk-http-smoke-token-1234567890abcdef"
    monkeypatch.setenv("CS_AUTH_TOKEN", token)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")

    port = _reserve_port()
    request_count = mp.Value("i", 0)
    process = mp.Process(
        target=_run_gateway_process,
        args=(port, token, request_count),
        daemon=True,
    )

    process.start()
    try:
        # Local loopback readiness check should not inherit user/system proxy.
        async with httpx.AsyncClient(trust_env=False) as client:
            for _ in range(50):
                try:
                    resp = await client.get(f"http://127.0.0.1:{port}/health")
                    if resp.status_code == 200:
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.1)
            else:
                raise AssertionError("HTTP gateway did not become ready in time")

        agent = Agent.create(cfg)
        with tempfile.TemporaryDirectory() as workspace:
            opts = SessionOptions()
            opts.ahp_transport = HttpTransport(
                f"http://127.0.0.1:{port}/ahp/a3s?token={token}"
            )
            _session = agent.session(workspace, opts, permissive=True)

        assert request_count.value >= 1
    finally:
        process.terminate()
        process.join(timeout=5.0)
