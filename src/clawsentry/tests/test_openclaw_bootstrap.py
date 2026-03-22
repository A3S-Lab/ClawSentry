"""Tests for OpenClaw bootstrap factory (P1-1 unified config assembly)."""

import pytest

from fastapi.testclient import TestClient

from clawsentry.adapters.openclaw_bootstrap import (
    OpenClawBootstrapConfig,
    build_openclaw_runtime,
    build_openclaw_runtime_from_env,
    create_openclaw_webhook_app,
)


def test_from_env_reads_expected_values(monkeypatch):
    monkeypatch.setenv("OPENCLAW_WEBHOOK_TOKEN", "tok-from-env")
    monkeypatch.setenv("OPENCLAW_WEBHOOK_SECRET", "sec-from-env")
    monkeypatch.setenv("OPENCLAW_WEBHOOK_REQUIRE_HTTPS", "true")
    monkeypatch.setenv("OPENCLAW_WEBHOOK_MAX_BODY_BYTES", "2048")
    monkeypatch.setenv("OPENCLAW_SOURCE_PROTOCOL_VERSION", "2.0")
    monkeypatch.setenv("OPENCLAW_MAPPING_GIT_SHA", "abc1234")
    monkeypatch.setenv("OPENCLAW_MAPPING_PROFILE_VERSION", "9")
    monkeypatch.setenv("CS_HTTP_HOST", "10.0.0.8")
    monkeypatch.setenv("CS_HTTP_PORT", "18080")
    monkeypatch.setenv("CS_UDS_PATH", "/tmp/test-openclaw.sock")
    monkeypatch.setenv("CS_AUTH_TOKEN", "auth-from-env")
    monkeypatch.setenv("OPENCLAW_GATEWAY_TRANSPORT_PREFERENCE", "http_first")

    cfg = OpenClawBootstrapConfig.from_env()

    assert cfg.webhook_token == "tok-from-env"
    assert cfg.webhook_secret == "sec-from-env"
    assert cfg.webhook_require_https is True
    assert cfg.webhook_max_body_bytes == 2048
    assert cfg.source_protocol_version == "2.0"
    assert cfg.git_short_sha == "abc1234"
    assert cfg.profile_version == 9
    assert cfg.gateway_http_url == "http://10.0.0.8:18080/ahp"
    assert cfg.gateway_uds_path == "/tmp/test-openclaw.sock"
    assert cfg.gateway_auth_token == "auth-from-env"
    assert cfg.gateway_transport_preference == "http_first"


def test_explicit_kwargs_override_env(monkeypatch):
    monkeypatch.setenv("OPENCLAW_WEBHOOK_TOKEN", "tok-from-env")
    monkeypatch.setenv("CS_HTTP_HOST", "10.0.0.8")
    monkeypatch.setenv("CS_HTTP_PORT", "18080")

    cfg = OpenClawBootstrapConfig.from_env(
        webhook_token="tok-from-arg",
        gateway_http_url="http://127.0.0.1:8080/ahp",
    )

    assert cfg.webhook_token == "tok-from-arg"
    assert cfg.gateway_http_url == "http://127.0.0.1:8080/ahp"


def test_build_runtime_wires_adapter_client_security_components():
    cfg = OpenClawBootstrapConfig(
        webhook_token="tok-test",
        webhook_secret="sec-test",
        webhook_require_https=False,
        source_protocol_version="1.1",
        git_short_sha="deadbee",
        profile_version=3,
        gateway_http_url="http://127.0.0.1:18080/ahp",
        gateway_uds_path="/tmp/ahp-unit.sock",
        gateway_auth_token="auth-test",
        gateway_transport_preference="http_first",
        max_retry_budget=7,
    )

    runtime = build_openclaw_runtime(cfg)

    assert runtime.adapter.config.max_retry_budget == 7
    assert runtime.adapter.config.source_protocol_version == "1.1"
    assert runtime.adapter.config.git_short_sha == "deadbee"
    assert runtime.webhook_security.primary_token == "tok-test"
    assert runtime.webhook_security.webhook_secret == "sec-test"
    assert runtime.normalizer.source_protocol_version == "1.1"
    assert runtime.gateway_client.http_url == "http://127.0.0.1:18080/ahp"
    assert runtime.gateway_client.uds_path == "/tmp/ahp-unit.sock"
    assert runtime.gateway_client.auth_token == "auth-test"
    assert runtime.gateway_client.transport_preference == "http_first"
    assert runtime.adapter._gateway_client is runtime.gateway_client


def test_create_webhook_app_uses_built_components():
    cfg = OpenClawBootstrapConfig(
        webhook_token="tok-test",
        webhook_secret="sec-test",
        webhook_require_https=False,
    )
    runtime = build_openclaw_runtime(cfg)
    app = create_openclaw_webhook_app(runtime)

    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["component"] == "openclaw-webhook-receiver"


class TestEnforcementConfig:
    """Test enforcement-related bootstrap config fields."""

    def test_default_enforcement_disabled(self):
        config = OpenClawBootstrapConfig()
        assert config.enforcement_enabled is False
        assert config.openclaw_ws_url == "ws://127.0.0.1:18789"
        assert config.openclaw_operator_token == ""

    def test_from_env_enforcement_fields(self, monkeypatch):
        monkeypatch.setenv("OPENCLAW_WS_URL", "ws://10.0.0.1:9999")
        monkeypatch.setenv("OPENCLAW_OPERATOR_TOKEN", "op-token-123")
        monkeypatch.setenv("OPENCLAW_ENFORCEMENT_ENABLED", "true")
        config = OpenClawBootstrapConfig.from_env()
        assert config.enforcement_enabled is True
        assert config.openclaw_ws_url == "ws://10.0.0.1:9999"
        assert config.openclaw_operator_token == "op-token-123"

    def test_runtime_includes_approval_client(self, monkeypatch):
        monkeypatch.setenv("OPENCLAW_ENFORCEMENT_ENABLED", "true")
        monkeypatch.setenv("OPENCLAW_OPERATOR_TOKEN", "test-token")
        runtime = build_openclaw_runtime_from_env()
        assert runtime.approval_client is not None
        assert runtime.approval_client._config.enabled is True

    def test_runtime_approval_client_disabled_by_default(self):
        runtime = build_openclaw_runtime(OpenClawBootstrapConfig())
        assert runtime.approval_client is not None
        assert runtime.approval_client._config.enabled is False

    def test_runtime_wires_approval_client_to_adapter(self):
        cfg = OpenClawBootstrapConfig(
            enforcement_enabled=True,
            openclaw_operator_token="tok",
        )
        runtime = build_openclaw_runtime(cfg)
        assert runtime.adapter._approval_client is runtime.approval_client
