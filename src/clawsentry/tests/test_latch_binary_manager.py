"""Tests for latch.binary_manager."""

from __future__ import annotations

import hashlib
import os
import stat
import tarfile
import textwrap
from pathlib import Path
from unittest import mock

import pytest

from clawsentry.latch.binary_manager import (
    BinaryManager,
    ChecksumMismatchError,
    UnsupportedPlatformError,
    _PlatformInfo,
    _detect_platform,
    _extract,
    _parse_checksum,
    _sha256,
)


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------


def test_detect_platform_linux_x64():
    with mock.patch("platform.system", return_value="Linux"), \
         mock.patch("platform.machine", return_value="x86_64"):
        info = _detect_platform()
        assert info.system == "linux"
        assert info.machine == "x64"


def test_detect_platform_darwin_arm64():
    with mock.patch("platform.system", return_value="Darwin"), \
         mock.patch("platform.machine", return_value="arm64"):
        info = _detect_platform()
        assert info.system == "darwin"
        assert info.machine == "arm64"


def test_detect_platform_windows_amd64():
    with mock.patch("platform.system", return_value="Windows"), \
         mock.patch("platform.machine", return_value="AMD64"):
        info = _detect_platform()
        assert info.system == "windows"
        assert info.machine == "x64"


def test_detect_platform_unsupported():
    with mock.patch("platform.system", return_value="FreeBSD"), \
         mock.patch("platform.machine", return_value="mips"):
        with pytest.raises(UnsupportedPlatformError, match="freebsd"):
            _detect_platform()


# ---------------------------------------------------------------------------
# _PlatformInfo.archive_name
# ---------------------------------------------------------------------------


def test_archive_name_linux():
    info = _PlatformInfo(system="linux", machine="x64")
    assert info.archive_name == "latch-v0.16.1-linux-x64.tar.gz"


def test_archive_name_windows():
    info = _PlatformInfo(system="windows", machine="x64")
    assert info.archive_name == "latch-v0.16.1-windows-x64.zip"


# ---------------------------------------------------------------------------
# Checksum parsing
# ---------------------------------------------------------------------------


def test_parse_checksum_found(tmp_path: Path):
    content = textwrap.dedent("""\
        abc123  latch-v0.16.1-linux-x64.tar.gz
        def456  latch-v0.16.1-darwin-arm64.tar.gz
    """)
    p = tmp_path / "checksums.txt"
    p.write_text(content)
    assert _parse_checksum(p, "latch-v0.16.1-linux-x64.tar.gz") == "abc123"


def test_parse_checksum_not_found(tmp_path: Path):
    p = tmp_path / "checksums.txt"
    p.write_text("abc123  other-file.tar.gz\n")
    with pytest.raises(ValueError, match="No checksum found"):
        _parse_checksum(p, "latch-v0.16.1-linux-x64.tar.gz")


# ---------------------------------------------------------------------------
# SHA-256
# ---------------------------------------------------------------------------


def test_sha256(tmp_path: Path):
    f = tmp_path / "data.bin"
    f.write_bytes(b"hello world")
    expected = hashlib.sha256(b"hello world").hexdigest()
    assert _sha256(f) == expected


# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------


def test_extract_tar_gz(tmp_path: Path):
    # Create a tar.gz with a dummy binary
    archive = tmp_path / "test.tar.gz"
    inner = tmp_path / "inner"
    inner.mkdir()
    (inner / "latch").write_text("#!/bin/sh\necho ok")
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(inner / "latch", arcname="latch")

    dest = tmp_path / "out"
    dest.mkdir()
    _extract(archive, dest)
    assert (dest / "latch").is_file()


def test_extract_tar_gz_without_filter_support(tmp_path: Path):
    archive = tmp_path / "test.tar.gz"
    archive.write_bytes(b"placeholder")
    dest = tmp_path / "out"
    dest.mkdir()

    class FakeTarFile:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extractall(self, path):
            (Path(path) / "latch").write_text("#!/bin/sh\necho ok")

    with mock.patch("tarfile.open", return_value=FakeTarFile()):
        _extract(archive, dest)

    assert (dest / "latch").is_file()


def test_extract_tar_gz_rejects_path_traversal(tmp_path: Path):
    archive = tmp_path / "traversal.tar.gz"
    payload = tmp_path / "payload.txt"
    payload.write_text("bad")

    with tarfile.open(archive, "w:gz") as tf:
        tf.add(payload, arcname="../escape.txt")

    dest = tmp_path / "out"
    dest.mkdir()

    with pytest.raises(ValueError, match="Unsafe archive member"):
        _extract(archive, dest)

    assert not (tmp_path / "escape.txt").exists()


def test_extract_unsupported(tmp_path: Path):
    archive = tmp_path / "test.tar.bz2"
    archive.write_bytes(b"")
    with pytest.raises(ValueError, match="Unsupported archive"):
        _extract(archive, tmp_path)


# ---------------------------------------------------------------------------
# BinaryManager
# ---------------------------------------------------------------------------


def test_binary_manager_is_installed(tmp_path: Path):
    mgr = BinaryManager(install_dir=tmp_path)
    assert mgr.is_installed is False

    (tmp_path / "latch").write_text("binary")
    assert mgr.is_installed is True


def test_binary_manager_binary_path(tmp_path: Path):
    mgr = BinaryManager(install_dir=tmp_path)
    with mock.patch("platform.system", return_value="Linux"):
        assert mgr.binary_path == tmp_path / "latch"


def test_binary_manager_uninstall(tmp_path: Path):
    install = tmp_path / "bin"
    install.mkdir()
    (install / "latch").write_text("binary")
    mgr = BinaryManager(install_dir=install)
    mgr.uninstall()
    assert not install.exists()


def test_binary_manager_install_success(tmp_path: Path):
    """Full install flow with mocked HTTP downloads."""
    install_dir = tmp_path / "bin"
    mgr = BinaryManager(install_dir=install_dir)

    # Create a fake tar.gz archive containing a "latch" binary
    archive_dir = tmp_path / "archive_build"
    archive_dir.mkdir()
    fake_binary = archive_dir / "latch"
    fake_binary.write_text("#!/bin/sh\necho latch")
    archive_path = tmp_path / "archive.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tf:
        tf.add(fake_binary, arcname="latch")

    archive_bytes = archive_path.read_bytes()
    archive_hash = hashlib.sha256(archive_bytes).hexdigest()

    # Build fake checksums.txt content
    checksums_content = f"{archive_hash}  latch-v0.16.1-linux-x64.tar.gz\n"

    call_count = 0

    def fake_download(url: str, dest: Path) -> None:
        nonlocal call_count
        if "checksums.txt" in url:
            dest.write_text(checksums_content)
        else:
            dest.write_bytes(archive_bytes)
        call_count += 1

    with mock.patch("platform.system", return_value="Linux"), \
         mock.patch("platform.machine", return_value="x86_64"), \
         mock.patch("clawsentry.latch.binary_manager._download", side_effect=fake_download):
        result = mgr.install()

    assert result == install_dir / "latch"
    assert result.is_file()
    assert call_count == 2  # checksums + archive
    # Check executable bit set
    assert result.stat().st_mode & stat.S_IXUSR


def test_binary_manager_install_checksum_mismatch(tmp_path: Path):
    """Install fails when checksum doesn't match."""
    install_dir = tmp_path / "bin"
    mgr = BinaryManager(install_dir=install_dir)

    archive_path = tmp_path / "archive.tar.gz"
    archive_path.write_bytes(b"fake archive data")

    def fake_download(url: str, dest: Path) -> None:
        if "checksums.txt" in url:
            dest.write_text("0000000000000000  latch-v0.16.1-linux-x64.tar.gz\n")
        else:
            dest.write_bytes(b"fake archive data")

    with mock.patch("platform.system", return_value="Linux"), \
         mock.patch("platform.machine", return_value="x86_64"), \
         mock.patch("clawsentry.latch.binary_manager._download", side_effect=fake_download):
        with pytest.raises(ChecksumMismatchError, match="SHA-256 mismatch"):
            mgr.install()
