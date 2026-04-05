from __future__ import annotations

import sqlite3
from pathlib import Path

from orbit.store.sqlite_store import SQLiteStore


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def test_delete_all_sessions_clears_session_history_tables_even_without_session_rows(tmp_path: Path):
    db_path = tmp_path / "orbit.db"
    store = SQLiteStore(db_path)
    conn = store.conn

    conn.execute("INSERT INTO events(event_id, run_id, timestamp, data) VALUES (?, ?, ?, ?)", ("ev1", "run_orphan", "2026-04-05T12:00:00+00:00", "{}"))
    conn.execute("INSERT INTO context_artifacts(context_artifact_id, run_id, data) VALUES (?, ?, ?)", ("art1", "run_orphan", "{}"))
    conn.execute("INSERT INTO tool_invocations(tool_invocation_id, run_id, data) VALUES (?, ?, ?)", ("tool1", "run_orphan", "{}"))
    conn.execute("INSERT INTO approval_requests(approval_request_id, run_id, data) VALUES (?, ?, ?)", ("apr1", "run_orphan", "{}"))
    conn.execute("INSERT INTO approval_decisions(approval_decision_id, approval_request_id, data) VALUES (?, ?, ?)", ("apd1", "apr1", "{}"))
    conn.execute("INSERT INTO sessions(session_id, conversation_id, updated_at, data) VALUES (?, ?, ?, ?)", ("sess1", "run_live", "2026-04-05T12:00:00+00:00", "{}"))
    conn.execute("INSERT INTO session_messages(message_id, session_id, turn_index, created_at, data) VALUES (?, ?, ?, ?, ?)", ("msg1", "sess1", 1, "2026-04-05T12:00:00+00:00", "{}"))
    conn.commit()

    assert _count(conn, "sessions") == 1
    assert _count(conn, "session_messages") == 1
    assert _count(conn, "events") == 1
    assert _count(conn, "context_artifacts") == 1
    assert _count(conn, "tool_invocations") == 1
    assert _count(conn, "approval_requests") == 1
    assert _count(conn, "approval_decisions") == 1

    store.delete_all_sessions()

    assert _count(conn, "sessions") == 0
    assert _count(conn, "session_messages") == 0
    assert _count(conn, "events") == 0
    assert _count(conn, "context_artifacts") == 0
    assert _count(conn, "tool_invocations") == 0
    assert _count(conn, "approval_requests") == 0
    assert _count(conn, "approval_decisions") == 0
