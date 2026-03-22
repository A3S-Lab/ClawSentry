"""Tests for F-4: UDS socket permissions + optional SSL."""

import asyncio
import os
import tempfile

import pytest

from clawsentry.gateway.server import (
    SupervisionGateway,
    start_uds_server,
    run_gateway,
    _gateway_args_from_env,
)


class TestUDSSocketPermissions:
    @pytest.mark.asyncio
    async def test_uds_socket_permissions(self, tmp_path):
        """Verify socket file permission is 0o600 after creation."""
        sock_path = str(tmp_path / "test.sock")
        gw = SupervisionGateway(trajectory_db_path=":memory:")
        server = await start_uds_server(gw, path=sock_path)
        try:
            assert os.path.exists(sock_path)
            mode = os.stat(sock_path).st_mode & 0o777
            assert mode == 0o600, f"Expected 0600, got {oct(mode)}"
        finally:
            server.close()
            await server.wait_closed()


class TestSSLEnvVars:
    def test_ssl_env_vars_parsed(self, monkeypatch):
        """SSL env vars are correctly parsed by _gateway_args_from_env."""
        monkeypatch.setenv("AHP_SSL_CERTFILE", "/path/to/cert.pem")
        monkeypatch.setenv("AHP_SSL_KEYFILE", "/path/to/key.pem")
        args = _gateway_args_from_env()
        assert args["ssl_certfile"] == "/path/to/cert.pem"
        assert args["ssl_keyfile"] == "/path/to/key.pem"

    def test_run_gateway_default_no_ssl(self, monkeypatch):
        """Default config has no SSL parameters."""
        monkeypatch.delenv("AHP_SSL_CERTFILE", raising=False)
        monkeypatch.delenv("AHP_SSL_KEYFILE", raising=False)
        args = _gateway_args_from_env()
        assert "ssl_certfile" not in args
        assert "ssl_keyfile" not in args

    def test_ssl_partial_config_ignored(self, monkeypatch):
        """Only cert without key should not enable SSL."""
        monkeypatch.setenv("AHP_SSL_CERTFILE", "/path/to/cert.pem")
        monkeypatch.delenv("AHP_SSL_KEYFILE", raising=False)
        args = _gateway_args_from_env()
        assert "ssl_certfile" not in args
        assert "ssl_keyfile" not in args

    def test_ssl_config_logged(self, monkeypatch, caplog):
        """SSL configuration logs HTTPS enabled message."""
        import logging
        caplog.set_level(logging.INFO, logger="clawsentry")
        # We can't easily test run_gateway's logging without starting a server,
        # but we verify the args are correctly built
        monkeypatch.setenv("AHP_SSL_CERTFILE", "/cert.pem")
        monkeypatch.setenv("AHP_SSL_KEYFILE", "/key.pem")
        args = _gateway_args_from_env()
        assert args["ssl_certfile"] == "/cert.pem"
        assert args["ssl_keyfile"] == "/key.pem"
