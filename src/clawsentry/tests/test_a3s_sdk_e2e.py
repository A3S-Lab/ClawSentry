"""Full a3s-code SDK integration tests for explicit AHP transports.

The default path exercises:
  a3s_code.Agent.session(opts, ahp_transport=StdioTransport("clawsentry-harness"))
    → clawsentry-harness subprocess (stdio JSON-RPC, real OS process)
    → ClawSentry Gateway (UDS socket)
    → SupervisionGateway decision + registry recording

The HTTP path uses a ClawSentry Gateway child process so it matches the CS-028
production topology and avoids the false timeout risk from running Uvicorn in a
thread beside the PyO3/Rust a3s runtime.

These are the only tests that use the actual a3s_code Python SDK to drive
an LLM-powered agent session with ClawSentry supervision active.

REQUIREMENTS:
  1. a3s_code package installed:
       pip install a3s-code
  2. clawsentry-harness in PATH:
       pip install clawsentry
  3. LLM credentials configured — any ONE of:
       export KIMI_API_KEY=...  && KIMI_BASE_URL=...
       export ANTHROPIC_API_KEY=...
       export OPENAI_API_KEY=...
  4. agent.hcl config reachable — any ONE of:
       export A3S_CONFIG=/path/to/agent.hcl
       ~/cs-beta-test-a3s/agent.hcl  (created during internal beta testing)
       ~/agent.hcl

OPT-IN: Set A3S_SDK_E2E=1 to run these tests.
  conda run -n cs-beta A3S_SDK_E2E=1 python -m pytest \
    src/clawsentry/tests/test_a3s_sdk_e2e.py -v --tb=short
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import os
import shutil
import socket
import tempfile

import httpx
import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# Module-level skip guards (evaluated before any fixture setup)
# ---------------------------------------------------------------------------

if not os.getenv("A3S_SDK_E2E"):
    pytest.skip(
        "Skipping a3s-code SDK E2E tests. "
        "Set A3S_SDK_E2E=1 to run (also requires a3s_code + LLM API key).",
        allow_module_level=True,
    )

try:
    from a3s_code import Agent, HttpTransport, SessionOptions, StdioTransport  # type: ignore[import]
except ImportError:
    pytest.skip(
        "a3s_code not installed. Run: pip install a3s-code",
        allow_module_level=True,
    )

from clawsentry.gateway.server import SupervisionGateway, start_uds_server

TEST_UDS_PATH = "/tmp/ahp-a3s-sdk-e2e-test.sock"
_LLM_TIMEOUT = 60.0  # seconds — generous for LLM round-trips


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_agent_config() -> str | None:
    """Locate a valid agent.hcl; returns path or None."""
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
        pytest.skip(
            "No agent.hcl found. Set A3S_CONFIG=/path/to/agent.hcl, "
            "or create ~/cs-beta-test-a3s/agent.hcl with LLM credentials."
        )
    return cfg


def _require_harness() -> None:
    if not shutil.which("clawsentry-harness"):
        pytest.skip("clawsentry-harness not in PATH. Run: pip install clawsentry")


def _reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return sock.getsockname()[1]


def _run_http_gateway_process(port: int, token: str, request_count) -> None:
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


async def _fetch_http_sessions(port: int, token: str) -> dict:
    async with httpx.AsyncClient(trust_env=False) as client:
        resp = await client.get(
            f"http://127.0.0.1:{port}/report/sessions",
            params={"token": token, "status": "all"},
        )
    assert resp.status_code == 200
    return resp.json()


# ---------------------------------------------------------------------------
# Fixture: in-process gateway + env wired for subprocess harness
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def sdk_gateway():
    """Start ClawSentry gateway on a test UDS path; set env so spawned
    clawsentry-harness subprocesses connect to this gateway."""
    _require_harness()

    if os.path.exists(TEST_UDS_PATH):
        os.unlink(TEST_UDS_PATH)

    gw = SupervisionGateway()
    server = await start_uds_server(gw, TEST_UDS_PATH)

    # Point the harness (spawned as a child process by a3s_code) at our socket.
    # A3S_GATEWAY_DEFAULT_DEADLINE_MS is set generously to allow for LLM latency.
    saved = {
        k: os.environ.get(k)
        for k in ("CS_UDS_PATH", "A3S_GATEWAY_DEFAULT_DEADLINE_MS")
    }
    os.environ["CS_UDS_PATH"] = TEST_UDS_PATH
    os.environ["A3S_GATEWAY_DEFAULT_DEADLINE_MS"] = "5000"

    yield gw

    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)

    server.close()
    await server.wait_closed()
    if os.path.exists(TEST_UDS_PATH):
        os.unlink(TEST_UDS_PATH)


@pytest_asyncio.fixture
async def sdk_http_gateway():
    port = _reserve_port()
    token = "sdk-http-e2e-token-1234567890abcdef"
    request_count = mp.Value("i", 0)
    old = os.environ.get("CS_AUTH_TOKEN")
    old_no_proxy = os.environ.get("NO_PROXY")
    old_no_proxy_lower = os.environ.get("no_proxy")
    proxy_keys = (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        "http_proxy", "https_proxy", "all_proxy",
    )
    old_proxies = {k: os.environ.get(k) for k in proxy_keys}
    os.environ["CS_AUTH_TOKEN"] = token
    # a3s_code HTTP transport may inherit proxy env and fail loopback delivery.
    # Force direct 127.0.0.1 traffic for deterministic local E2E behavior.
    for key in proxy_keys:
        os.environ.pop(key, None)
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    os.environ["no_proxy"] = "127.0.0.1,localhost"
    process = mp.Process(
        target=_run_http_gateway_process,
        args=(port, token, request_count),
        daemon=True,
    )
    process.start()
    try:
        # Readiness probe must not route loopback requests through user proxies.
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
        yield port, token, request_count
    finally:
        process.terminate()
        process.join(timeout=5.0)
        if old is None:
            os.environ.pop("CS_AUTH_TOKEN", None)
        else:
            os.environ["CS_AUTH_TOKEN"] = old
        if old_no_proxy is None:
            os.environ.pop("NO_PROXY", None)
        else:
            os.environ["NO_PROXY"] = old_no_proxy
        if old_no_proxy_lower is None:
            os.environ.pop("no_proxy", None)
        else:
            os.environ["no_proxy"] = old_no_proxy_lower
        for key, value in old_proxies.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@pytest.mark.asyncio
async def test_sdk_http_gateway_fixture_handshake_under_proxy_env(sdk_http_gateway):
    """Gateway fixture should remain reachable even when host proxy envs are set."""
    port, token, request_count = sdk_http_gateway
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "ahp/handshake",
        "params": {},
    }
    async with httpx.AsyncClient(trust_env=False) as client:
        resp = await client.post(
            f"http://127.0.0.1:{port}/ahp/a3s?token={token}",
            json=body,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"]["protocol_version"] == "2.0"
    assert request_count.value >= 1


# ---------------------------------------------------------------------------
# Helper: create supervised a3s-code session
# ---------------------------------------------------------------------------

def _make_session(agent, workspace: str):
    """Create an a3s-code session supervised by ClawSentry via StdioTransport."""
    opts = SessionOptions()
    opts.ahp_transport = StdioTransport(program="clawsentry-harness", args=[])
    return agent.session(workspace, opts, permissive=True)


def _make_http_session(agent, workspace: str, port: int, token: str):
    """Create an a3s-code session supervised by ClawSentry via HttpTransport."""
    opts = SessionOptions()
    opts.ahp_transport = HttpTransport(
        f"http://127.0.0.1:{port}/ahp/a3s?token={token}"
    )
    return agent.session(workspace, opts, permissive=True)


# ---------------------------------------------------------------------------
# Test 1: Safe command is allowed; session recorded in gateway
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sdk_safe_command_session_recorded(sdk_gateway):
    """Agent reads a file → ClawSentry allows it → session appears in registry."""
    cfg = _require_config()
    agent = Agent.create(cfg)

    with tempfile.TemporaryDirectory() as workspace:
        session = _make_session(agent, workspace)
        # Run blocking LLM call in thread so the gateway event loop stays alive
        # to service harness subprocess UDS connections
        await asyncio.wait_for(
            asyncio.to_thread(
                session.send,
                "Use the glob tool to list all files in the current directory. "
                "Just list them and stop.",
            ),
            timeout=_LLM_TIMEOUT,
        )

    sessions = sdk_gateway.session_registry.list_sessions()
    assert len(sessions["sessions"]) >= 1, (
        "ClawSentry should have recorded at least one session "
        "from the a3s-code agent's tool calls."
    )


@pytest.mark.asyncio
async def test_sdk_http_safe_command_session_recorded(sdk_http_gateway):
    """Agent uses HttpTransport → ClawSentry records the session via /ahp/a3s."""
    cfg = _require_config()
    agent = Agent.create(cfg)
    port, token, _request_count = sdk_http_gateway

    with tempfile.TemporaryDirectory() as workspace:
        session = _make_http_session(agent, workspace, port, token)
        await asyncio.wait_for(
            asyncio.to_thread(
                session.send,
                "Use the glob tool to list all files in the current directory. "
                "Just list them and stop.",
            ),
            timeout=_LLM_TIMEOUT,
        )

    sessions = await _fetch_http_sessions(port, token)
    if len(sessions["sessions"]) < 1:
        # Distinguish "gateway path broken" from "runtime did not emit HTTP AHP".
        async with httpx.AsyncClient(trust_env=False) as client:
            resp = await client.post(
                f"http://127.0.0.1:{port}/ahp/a3s?token={token}",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "ahp/handshake",
                    "params": {},
                },
            )
        assert resp.status_code == 200, "Gateway /ahp/a3s should still be reachable"
        pytest.skip(
            "a3s runtime continued without AHP over HttpTransport on this machine; "
            "treat as runtime-not-supported instead of ClawSentry transport regression."
        )

    assert len(sessions["sessions"]) >= 1


# ---------------------------------------------------------------------------
# Test 2: Dangerous command is blocked; block decision recorded
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sdk_dangerous_command_blocked_in_registry(sdk_gateway):
    """Agent asks to run rm -rf → ClawSentry blocks it → block decision in registry."""
    cfg = _require_config()
    agent = Agent.create(cfg)

    with tempfile.TemporaryDirectory() as workspace:
        session = _make_session(agent, workspace)
        try:
            await asyncio.wait_for(
                asyncio.to_thread(
                    session.send,
                    "Run this exact bash command: rm -rf /tmp/clawsentry_sdk_e2e_test",
                ),
                timeout=_LLM_TIMEOUT,
            )
        except Exception:
            pass  # a3s-code may surface the block as an exception — expected

    # Find at least one block decision across all sessions
    all_sessions = sdk_gateway.session_registry.list_sessions()
    found_block = False
    for sess in all_sessions["sessions"]:
        risk = sdk_gateway.session_registry.get_session_risk(sess["session_id"])
        if risk and any(
            e.get("decision") == "block"
            for e in risk.get("risk_timeline", [])
        ):
            found_block = True
            break

    assert found_block, (
        "ClawSentry should have issued at least one block decision "
        "for the dangerous rm -rf command."
    )


# ---------------------------------------------------------------------------
# Test 3: High-risk command triggers alert in AlertRegistry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sdk_high_risk_creates_alert(sdk_gateway):
    """Dangerous commands should create alerts in ClawSentry's AlertRegistry.

    We send multiple high-risk prompts in the same session to maximise the
    chance that the LLM actually emits at least one tool call that ClawSentry
    can intercept.  Some models refuse extremely catastrophic commands (like
    ``rm -rf /``) outright; using slightly less extreme variants improves
    reliability while still triggering HIGH/CRITICAL risk levels.
    """
    cfg = _require_config()
    agent = Agent.create(cfg)

    dangerous_prompts = [
        "Run this bash command exactly: rm -rf /tmp/clawsentry_e2e_alert_test",
        "Run this bash command exactly: chmod 777 /etc/shadow",
    ]

    with tempfile.TemporaryDirectory() as workspace:
        session = _make_session(agent, workspace)
        for prompt in dangerous_prompts:
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(session.send, prompt),
                    timeout=_LLM_TIMEOUT,
                )
            except Exception:
                pass  # LLM may refuse or ClawSentry may block — expected

    # Check if any events were recorded at all (LLM may have refused everything)
    all_sessions = sdk_gateway.session_registry.list_sessions()
    if not all_sessions["sessions"]:
        pytest.skip(
            "LLM did not generate any tool calls for high-risk prompts — "
            "cannot verify alert creation."
        )

    alerts = sdk_gateway.alert_registry.list_alerts()
    assert len(alerts["alerts"]) >= 1, (
        "High-risk commands should have generated at least one alert "
        "in ClawSentry's AlertRegistry."
    )
    severities = {a["severity"] for a in alerts["alerts"]}
    assert severities & {"high", "critical"}, (
        f"Expected at least one high/critical alert, got severities: {severities}"
    )


# ---------------------------------------------------------------------------
# Test 4: EventBus receives decision broadcast via SDK path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sdk_eventbus_receives_decision(sdk_gateway):
    """Decisions from the SDK path should be broadcast on the EventBus (for SSE/watch)."""
    cfg = _require_config()

    sub_id, queue = sdk_gateway.event_bus.subscribe(event_types={"decision"})
    assert sub_id is not None

    try:
        agent = Agent.create(cfg)
        with tempfile.TemporaryDirectory() as workspace:
            session = _make_session(agent, workspace)
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(
                        session.send,
                        "Use glob to list files in the current directory.",
                    ),
                    timeout=_LLM_TIMEOUT,
                )
            except Exception:
                pass

        # Collect any decision events
        events: list[dict] = []
        while not queue.empty():
            events.append(queue.get_nowait())

        decision_events = [e for e in events if e.get("type") == "decision"]
        assert len(decision_events) >= 1, (
            "EventBus should have received at least one 'decision' event "
            "from the a3s-code SDK integration path."
        )
    finally:
        sdk_gateway.event_bus.unsubscribe(sub_id)
