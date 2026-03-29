"""``clawsentry audit`` — offline audit log query from trajectory database.

Opens the SQLite trajectory database in read-only mode and supports
multi-dimensional filtering with table/json/csv output formats.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Duration parsing
# ---------------------------------------------------------------------------

_DURATION_RE = re.compile(r"^(\d+)\s*([smhdw])$", re.IGNORECASE)

_DURATION_MULTIPLIERS: dict[str, int] = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
    "w": 604800,
}


def parse_duration(s: str) -> int:
    """Parse a human-friendly duration string into seconds.

    Examples: ``30m`` → 1800, ``24h`` → 86400, ``7d`` → 604800.
    Raises ``ValueError`` for invalid input.
    """
    m = _DURATION_RE.match(s.strip())
    if not m:
        raise ValueError(
            f"Invalid duration '{s}'. Use <number><unit> where unit is s/m/h/d/w."
        )
    return int(m.group(1)) * _DURATION_MULTIPLIERS[m.group(2).lower()]


# ---------------------------------------------------------------------------
# AuditReader
# ---------------------------------------------------------------------------


class AuditReader:
    """Read-only interface to the trajectory SQLite database."""

    def __init__(self, db_path: str) -> None:
        if not os.path.isfile(db_path):
            raise FileNotFoundError(f"Database not found: {db_path}")
        uri = f"file:{db_path}?mode=ro"
        self._conn = sqlite3.connect(uri, uri=True)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "AuditReader":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def query(
        self,
        *,
        session_id: str | None = None,
        since_seconds: int | None = None,
        risk_level: str | None = None,
        decision: str | None = None,
        tool_name: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query trajectory records with optional filters.

        All filter values are passed via parameterised SQL to prevent injection.
        """
        clauses: list[str] = []
        params: list[Any] = []

        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)

        if since_seconds is not None:
            cutoff = time.time() - since_seconds
            clauses.append("recorded_at_ts >= ?")
            params.append(cutoff)

        if risk_level is not None:
            clauses.append("LOWER(risk_level) = LOWER(?)")
            params.append(risk_level)

        if decision is not None:
            clauses.append("LOWER(decision) = LOWER(?)")
            params.append(decision)

        where = ""
        if clauses:
            where = "WHERE " + " AND ".join(clauses)

        sql = (
            f"SELECT id, recorded_at, session_id, source_framework, "
            f"event_type, decision, risk_level, event_json, decision_json, "
            f"snapshot_json, meta_json "
            f"FROM trajectory_records {where} "
            f"ORDER BY recorded_at_ts DESC LIMIT ?"
        )
        params.append(limit)

        cur = self._conn.execute(sql, params)
        rows = cur.fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            rec = dict(row)
            # Extract tool_name from event_json for filtering
            try:
                ev = json.loads(rec.get("event_json", "{}"))
                rec["tool_name"] = ev.get("tool_name", "")
            except (json.JSONDecodeError, TypeError):
                rec["tool_name"] = ""

            # Extract reason from decision_json
            try:
                dec = json.loads(rec.get("decision_json", "{}"))
                rec["reason"] = dec.get("reason", "")
            except (json.JSONDecodeError, TypeError):
                rec["reason"] = ""

            results.append(rec)

        # Post-filter by tool_name (not a DB column)
        if tool_name is not None:
            tool_lower = tool_name.lower()
            results = [
                r for r in results if tool_lower in (r.get("tool_name") or "").lower()
            ]

        return results

    def stats(self, since_seconds: int | None = None) -> dict[str, Any]:
        """Compute aggregate statistics."""
        clauses: list[str] = []
        params: list[Any] = []

        if since_seconds is not None:
            cutoff = time.time() - since_seconds
            clauses.append("recorded_at_ts >= ?")
            params.append(cutoff)

        where = ""
        if clauses:
            where = "WHERE " + " AND ".join(clauses)

        # Total count
        cur = self._conn.execute(
            f"SELECT COUNT(*) FROM trajectory_records {where}", params
        )
        total = cur.fetchone()[0]

        # By risk_level
        cur = self._conn.execute(
            f"SELECT UPPER(risk_level) as rl, COUNT(*) as cnt "
            f"FROM trajectory_records {where} "
            f"GROUP BY UPPER(risk_level) ORDER BY cnt DESC",
            params,
        )
        by_risk = {row[0] or "UNKNOWN": row[1] for row in cur.fetchall()}

        # By decision
        cur = self._conn.execute(
            f"SELECT UPPER(decision) as d, COUNT(*) as cnt "
            f"FROM trajectory_records {where} "
            f"GROUP BY UPPER(decision) ORDER BY cnt DESC",
            params,
        )
        by_decision = {row[0] or "UNKNOWN": row[1] for row in cur.fetchall()}

        # By source_framework
        cur = self._conn.execute(
            f"SELECT source_framework, COUNT(*) as cnt "
            f"FROM trajectory_records {where} "
            f"GROUP BY source_framework ORDER BY cnt DESC",
            params,
        )
        by_framework = {row[0] or "unknown": row[1] for row in cur.fetchall()}

        # Top sessions (top 5)
        cur = self._conn.execute(
            f"SELECT session_id, COUNT(*) as cnt "
            f"FROM trajectory_records {where} "
            f"GROUP BY session_id ORDER BY cnt DESC LIMIT 5",
            params,
        )
        top_sessions = [(row[0] or "unknown", row[1]) for row in cur.fetchall()]

        return {
            "total": total,
            "by_risk_level": by_risk,
            "by_decision": by_decision,
            "by_framework": by_framework,
            "top_sessions": top_sessions,
        }


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

_TABLE_COLUMNS = [
    ("Time", "recorded_at", 20),
    ("Session", "session_id", 14),
    ("Tool", "tool_name", 18),
    ("Risk", "risk_level", 8),
    ("Decision", "decision", 8),
    ("Reason", "reason", 40),
]


def _colorize_risk(level: str, color: bool) -> str:
    if not color:
        return level
    codes = {
        "LOW": "\033[32m",
        "MEDIUM": "\033[33m",
        "HIGH": "\033[31m",
        "CRITICAL": "\033[35m",
    }
    reset = "\033[0m"
    return f"{codes.get(level.upper(), '')}{level}{reset}"


def _colorize_decision(verdict: str, color: bool) -> str:
    if not color:
        return verdict
    codes = {
        "ALLOW": "\033[32m",
        "BLOCK": "\033[31m",
        "DEFER": "\033[33m",
        "MODIFY": "\033[36m",
    }
    reset = "\033[0m"
    return f"{codes.get(verdict.upper(), '')}{verdict}{reset}"


def _truncate(s: str, maxlen: int) -> str:
    if len(s) <= maxlen:
        return s
    return s[: maxlen - 3] + "..."


def format_table(records: list[dict[str, Any]], color: bool = True) -> str:
    """Format records as a human-readable table."""
    if not records:
        return "No records found."

    lines: list[str] = []
    # Header
    header = "  ".join(h.ljust(w) for h, _, w in _TABLE_COLUMNS)
    lines.append(header)
    lines.append("-" * len(header))

    for rec in records:
        parts: list[str] = []
        for _, key, width in _TABLE_COLUMNS:
            val = str(rec.get(key, "") or "")
            if key == "risk_level":
                display = _colorize_risk(val.upper(), color)
                # Pad after color codes
                pad = width - len(val)
                parts.append(display + " " * max(pad, 0))
            elif key == "decision":
                display = _colorize_decision(val.upper(), color)
                pad = width - len(val)
                parts.append(display + " " * max(pad, 0))
            else:
                parts.append(_truncate(val, width).ljust(width))
        lines.append("  ".join(parts))

    lines.append(f"\n{len(records)} record(s) shown.")
    return "\n".join(lines)


def format_json_output(records: list[dict[str, Any]]) -> str:
    """Format records as JSON, stripping large JSON blobs."""
    slim: list[dict[str, Any]] = []
    for rec in records:
        slim.append({
            "id": rec.get("id"),
            "recorded_at": rec.get("recorded_at"),
            "session_id": rec.get("session_id"),
            "source_framework": rec.get("source_framework"),
            "event_type": rec.get("event_type"),
            "decision": rec.get("decision"),
            "risk_level": rec.get("risk_level"),
            "tool_name": rec.get("tool_name"),
            "reason": rec.get("reason"),
        })
    return json.dumps(slim, indent=2)


def format_csv_output(records: list[dict[str, Any]]) -> str:
    """Format records as CSV."""
    if not records:
        return ""
    fields = [
        "id", "recorded_at", "session_id", "source_framework",
        "event_type", "decision", "risk_level", "tool_name", "reason",
    ]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(records)
    return buf.getvalue()


def format_stats(stats: dict[str, Any], since_label: str = "") -> str:
    """Format stats as a human-readable summary."""
    lines: list[str] = []
    title = f"Audit Summary{' (' + since_label + ')' if since_label else ''}"
    lines.append(title)
    lines.append("=" * len(title))
    lines.append(f"Total records:     {stats['total']:,}")

    risk = stats.get("by_risk_level", {})
    if risk:
        parts = [f"{k}: {v}" for k, v in risk.items()]
        lines.append(f"By risk level:     {', '.join(parts)}")

    dec = stats.get("by_decision", {})
    if dec:
        parts = [f"{k}: {v}" for k, v in dec.items()]
        lines.append(f"By decision:       {', '.join(parts)}")

    fw = stats.get("by_framework", {})
    if fw:
        parts = [f"{k}: {v}" for k, v in fw.items()]
        lines.append(f"By framework:      {', '.join(parts)}")

    top = stats.get("top_sessions", [])
    if top:
        parts = [f"{sid} ({cnt} events)" for sid, cnt in top]
        lines.append(f"Top sessions:      {'  '.join(parts)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI runner
# ---------------------------------------------------------------------------


def run_audit(
    *,
    db_path: str | None = None,
    session_id: str | None = None,
    since: str | None = None,
    risk: str | None = None,
    decision: str | None = None,
    tool: str | None = None,
    fmt: str = "table",
    stats_mode: bool = False,
    limit: int = 100,
    color: bool = True,
) -> int:
    """Run audit command and print output. Returns exit code (0=ok, 1=error)."""
    db = db_path or os.environ.get(
        "CS_TRAJECTORY_DB_PATH", "/tmp/clawsentry-trajectory.db"
    )

    since_seconds: int | None = None
    if since:
        try:
            since_seconds = parse_duration(since)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    try:
        reader = AuditReader(db)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    with reader:
        if stats_mode:
            result = reader.stats(since_seconds=since_seconds)
            if fmt == "json":
                print(json.dumps(result, indent=2))
            else:
                since_label = f"last {since}" if since else ""
                print(format_stats(result, since_label=since_label))
            return 0

        records = reader.query(
            session_id=session_id,
            since_seconds=since_seconds,
            risk_level=risk,
            decision=decision,
            tool_name=tool,
            limit=limit,
        )

        if fmt == "json":
            print(format_json_output(records))
        elif fmt == "csv":
            output = format_csv_output(records)
            if output:
                print(output, end="")
            else:
                print("No records found.")
        else:
            print(format_table(records, color=color))

    return 0
