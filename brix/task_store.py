from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from brix.domain import Approval, BrowserSession, BrowserTask, TaskEvent


class TaskStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def _migrate(self) -> None:
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS browser_tasks (id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS browser_sessions (id TEXT PRIMARY KEY, task_id TEXT NOT NULL UNIQUE, state TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS task_events (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, type TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS approvals (id TEXT PRIMARY KEY, task_id TEXT NOT NULL, status TEXT NOT NULL, data TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS idx_browser_tasks_status ON browser_tasks(status, created_at);
                CREATE INDEX IF NOT EXISTS idx_task_events_task ON task_events(task_id, id);
                INSERT OR IGNORE INTO schema_migrations(version) VALUES (1);
            """)

    @staticmethod
    def _json(model: Any) -> str:
        return json.dumps(model.model_dump(mode="json"), separators=(",", ":"))

    def save_task(self, task: BrowserTask) -> BrowserTask:
        with self.connection() as db:
            db.execute("INSERT OR REPLACE INTO browser_tasks VALUES (?, ?, ?, ?)", (task.id, task.status, task.created_at.isoformat(), self._json(task)))
        return task

    def get_task(self, task_id: str) -> BrowserTask | None:
        with self.connection() as db:
            row = db.execute("SELECT data FROM browser_tasks WHERE id=?", (task_id,)).fetchone()
        return BrowserTask.model_validate_json(row["data"]) if row else None

    def list_tasks(self) -> list[BrowserTask]:
        with self.connection() as db:
            rows = db.execute("SELECT data FROM browser_tasks ORDER BY created_at DESC").fetchall()
        return [BrowserTask.model_validate_json(row["data"]) for row in rows]

    def save_session(self, session: BrowserSession) -> BrowserSession:
        with self.connection() as db:
            db.execute("INSERT OR REPLACE INTO browser_sessions VALUES (?, ?, ?, ?)", (session.id, session.task_id, session.state, self._json(session)))
        return session

    def get_session(self, session_id: str) -> BrowserSession | None:
        with self.connection() as db:
            row = db.execute("SELECT data FROM browser_sessions WHERE id=?", (session_id,)).fetchone()
        return BrowserSession.model_validate_json(row["data"]) if row else None

    def list_sessions(self) -> list[BrowserSession]:
        with self.connection() as db:
            rows = db.execute("SELECT data FROM browser_sessions").fetchall()
        return [BrowserSession.model_validate_json(row["data"]) for row in rows]

    def add_event(self, event: TaskEvent) -> TaskEvent:
        with self.connection() as db:
            cursor = db.execute("INSERT INTO task_events(task_id,type,created_at,data) VALUES(?,?,?,?)", (event.task_id, event.type, event.created_at.isoformat(), self._json(event)))
            event.id = cursor.lastrowid
            db.execute("UPDATE task_events SET data=? WHERE id=?", (self._json(event), event.id))
        return event

    def events(self, task_id: str, after: int = 0) -> list[TaskEvent]:
        with self.connection() as db:
            rows = db.execute("SELECT data FROM task_events WHERE task_id=? AND id>? ORDER BY id LIMIT 1000", (task_id, after)).fetchall()
        return [TaskEvent.model_validate_json(row["data"]) for row in rows]

    def save_approval(self, approval: Approval) -> Approval:
        with self.connection() as db:
            db.execute("INSERT OR REPLACE INTO approvals VALUES(?,?,?,?)", (approval.id, approval.task_id, approval.status, self._json(approval)))
        return approval

    def get_approval(self, approval_id: str) -> Approval | None:
        with self.connection() as db:
            row = db.execute("SELECT data FROM approvals WHERE id=?", (approval_id,)).fetchone()
        return Approval.model_validate_json(row["data"]) if row else None

