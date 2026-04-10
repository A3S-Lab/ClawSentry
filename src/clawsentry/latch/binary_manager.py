"""Latch binary download, SHA-256 verification, and installation."""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import stat
import tarfile
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import GITHUB_RELEASE_BASE, LATCH_BIN_DIR, LATCH_VERSION


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class UnsupportedPlatformError(Exception):
    """Raised when the current OS/arch is not supported."""


class ChecksumMismatchError(Exception):
    """Raised when SHA-256 digest does not match the expected value."""


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _PlatformInfo:
    system: str  # "linux", "darwin", "windows"
    machine: str  # "x64", "arm64"

    @property
    def archive_name(self) -> str:
        ext = "zip" if self.system == "windows" else "tar.gz"
        return f"latch-v{LATCH_VERSION}-{self.system}-{self.machine}.{ext}"


_MACHINE_MAP: dict[str, str] = {
    "x86_64": "x64",
    "amd64": "x64",
    "aarch64": "arm64",
    "arm64": "arm64",
}

_SYSTEM_MAP: dict[str, str] = {
    "linux": "linux",
    "darwin": "darwin",
    "windows": "windows",
}


def _detect_platform() -> _PlatformInfo:
    """Return normalised ``(system, machine)`` for download URL construction."""
    raw_system = platform.system().lower()
    raw_machine = platform.machine().lower()

    system = _SYSTEM_MAP.get(raw_system)
    machine = _MACHINE_MAP.get(raw_machine)

    if system is None or machine is None:
        raise UnsupportedPlatformError(
            f"Unsupported platform: {raw_system}/{raw_machine}"
        )

    return _PlatformInfo(system=system, machine=machine)


# ---------------------------------------------------------------------------
# BinaryManager
# ---------------------------------------------------------------------------


class BinaryManager:
    """Download, verify, and manage the Latch binary."""

    def __init__(self, install_dir: Path | None = None) -> None:
        self._install_dir = install_dir or LATCH_BIN_DIR

    # -- properties ----------------------------------------------------------

    @property
    def install_dir(self) -> Path:
        return self._install_dir

    @property
    def binary_path(self) -> Path:
        name = "latch.exe" if platform.system().lower() == "windows" else "latch"
        return self._install_dir / name

    @property
    def is_installed(self) -> bool:
        return self.binary_path.is_file()

    # -- public API ----------------------------------------------------------

    def install(
        self,
        *,
        progress_callback: object | None = None,
        version: str | None = None,
    ) -> Path:
        """Download → verify checksum → extract → chmod +x.

        Returns the path to the installed binary.
        """
        ver = version or LATCH_VERSION
        plat = _detect_platform()
        archive_name = plat.archive_name
        tag = f"v{ver}"

        base_url = f"{GITHUB_RELEASE_BASE}/{tag}"
        checksums_url = f"{base_url}/checksums.txt"
        archive_url = f"{base_url}/{archive_name}"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)

            # 1. Download checksums.txt
            checksums_path = tmp_dir / "checksums.txt"
            _download(checksums_url, checksums_path)
            expected_hash = _parse_checksum(checksums_path, archive_name)

            # 2. Download archive
            archive_path = tmp_dir / archive_name
            _download(archive_url, archive_path)

            # 3. Verify SHA-256
            actual_hash = _sha256(archive_path)
            if actual_hash != expected_hash:
                raise ChecksumMismatchError(
                    f"SHA-256 mismatch for {archive_name}: "
                    f"expected {expected_hash}, got {actual_hash}"
                )

            # 4. Extract
            self._install_dir.mkdir(parents=True, exist_ok=True)
            _extract(archive_path, self._install_dir)

            # 5. chmod +x (non-Windows)
            if plat.system != "windows" and self.binary_path.exists():
                self.binary_path.chmod(
                    self.binary_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP
                )

        return self.binary_path

    def uninstall(self) -> None:
        """Remove the installed binary directory."""
        if self._install_dir.exists():
            shutil.rmtree(self._install_dir)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _download(url: str, dest: Path) -> None:
    """Download *url* to *dest* using ``urllib``."""
    req = urllib.request.Request(url, headers={"User-Agent": "clawsentry"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as fh:
        shutil.copyfileobj(resp, fh)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_checksum(checksums_path: Path, archive_name: str) -> str:
    """Extract expected SHA-256 for *archive_name* from checksums.txt."""
    for line in checksums_path.read_text().splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and parts[1] == archive_name:
            return parts[0].lower()
    raise ValueError(f"No checksum found for {archive_name} in checksums.txt")


def _extract(archive_path: Path, dest_dir: Path) -> None:
    """Extract tar.gz or zip archive into *dest_dir*."""
    name = archive_path.name
    if name.endswith(".tar.gz"):
        with tarfile.open(archive_path, "r:gz") as tf:
            _safe_extract_tar(tf, dest_dir)
    elif name.endswith(".zip"):
        with zipfile.ZipFile(archive_path, "r") as zf:
            _safe_extract_zip(zf, dest_dir)
    else:
        raise ValueError(f"Unsupported archive format: {name}")


def _safe_extract_tar(tf: tarfile.TarFile, dest_dir: Path) -> None:
    """Safely extract a tar archive without relying on Python 3.12-only APIs."""
    if not hasattr(tf, "getmembers"):
        tf.extractall(dest_dir)
        return

    members = tf.getmembers()
    for member in members:
        _validate_archive_member_name(member.name, dest_dir)
        if member.issym() or member.islnk():
            raise ValueError(f"Unsafe archive member: {member.name}")
        if not (member.isfile() or member.isdir()):
            raise ValueError(f"Unsafe archive member: {member.name}")

    for member in members:
        target = dest_dir / member.name
        if member.isdir():
            target.mkdir(parents=True, exist_ok=True)
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        extracted = tf.extractfile(member)
        if extracted is None:
            raise ValueError(f"Unsafe archive member: {member.name}")
        with extracted, open(target, "wb") as fh:
            shutil.copyfileobj(extracted, fh)
        if member.mode:
            target.chmod(member.mode & 0o777)


def _safe_extract_zip(zf: zipfile.ZipFile, dest_dir: Path) -> None:
    """Safely extract a zip archive with destination confinement."""
    for member in zf.infolist():
        _validate_archive_member_name(member.filename, dest_dir)
    zf.extractall(dest_dir)


def _validate_archive_member_name(member_name: str, dest_dir: Path) -> None:
    target = (dest_dir / member_name).resolve()
    dest_root = dest_dir.resolve()
    if os.path.commonpath([str(dest_root), str(target)]) != str(dest_root):
        raise ValueError(f"Unsafe archive member: {member_name}")
