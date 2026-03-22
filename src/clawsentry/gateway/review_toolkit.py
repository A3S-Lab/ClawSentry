"""Read-only toolkit for Phase 5.2 L3 review agent."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any


class ToolCallBudgetExhausted(RuntimeError):
    """Raised when ReadOnlyToolkit exceeds MAX_TOOL_CALLS."""


class ReadOnlyToolkit:
    MAX_FILE_READ_BYTES = 512_000
    MAX_TOOL_CALLS = 20
    MAX_TRAJECTORY_EVENTS = 500

    def __init__(self, workspace_root: Path, trajectory_store: Any) -> None:
        self._workspace_root = workspace_root.resolve()
        self._trajectory_store = trajectory_store
        self._calls_remaining = self.MAX_TOOL_CALLS

    @property
    def calls_remaining(self) -> int:
        return self._calls_remaining

    def reset_budget(self) -> None:
        self._calls_remaining = self.MAX_TOOL_CALLS

    def _consume_call(self) -> None:
        if self._calls_remaining <= 0:
            raise ToolCallBudgetExhausted(
                f"ReadOnlyToolkit budget exhausted (max {self.MAX_TOOL_CALLS} calls)"
            )
        self._calls_remaining -= 1

    def _safe_path(self, relative_path: str) -> Path:
        clean = relative_path.lstrip("/")
        target = (self._workspace_root / clean).resolve()
        try:
            target.relative_to(self._workspace_root)
        except ValueError as exc:
            raise ValueError(f"Path '{relative_path}' escapes workspace_root") from exc
        return target

    async def read_trajectory(self, session_id: str, limit: int = 100) -> list[dict[str, Any]]:
        self._consume_call()
        capped_limit = min(limit, self.MAX_TRAJECTORY_EVENTS)
        records = self._trajectory_store.replay_session(session_id, limit=capped_limit)
        return [
            {
                "recorded_at": rec.get("recorded_at"),
                "event": rec.get("event", {}),
                "decision": rec.get("decision", {}),
                "risk_level": rec.get("decision", {}).get("risk_level"),
            }
            for rec in records
        ]

    async def read_file(self, relative_path: str) -> str:
        self._consume_call()
        try:
            target = self._safe_path(relative_path)
            if not target.is_file():
                return f"[error: '{relative_path}' is not a file or does not exist]"
            with open(target, "rb") as fh:
                raw = fh.read(self.MAX_FILE_READ_BYTES)
            text = raw.decode("utf-8", errors="replace")
            if len(raw) == self.MAX_FILE_READ_BYTES:
                text += f"\n[truncated at {self.MAX_FILE_READ_BYTES} bytes]"
            return text
        except (ValueError, OSError) as exc:
            return f"[error: {exc}]"

    async def search_codebase(self, pattern: str, glob: str = "**/*", max_results: int = 50) -> list[dict[str, Any]]:
        self._consume_call()
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            return [{"error": f"Invalid regex: {exc}"}]
        results: list[dict[str, Any]] = []
        for path in sorted(self._workspace_root.glob(glob)):
            if not path.is_file() or len(results) >= max_results:
                continue
            try:
                with open(path, "rb") as fh:
                    raw = fh.read(self.MAX_FILE_READ_BYTES)
                for lineno, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), 1):
                    if compiled.search(line):
                        results.append(
                            {
                                "file": str(path.relative_to(self._workspace_root)),
                                "line": lineno,
                                "content": line.rstrip(),
                            }
                        )
                        if len(results) >= max_results:
                            break
            except OSError:
                continue
        return results

    async def query_git_diff(self, ref: str = "HEAD") -> str:
        self._consume_call()
        if not re.match(r"^[A-Za-z0-9_.^~\-/]{1,200}$", ref):
            return "[error: unsafe ref pattern]"
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "diff",
                ref,
                cwd=str(self._workspace_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            output = stdout.decode("utf-8", errors="replace")
            if len(output) > self.MAX_FILE_READ_BYTES:
                output = output[: self.MAX_FILE_READ_BYTES] + "\n[truncated]"
            return output if output else stderr.decode("utf-8", errors="replace")
        except (asyncio.TimeoutError, OSError, FileNotFoundError) as exc:
            return f"[error: {exc}]"

    async def list_directory(self, relative_path: str = ".") -> list[str]:
        self._consume_call()
        try:
            target = self._safe_path(relative_path)
            if not target.is_dir():
                return [f"[error: '{relative_path}' is not a directory]"]
            return [
                str(entry.relative_to(self._workspace_root)) + ("/" if entry.is_dir() else "")
                for entry in sorted(target.iterdir())
            ]
        except (ValueError, OSError) as exc:
            return [f"[error: {exc}]"]
