"""
SQLite-backed blackboard store.

The store is the single source of truth for every project's graph. It is the only
component that touches persistent state, which keeps the rest of the system pure
and testable, and keeps the whole engine runnable from one file with no network
dependency (an important property for the future air-gapped build).

Concurrency note: multiple workers may try to claim the same Intent at once.
`claim_intent` performs the claim as a single conditional UPDATE inside a
transaction, so exactly one worker can win. This is the atomic primitive that lets
workers coordinate purely through the board (stigmergy) without talking to each
other directly.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from .models import (
    Fact,
    Graph,
    Hint,
    Intent,
    IntentStatus,
    ProjectStatus,
    _new_id,
    _now,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id         TEXT PRIMARY KEY,
    origin     TEXT NOT NULL,
    goal       TEXT NOT NULL,
    status     TEXT NOT NULL,
    result     TEXT,
    iteration  INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS facts (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL,
    content         TEXT NOT NULL,
    source_intent_id TEXT,
    created_by      TEXT,
    created_at      TEXT NOT NULL,
    metadata        TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (project_id) REFERENCES projects(id)
);
CREATE TABLE IF NOT EXISTS intents (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL,
    description   TEXT NOT NULL,
    status        TEXT NOT NULL,
    created_by    TEXT,
    claimed_by    TEXT,
    parent_fact_id TEXT,
    created_at    TEXT NOT NULL,
    metadata      TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (project_id) REFERENCES projects(id)
);
CREATE TABLE IF NOT EXISTS hints (
    id         TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    content    TEXT NOT NULL,
    consumed   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);
CREATE INDEX IF NOT EXISTS idx_facts_project   ON facts(project_id);
CREATE INDEX IF NOT EXISTS idx_intents_project ON intents(project_id);
CREATE INDEX IF NOT EXISTS idx_hints_project   ON hints(project_id);
"""


def _iso(dt: datetime) -> str:
    return dt.isoformat()


class GraphStore:
    """Thread-safe persistence for the blackboard."""

    def __init__(self, db_path: str | Path = "fapta.db"):
        self.db_path = str(db_path)
        # check_same_thread=False + an explicit lock lets the dispatcher's worker
        # threads share one connection safely.
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._lock = threading.RLock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---- projects -------------------------------------------------------

    def create_project(self, origin: str, goal: str) -> str:
        pid = _new_id("proj")
        with self._lock:
            self._conn.execute(
                "INSERT INTO projects (id, origin, goal, status, iteration, created_at)"
                " VALUES (?, ?, ?, ?, 0, ?)",
                (pid, origin, goal, ProjectStatus.ACTIVE.value, _iso(_now())),
            )
            self._conn.commit()
        return pid

    def list_projects(self, status: ProjectStatus | None = None) -> list[str]:
        with self._lock:
            if status is None:
                rows = self._conn.execute("SELECT id FROM projects").fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT id FROM projects WHERE status = ?", (status.value,)
                ).fetchall()
        return [r["id"] for r in rows]

    def set_status(self, project_id: str, status: ProjectStatus) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE projects SET status = ? WHERE id = ?",
                (status.value, project_id),
            )
            self._conn.commit()

    def set_result(self, project_id: str, result: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE projects SET result = ?, status = ? WHERE id = ?",
                (result, ProjectStatus.COMPLETE.value, project_id),
            )
            self._conn.commit()

    def bump_iteration(self, project_id: str) -> int:
        with self._lock:
            self._conn.execute(
                "UPDATE projects SET iteration = iteration + 1 WHERE id = ?",
                (project_id,),
            )
            row = self._conn.execute(
                "SELECT iteration FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            self._conn.commit()
        return row["iteration"] if row else 0

    # ---- writes ---------------------------------------------------------

    def add_fact(self, project_id: str, fact: Fact) -> Fact:
        with self._lock:
            self._conn.execute(
                "INSERT INTO facts (id, project_id, content, source_intent_id,"
                " created_by, created_at, metadata) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    fact.id,
                    project_id,
                    fact.content,
                    fact.source_intent_id,
                    fact.created_by,
                    _iso(fact.created_at),
                    json.dumps(fact.metadata),
                ),
            )
            self._conn.commit()
        return fact

    def add_intent(self, project_id: str, intent: Intent) -> Intent:
        with self._lock:
            self._conn.execute(
                "INSERT INTO intents (id, project_id, description, status,"
                " created_by, claimed_by, parent_fact_id, created_at, metadata)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    intent.id,
                    project_id,
                    intent.description,
                    intent.status.value,
                    intent.created_by,
                    intent.claimed_by,
                    intent.parent_fact_id,
                    _iso(intent.created_at),
                    json.dumps(intent.metadata),
                ),
            )
            self._conn.commit()
        return intent

    def add_hint(self, project_id: str, content: str) -> Hint:
        hint = Hint(content=content)
        with self._lock:
            self._conn.execute(
                "INSERT INTO hints (id, project_id, content, consumed, created_at)"
                " VALUES (?, ?, ?, 0, ?)",
                (hint.id, project_id, hint.content, _iso(hint.created_at)),
            )
            self._conn.commit()
        return hint

    def claim_intent(self, project_id: str, intent_id: str, worker: str) -> bool:
        """
        Atomically claim an OPEN intent. Returns True only for the single caller
        that wins the race; everyone else gets False and should pick another intent.
        """
        with self._lock:
            cur = self._conn.execute(
                "UPDATE intents SET status = ?, claimed_by = ?"
                " WHERE id = ? AND project_id = ? AND status = ?",
                (
                    IntentStatus.CLAIMED.value,
                    worker,
                    intent_id,
                    project_id,
                    IntentStatus.OPEN.value,
                ),
            )
            self._conn.commit()
            return cur.rowcount == 1

    def finish_intent(
        self, intent_id: str, status: IntentStatus = IntentStatus.DONE
    ) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE intents SET status = ? WHERE id = ?",
                (status.value, intent_id),
            )
            self._conn.commit()

    def consume_hints(self, project_id: str) -> list[Hint]:
        """Mark all unconsumed hints consumed and return them (for a Reason task)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM hints WHERE project_id = ? AND consumed = 0",
                (project_id,),
            ).fetchall()
            self._conn.execute(
                "UPDATE hints SET consumed = 1 WHERE project_id = ? AND consumed = 0",
                (project_id,),
            )
            self._conn.commit()
        return [
            Hint(
                id=r["id"],
                content=r["content"],
                created_at=datetime.fromisoformat(r["created_at"]),
                consumed=True,
            )
            for r in rows
        ]

    # ---- reads ----------------------------------------------------------

    def get_graph(self, project_id: str) -> Graph:
        with self._lock:
            proj = self._conn.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if proj is None:
                raise KeyError(f"unknown project {project_id!r}")
            fact_rows = self._conn.execute(
                "SELECT * FROM facts WHERE project_id = ? ORDER BY created_at",
                (project_id,),
            ).fetchall()
            intent_rows = self._conn.execute(
                "SELECT * FROM intents WHERE project_id = ? ORDER BY created_at",
                (project_id,),
            ).fetchall()
            hint_rows = self._conn.execute(
                "SELECT * FROM hints WHERE project_id = ? ORDER BY created_at",
                (project_id,),
            ).fetchall()

        return Graph(
            project_id=proj["id"],
            origin=proj["origin"],
            goal=proj["goal"],
            status=ProjectStatus(proj["status"]),
            result=proj["result"],
            iteration=proj["iteration"],
            facts=[
                Fact(
                    id=r["id"],
                    content=r["content"],
                    source_intent_id=r["source_intent_id"],
                    created_by=r["created_by"],
                    created_at=datetime.fromisoformat(r["created_at"]),
                    metadata=json.loads(r["metadata"]),
                )
                for r in fact_rows
            ],
            intents=[
                Intent(
                    id=r["id"],
                    description=r["description"],
                    status=IntentStatus(r["status"]),
                    created_by=r["created_by"],
                    claimed_by=r["claimed_by"],
                    parent_fact_id=r["parent_fact_id"],
                    created_at=datetime.fromisoformat(r["created_at"]),
                    metadata=json.loads(r["metadata"]),
                )
                for r in intent_rows
            ],
            hints=[
                Hint(
                    id=r["id"],
                    content=r["content"],
                    created_at=datetime.fromisoformat(r["created_at"]),
                    consumed=bool(r["consumed"]),
                )
                for r in hint_rows
            ],
        )
