"""Tests for /ui static file serving."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from clawsentry.gateway.server import SupervisionGateway, create_http_app


@pytest.fixture
def ui_dist(tmp_path):
    """Create a fake ui/dist directory with index.html and an asset."""
    dist = tmp_path / "ui" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html><body>Dashboard</body></html>")
    assets = dist / "assets"
    assets.mkdir()
    (assets / "main.js").write_text("console.log('app')")
    return dist


@pytest.fixture
def gateway(tmp_path):
    return SupervisionGateway(trajectory_db_path=str(tmp_path / "traj.db"))


class TestUIStaticServing:

    @pytest.mark.asyncio
    async def test_ui_serves_index_html(self, gateway, ui_dist):
        app = create_http_app(gateway, ui_dir=ui_dist)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/ui")
        assert resp.status_code == 200
        assert "Dashboard" in resp.text

    @pytest.mark.asyncio
    async def test_ui_serves_asset(self, gateway, ui_dist):
        app = create_http_app(gateway, ui_dir=ui_dist)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/ui/assets/main.js")
        assert resp.status_code == 200
        assert "console.log" in resp.text

    @pytest.mark.asyncio
    async def test_ui_spa_fallback(self, gateway, ui_dist):
        """Unknown /ui/sessions/abc should serve index.html (SPA routing)."""
        app = create_http_app(gateway, ui_dir=ui_dist)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/ui/sessions/abc123")
        assert resp.status_code == 200
        assert "Dashboard" in resp.text

    @pytest.mark.asyncio
    async def test_ui_not_mounted_when_dir_missing(self, gateway, tmp_path):
        """No /ui route when dist dir doesn't exist."""
        missing = tmp_path / "nonexistent"
        app = create_http_app(gateway, ui_dir=missing)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/ui")
        assert resp.status_code in (404, 405)

    @pytest.mark.asyncio
    async def test_ui_no_auth_required(self, gateway, ui_dist):
        """Static UI files should NOT require auth."""
        original = os.environ.get("CS_AUTH_TOKEN")
        os.environ["CS_AUTH_TOKEN"] = "secret-token-for-ui-test-123456789"
        try:
            app = create_http_app(gateway, ui_dir=ui_dist)
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/ui/assets/main.js")
            assert resp.status_code == 200
        finally:
            if original is None:
                os.environ.pop("CS_AUTH_TOKEN", None)
            else:
                os.environ["CS_AUTH_TOKEN"] = original

    @pytest.mark.asyncio
    async def test_ui_path_traversal_blocked(self, gateway, ui_dist):
        """Path traversal attempts must not escape ui_dir."""
        app = create_http_app(gateway, ui_dir=ui_dist)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/ui/../../../etc/passwd")
        # Should get SPA fallback (index.html) since the traversal path is not
        # a valid file inside ui_dir — not a 200 serving /etc/passwd
        assert "root:" not in resp.text
