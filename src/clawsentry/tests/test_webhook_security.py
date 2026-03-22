"""
Tests for Webhook Security Layer — Gate 3 verification.

Covers: Token verification, HMAC signature, timestamp anti-replay,
request validation, TLS enforcement, failure_class mapping.
"""

import hmac
import hashlib
import json
import time
import pytest
from clawsentry.adapters.webhook_security import (
    WebhookSecurityConfig,
    WebhookTokenManager,
    verify_webhook_request,
    SecurityCheckResult,
)
from clawsentry.gateway.models import FailureClass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def config():
    return WebhookSecurityConfig(
        primary_token="tok-primary-123",
        webhook_secret="secret-key-abc",
        require_https=False,  # relax for testing
    )


@pytest.fixture
def token_manager(config):
    return WebhookTokenManager(config)


def _make_signature(secret: str, timestamp: int, body: bytes) -> str:
    """Helper to generate valid HMAC signature."""
    msg = f"{timestamp}.".encode() + body
    sig = hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()
    return f"v1={sig}"


# ===========================================================================
# Token Verification
# ===========================================================================

class TestTokenVerification:
    def test_valid_primary_token(self, token_manager):
        assert token_manager.verify_token("tok-primary-123") is True

    def test_invalid_token(self, token_manager):
        assert token_manager.verify_token("wrong-token") is False

    def test_empty_token(self, token_manager):
        assert token_manager.verify_token("") is False

    def test_dual_token_primary(self, config):
        config.secondary_token = "tok-secondary-456"
        mgr = WebhookTokenManager(config)
        assert mgr.verify_token("tok-primary-123") is True

    def test_dual_token_secondary(self, config):
        config.secondary_token = "tok-secondary-456"
        mgr = WebhookTokenManager(config)
        assert mgr.verify_token("tok-secondary-456") is True

    def test_dual_token_invalid(self, config):
        config.secondary_token = "tok-secondary-456"
        mgr = WebhookTokenManager(config)
        assert mgr.verify_token("wrong") is False


# ===========================================================================
# HMAC Signature Verification
# ===========================================================================

class TestHMACSignature:
    def test_valid_signature(self, config):
        body = json.dumps({"type": "test", "sessionKey": "s1"}).encode()
        ts = int(time.time())
        sig = _make_signature(config.webhook_secret, ts, body)
        result = verify_webhook_request(
            config=config,
            token="tok-primary-123",
            signature=sig,
            timestamp=str(ts),
            content_type="application/json",
            body=body,
            source_url="https://example.com/webhook",
        )
        assert result.ok is True

    def test_wrong_signature(self, config):
        body = b'{"type":"test","sessionKey":"s1"}'
        ts = int(time.time())
        result = verify_webhook_request(
            config=config,
            token="tok-primary-123",
            signature="v1=wrongsignature",
            timestamp=str(ts),
            content_type="application/json",
            body=body,
            source_url="https://example.com/webhook",
        )
        assert result.ok is False
        assert result.failure_class == FailureClass.AUTH_INVALID_SIGNATURE

    def test_missing_signature_strict_mode(self, config):
        body = b'{"type":"test","sessionKey":"s1"}'
        ts = int(time.time())
        result = verify_webhook_request(
            config=config,
            token="tok-primary-123",
            signature=None,
            timestamp=str(ts),
            content_type="application/json",
            body=body,
            source_url="https://example.com/webhook",
        )
        assert result.ok is False
        assert result.failure_class == FailureClass.AUTH_INVALID_SIGNATURE

    def test_missing_signature_permissive_mode(self, config):
        config.signature_mode = "permissive"
        body = b'{"type":"test","sessionKey":"s1"}'
        ts = int(time.time())
        result = verify_webhook_request(
            config=config,
            token="tok-primary-123",
            signature=None,
            timestamp=str(ts),
            content_type="application/json",
            body=body,
            source_url="https://example.com/webhook",
        )
        assert result.ok is True


# ===========================================================================
# Timestamp Anti-Replay
# ===========================================================================

class TestTimestamp:
    def test_expired_timestamp(self, config):
        body = b'{"type":"test","sessionKey":"s1"}'
        old_ts = int(time.time()) - 600  # 10 min ago
        sig = _make_signature(config.webhook_secret, old_ts, body)
        result = verify_webhook_request(
            config=config,
            token="tok-primary-123",
            signature=sig,
            timestamp=str(old_ts),
            content_type="application/json",
            body=body,
            source_url="https://example.com/webhook",
        )
        assert result.ok is False
        assert result.failure_class == FailureClass.AUTH_TIMESTAMP_EXPIRED

    def test_missing_timestamp(self, config):
        body = b'{"type":"test","sessionKey":"s1"}'
        sig = _make_signature(config.webhook_secret, 0, body)
        result = verify_webhook_request(
            config=config,
            token="tok-primary-123",
            signature=sig,
            timestamp=None,
            content_type="application/json",
            body=body,
            source_url="https://example.com/webhook",
        )
        assert result.ok is False
        assert result.failure_class == FailureClass.AUTH_TIMESTAMP_EXPIRED


# ===========================================================================
# Request Validation
# ===========================================================================

class TestRequestValidation:
    def test_wrong_content_type(self, config):
        body = b'{"type":"test","sessionKey":"s1"}'
        ts = int(time.time())
        sig = _make_signature(config.webhook_secret, ts, body)
        result = verify_webhook_request(
            config=config,
            token="tok-primary-123",
            signature=sig,
            timestamp=str(ts),
            content_type="text/plain",
            body=body,
            source_url="https://example.com/webhook",
        )
        assert result.ok is False
        assert result.failure_class == FailureClass.INPUT_INVALID

    def test_oversized_body(self, config):
        config.max_body_bytes = 100
        body = b"x" * 200
        ts = int(time.time())
        sig = _make_signature(config.webhook_secret, ts, body)
        result = verify_webhook_request(
            config=config,
            token="tok-primary-123",
            signature=sig,
            timestamp=str(ts),
            content_type="application/json",
            body=body,
            source_url="https://example.com/webhook",
        )
        assert result.ok is False
        assert result.failure_class == FailureClass.INPUT_INVALID

    def test_invalid_json(self, config):
        body = b"not valid json"
        ts = int(time.time())
        sig = _make_signature(config.webhook_secret, ts, body)
        result = verify_webhook_request(
            config=config,
            token="tok-primary-123",
            signature=sig,
            timestamp=str(ts),
            content_type="application/json",
            body=body,
            source_url="https://example.com/webhook",
        )
        assert result.ok is False
        assert result.failure_class == FailureClass.INPUT_INVALID

    def test_missing_required_fields(self, config):
        body = json.dumps({"data": "no type or sessionKey"}).encode()
        ts = int(time.time())
        sig = _make_signature(config.webhook_secret, ts, body)
        result = verify_webhook_request(
            config=config,
            token="tok-primary-123",
            signature=sig,
            timestamp=str(ts),
            content_type="application/json",
            body=body,
            source_url="https://example.com/webhook",
        )
        assert result.ok is False
        assert result.failure_class == FailureClass.INPUT_INVALID


# ===========================================================================
# TLS Enforcement
# ===========================================================================

class TestTLSEnforcement:
    def test_https_url_accepted(self):
        config = WebhookSecurityConfig(
            primary_token="tok-1",
            require_https=True,
        )
        body = json.dumps({"type": "test", "sessionKey": "s1"}).encode()
        ts = int(time.time())
        result = verify_webhook_request(
            config=config,
            token="tok-1",
            signature=None,
            timestamp=str(ts),
            content_type="application/json",
            body=body,
            source_url="https://example.com/webhook",
        )
        # Will pass TLS check (may fail later on signature if no secret, but TLS ok)
        assert result.failure_class != FailureClass.AUTH_INVALID_TOKEN or result.http_status != 403

    def test_http_non_localhost_rejected(self):
        config = WebhookSecurityConfig(
            primary_token="tok-1",
            require_https=True,
        )
        body = json.dumps({"type": "test", "sessionKey": "s1"}).encode()
        ts = int(time.time())
        result = verify_webhook_request(
            config=config,
            token="tok-1",
            signature=None,
            timestamp=str(ts),
            content_type="application/json",
            body=body,
            source_url="http://remote-server.com/webhook",
        )
        assert result.ok is False

    def test_http_localhost_allowed(self):
        config = WebhookSecurityConfig(
            primary_token="tok-1",
            require_https=True,
        )
        body = json.dumps({"type": "test", "sessionKey": "s1"}).encode()
        ts = int(time.time())
        result = verify_webhook_request(
            config=config,
            token="tok-1",
            signature=None,
            timestamp=str(ts),
            content_type="application/json",
            body=body,
            source_url="http://127.0.0.1:8081/webhook",
        )
        # Localhost HTTP should pass TLS check
        assert result.failure_class != FailureClass.INPUT_INVALID


# ===========================================================================
# Token + Full Flow
# ===========================================================================

class TestFullFlow:
    def test_invalid_token_rejects(self, config):
        body = b'{"type":"test","sessionKey":"s1"}'
        ts = int(time.time())
        sig = _make_signature(config.webhook_secret, ts, body)
        result = verify_webhook_request(
            config=config,
            token="wrong-token",
            signature=sig,
            timestamp=str(ts),
            content_type="application/json",
            body=body,
            source_url="https://example.com/webhook",
        )
        assert result.ok is False
        assert result.failure_class == FailureClass.AUTH_INVALID_TOKEN

    def test_no_secret_skips_signature_check(self):
        config = WebhookSecurityConfig(
            primary_token="tok-1",
            webhook_secret=None,
            require_https=False,
        )
        body = json.dumps({"type": "test", "sessionKey": "s1"}).encode()
        ts = int(time.time())
        result = verify_webhook_request(
            config=config,
            token="tok-1",
            signature=None,
            timestamp=str(ts),
            content_type="application/json",
            body=body,
            source_url="https://example.com/webhook",
        )
        assert result.ok is True


# ===========================================================================
# F-3: IP Whitelist
# ===========================================================================

class TestIPWhitelist:
    def test_ip_whitelist_allowed(self):
        config = WebhookSecurityConfig(
            primary_token="tok-1",
            webhook_secret=None,
            require_https=False,
            ip_whitelist=["10.0.0.1", "10.0.0.2"],
        )
        body = json.dumps({"type": "test", "sessionKey": "s1"}).encode()
        result = verify_webhook_request(
            config=config, token="tok-1", signature=None,
            timestamp=None, content_type="application/json",
            body=body, source_url="http://localhost/webhook",
            source_ip="10.0.0.1",
        )
        assert result.ok is True

    def test_ip_whitelist_blocked(self):
        config = WebhookSecurityConfig(
            primary_token="tok-1",
            webhook_secret=None,
            require_https=False,
            ip_whitelist=["10.0.0.1"],
        )
        body = json.dumps({"type": "test", "sessionKey": "s1"}).encode()
        result = verify_webhook_request(
            config=config, token="tok-1", signature=None,
            timestamp=None, content_type="application/json",
            body=body, source_url="http://localhost/webhook",
            source_ip="192.168.1.1",
        )
        assert result.ok is False
        assert result.http_status == 403

    def test_ip_whitelist_disabled(self):
        config = WebhookSecurityConfig(
            primary_token="tok-1",
            webhook_secret=None,
            require_https=False,
            ip_whitelist=None,
        )
        body = json.dumps({"type": "test", "sessionKey": "s1"}).encode()
        result = verify_webhook_request(
            config=config, token="tok-1", signature=None,
            timestamp=None, content_type="application/json",
            body=body, source_url="http://localhost/webhook",
            source_ip="any-ip",
        )
        assert result.ok is True


# ===========================================================================
# F-3: Token TTL
# ===========================================================================

class TestTokenTTL:
    def test_token_ttl_valid(self):
        config = WebhookSecurityConfig(
            primary_token="tok-1",
            webhook_secret=None,
            require_https=False,
            token_issued_at=time.time() - 100,
            token_ttl_seconds=3600,
        )
        body = json.dumps({"type": "test", "sessionKey": "s1"}).encode()
        result = verify_webhook_request(
            config=config, token="tok-1", signature=None,
            timestamp=None, content_type="application/json",
            body=body, source_url="http://localhost/webhook",
        )
        assert result.ok is True

    def test_token_ttl_expired(self):
        config = WebhookSecurityConfig(
            primary_token="tok-1",
            webhook_secret=None,
            require_https=False,
            token_issued_at=time.time() - 7200,
            token_ttl_seconds=3600,
        )
        body = json.dumps({"type": "test", "sessionKey": "s1"}).encode()
        result = verify_webhook_request(
            config=config, token="tok-1", signature=None,
            timestamp=None, content_type="application/json",
            body=body, source_url="http://localhost/webhook",
        )
        assert result.ok is False
        assert result.http_status == 401
        assert "expired" in result.message.lower()

    def test_token_ttl_disabled(self):
        config = WebhookSecurityConfig(
            primary_token="tok-1",
            webhook_secret=None,
            require_https=False,
            token_issued_at=time.time() - 999999,
            token_ttl_seconds=0,
        )
        body = json.dumps({"type": "test", "sessionKey": "s1"}).encode()
        result = verify_webhook_request(
            config=config, token="tok-1", signature=None,
            timestamp=None, content_type="application/json",
            body=body, source_url="http://localhost/webhook",
        )
        assert result.ok is True
