"""Tests for ``clawsentry audit`` audit log query command."""

from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
import time

import pytest

from clawsentry.cli.audit_command import (
    AuditReader,
    format_csv_output,
    format_json_output,
    format_stats,
    format_table,
    parse_duration,
    run_audit,
)


# ---------------------------------------------------------------------------
# Helpers — create a temporary trajectory DB with test data
# ---------------------------------------------------------------------------


def _create_test_db(db_path: str, records: list[dict] | None = None) -> None:
    """Create a trajectory_records table with optional test data."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trajectory_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recorded_at_ts REAL NOT NULL,
            recorded_at TEXT NOT NULL,
            session_id TEXT,
            source_framework TEXT,
            event_type TEXT,
            decision TEXT,
            risk_level TEXT,
            event_json TEXT NOT NULL,
            decision_json TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            meta_json TEXT NOT NULL,
            l3_trace_json TEXT
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_traj_recorded_at "
        "ON trajectory_records(recorded_at_ts)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_traj_session_id "
        "ON trajectory_records(session_id)"
    )

    if records:
        for rec in records:
            conn.execute(
                """
                INSERT INTO trajectory_records
                    (recorded_at_ts, recorded_at, session_id, source_framework,
                     event_type, decision, risk_level,
                     event_json, decision_json, snapshot_json, meta_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec.get("ts", time.time()),
                    rec.get("at", "2026-03-29T00:00:00Z"),
                    rec.get("session_id", "sess-1"),
                    rec.get("source_framework", "a3s-code"),
                    rec.get("event_type", "PRE_ACTION"),
                    rec.get("decision", "ALLOW"),
                    rec.get("risk_level", "LOW"),
                    json.dumps(rec.get("event", {"tool_name": "bash"})),
                    json.dumps(rec.get("dec", {"reason": "low risk"})),
                    json.dumps(rec.get("snap", {})),
                    json.dumps(rec.get("meta", {})),
                ),
            )

    conn.commit()
    conn.close()


@pytest.fixture()
def sample_db(tmp_path) -> str:
    """Create a test DB with sample records."""
    db = str(tmp_path / "test.db")
    now = time.time()
    records = [
        {
            "ts": now - 60,
            "at": "2026-03-29T12:00:00Z",
            "session_id": "sess-1",
            "decision": "ALLOW",
            "risk_level": "LOW",
            "event": {"tool_name": "read_file"},
            "dec": {"reason": "low risk"},
        },
        {
            "ts": now - 30,
            "at": "2026-03-29T12:00:30Z",
            "session_id": "sess-1",
            "decision": "BLOCK",
            "risk_level": "HIGH",
            "event": {"tool_name": "bash"},
            "dec": {"reason": "dangerous command"},
        },
        {
            "ts": now - 10,
            "at": "2026-03-29T12:01:00Z",
            "session_id": "sess-2",
            "decision": "DEFER",
            "risk_level": "MEDIUM",
            "event": {"tool_name": "write_file"},
            "dec": {"reason": "needs review"},
        },
        {
            "ts": now - 5,
            "at": "2026-03-29T12:01:30Z",
            "session_id": "sess-2",
            "source_framework": "openclaw",
            "decision": "ALLOW",
            "risk_level": "LOW",
            "event": {"tool_name": "grep"},
            "dec": {"reason": "safe tool"},
        },
    ]
    _create_test_db(db, records)
    return db


@pytest.fixture()
def empty_db(tmp_path) -> str:
    """Create an empty trajectory DB."""
    db = str(tmp_path / "empty.db")
    _create_test_db(db)
    return db


# ===== Duration parsing =====


class TestParseDuration:
    def test_seconds(self) -> None:
        assert parse_duration("30s") == 30

    def test_minutes(self) -> None:
        assert parse_duration("30m") == 1800

    def test_hours(self) -> None:
        assert parse_duration("24h") == 86400

    def test_days(self) -> None:
        assert parse_duration("7d") == 604800

    def test_weeks(self) -> None:
        assert parse_duration("2w") == 1209600

    def test_whitespace(self) -> None:
        assert parse_duration(" 1h ") == 3600

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid duration"):
            parse_duration("abc")

    def test_no_unit_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_duration("100")


# ===== AuditReader query =====


class TestAuditReaderQuery:
    def test_all_records(self, sample_db: str) -> None:
        with AuditReader(sample_db) as r:
            recs = r.query()
        assert len(recs) == 4

    def test_filter_by_session(self, sample_db: str) -> None:
        with AuditReader(sample_db) as r:
            recs = r.query(session_id="sess-1")
        assert len(recs) == 2
        assert all(r["session_id"] == "sess-1" for r in recs)

    def test_filter_by_risk(self, sample_db: str) -> None:
        with AuditReader(sample_db) as r:
            recs = r.query(risk_level="HIGH")
        assert len(recs) == 1
        assert recs[0]["risk_level"] == "HIGH"

    def test_filter_by_decision(self, sample_db: str) -> None:
        with AuditReader(sample_db) as r:
            recs = r.query(decision="BLOCK")
        assert len(recs) == 1

    def test_filter_by_tool(self, sample_db: str) -> None:
        with AuditReader(sample_db) as r:
            recs = r.query(tool_name="bash")
        assert len(recs) == 1

    def test_filter_by_since(self, sample_db: str) -> None:
        with AuditReader(sample_db) as r:
            # Last 20 seconds should get 2 records
            recs = r.query(since_seconds=20)
        assert len(recs) == 2

    def test_limit(self, sample_db: str) -> None:
        with AuditReader(sample_db) as r:
            recs = r.query(limit=2)
        assert len(recs) == 2

    def test_empty_db(self, empty_db: str) -> None:
        with AuditReader(empty_db) as r:
            recs = r.query()
        assert recs == []

    def test_file_not_found(self, tmp_path) -> None:
        with pytest.raises(FileNotFoundError):
            AuditReader(str(tmp_path / "nope.db"))

    def test_extracts_tool_name(self, sample_db: str) -> None:
        with AuditReader(sample_db) as r:
            recs = r.query()
        tools = {rec["tool_name"] for rec in recs}
        assert "bash" in tools
        assert "read_file" in tools

    def test_extracts_reason(self, sample_db: str) -> None:
        with AuditReader(sample_db) as r:
            recs = r.query(decision="BLOCK")
        assert recs[0]["reason"] == "dangerous command"


# ===== AuditReader stats =====


class TestAuditReaderStats:
    def test_total(self, sample_db: str) -> None:
        with AuditReader(sample_db) as r:
            s = r.stats()
        assert s["total"] == 4

    def test_by_risk(self, sample_db: str) -> None:
        with AuditReader(sample_db) as r:
            s = r.stats()
        assert s["by_risk_level"]["LOW"] == 2
        assert s["by_risk_level"]["HIGH"] == 1

    def test_by_decision(self, sample_db: str) -> None:
        with AuditReader(sample_db) as r:
            s = r.stats()
        assert s["by_decision"]["ALLOW"] == 2

    def test_since_filter(self, sample_db: str) -> None:
        with AuditReader(sample_db) as r:
            s = r.stats(since_seconds=20)
        assert s["total"] == 2


# ===== Formatters =====


class TestFormatTable:
    def test_no_records(self) -> None:
        out = format_table([])
        assert "No records" in out

    def test_has_header(self, sample_db: str) -> None:
        with AuditReader(sample_db) as r:
            recs = r.query()
        out = format_table(recs, color=False)
        assert "Time" in out
        assert "Session" in out

    def test_no_color(self, sample_db: str) -> None:
        with AuditReader(sample_db) as r:
            recs = r.query()
        out = format_table(recs, color=False)
        assert "\033[" not in out

    def test_count_shown(self, sample_db: str) -> None:
        with AuditReader(sample_db) as r:
            recs = r.query()
        out = format_table(recs, color=False)
        assert "4 record(s) shown" in out


class TestFormatJson:
    def test_valid_json(self, sample_db: str) -> None:
        with AuditReader(sample_db) as r:
            recs = r.query()
        out = format_json_output(recs)
        data = json.loads(out)
        assert len(data) == 4
        assert "tool_name" in data[0]

    def test_empty(self) -> None:
        out = format_json_output([])
        assert json.loads(out) == []


class TestFormatCsv:
    def test_valid_csv(self, sample_db: str) -> None:
        with AuditReader(sample_db) as r:
            recs = r.query()
        out = format_csv_output(recs)
        reader = csv.DictReader(io.StringIO(out))
        rows = list(reader)
        assert len(rows) == 4
        assert "tool_name" in rows[0]

    def test_empty(self) -> None:
        out = format_csv_output([])
        assert out == ""


class TestFormatStats:
    def test_contains_total(self) -> None:
        s = {"total": 42, "by_risk_level": {}, "by_decision": {},
             "by_framework": {}, "top_sessions": []}
        out = format_stats(s)
        assert "42" in out

    def test_since_label(self) -> None:
        s = {"total": 0, "by_risk_level": {}, "by_decision": {},
             "by_framework": {}, "top_sessions": []}
        out = format_stats(s, since_label="last 24h")
        assert "last 24h" in out


# ===== Integration: run_audit =====


class TestRunAudit:
    def test_table_output(self, sample_db: str,
                           capsys: pytest.CaptureFixture[str]) -> None:
        code = run_audit(db_path=sample_db, color=False)
        assert code == 0
        out = capsys.readouterr().out
        assert "record(s) shown" in out

    def test_json_output(self, sample_db: str,
                          capsys: pytest.CaptureFixture[str]) -> None:
        code = run_audit(db_path=sample_db, fmt="json")
        assert code == 0
        data = json.loads(capsys.readouterr().out)
        assert len(data) == 4

    def test_csv_output(self, sample_db: str,
                         capsys: pytest.CaptureFixture[str]) -> None:
        code = run_audit(db_path=sample_db, fmt="csv")
        assert code == 0

    def test_stats_mode(self, sample_db: str,
                         capsys: pytest.CaptureFixture[str]) -> None:
        code = run_audit(db_path=sample_db, stats_mode=True)
        assert code == 0
        out = capsys.readouterr().out
        assert "Total records" in out

    def test_missing_db(self, tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
        code = run_audit(db_path=str(tmp_path / "nope.db"))
        assert code == 1
        err = capsys.readouterr().err
        assert "not found" in err

    def test_invalid_since(self, sample_db: str,
                            capsys: pytest.CaptureFixture[str]) -> None:
        code = run_audit(db_path=sample_db, since="invalid")
        assert code == 1

    def test_filter_combination(self, sample_db: str,
                                 capsys: pytest.CaptureFixture[str]) -> None:
        code = run_audit(
            db_path=sample_db, risk="high", decision="block", fmt="json"
        )
        assert code == 0
        data = json.loads(capsys.readouterr().out)
        assert len(data) == 1
