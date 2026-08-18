from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .model import Memory, MemoryScope


class SQLiteMemoryStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self._connection = sqlite3.connect(str(path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("""CREATE TABLE IF NOT EXISTS memory (
            id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, scope TEXT NOT NULL,
            owner_id TEXT NOT NULL, content TEXT NOT NULL, fingerprint TEXT NOT NULL,
            importance REAL NOT NULL, created_at TEXT NOT NULL, expires_at TEXT,
            metadata TEXT NOT NULL,
            UNIQUE(tenant_id, scope, owner_id, fingerprint))""")
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS memory_lookup "
            "ON memory(tenant_id, scope, owner_id, created_at)"
        )
        self._connection.commit()

    def upsert(self, memory: Memory) -> Memory:
        with self._connection:
            existing = self._connection.execute(
                "SELECT * FROM memory WHERE tenant_id=? AND scope=? "
                "AND owner_id=? AND fingerprint=?",
                (memory.tenant_id, memory.scope.value, memory.owner_id, memory.fingerprint),
            ).fetchone()
            if existing:
                current = _row(existing)
                winner = (
                    memory
                    if (memory.importance, memory.created_at, memory.id)
                    > (current.importance, current.created_at, current.id)
                    else current
                )
                if winner is memory:
                    self._connection.execute(
                        "UPDATE memory SET content=?, importance=?, created_at=?, "
                        "expires_at=?, metadata=? WHERE id=?",
                        (
                            memory.content,
                            memory.importance,
                            memory.created_at.isoformat(),
                            _time(memory.expires_at),
                            json.dumps(memory.metadata, sort_keys=True),
                            current.id,
                        ),
                    )
                    return Memory(
                        current.id,
                        memory.tenant_id,
                        memory.scope,
                        memory.owner_id,
                        memory.content,
                        memory.fingerprint,
                        memory.importance,
                        memory.created_at,
                        memory.expires_at,
                        memory.metadata,
                    )
                return current
            self._connection.execute(
                "INSERT INTO memory VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    memory.id,
                    memory.tenant_id,
                    memory.scope.value,
                    memory.owner_id,
                    memory.content,
                    memory.fingerprint,
                    memory.importance,
                    memory.created_at.isoformat(),
                    _time(memory.expires_at),
                    json.dumps(memory.metadata, sort_keys=True),
                ),
            )
            return memory

    def list(
        self, tenant_id: str, scope: MemoryScope, owner_id: str, now: datetime
    ) -> list[Memory]:
        rows = self._connection.execute(
            "SELECT * FROM memory WHERE tenant_id=? AND scope=? AND owner_id=? "
            "AND (expires_at IS NULL OR expires_at>?) "
            "ORDER BY importance DESC, created_at DESC, id ASC",
            (tenant_id, scope.value, owner_id, now.isoformat()),
        ).fetchall()
        return [_row(row) for row in rows]

    def expire(self, now: datetime) -> int:
        with self._connection:
            cursor = self._connection.execute(
                "DELETE FROM memory WHERE expires_at IS NOT NULL AND expires_at<=?",
                (now.isoformat(),),
            )
            return cursor.rowcount

    def delete(self, tenant_id: str, memory_id: str) -> bool:
        with self._connection:
            return (
                self._connection.execute(
                    "DELETE FROM memory WHERE tenant_id=? AND id=?", (tenant_id, memory_id)
                ).rowcount
                == 1
            )

    def forget(
        self, tenant_id: str, scope: MemoryScope | None = None, owner_id: str | None = None
    ) -> int:
        clauses, values = ["tenant_id=?"], [tenant_id]
        if scope is not None:
            clauses.append("scope=?")
            values.append(scope.value)
        if owner_id is not None:
            clauses.append("owner_id=?")
            values.append(owner_id)
        with self._connection:
            return self._connection.execute(
                f"DELETE FROM memory WHERE {' AND '.join(clauses)}", values
            ).rowcount

    def close(self) -> None:
        self._connection.close()


def _time(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _row(row: sqlite3.Row) -> Memory:
    return Memory(
        row["id"],
        row["tenant_id"],
        MemoryScope(row["scope"]),
        row["owner_id"],
        row["content"],
        row["fingerprint"],
        row["importance"],
        datetime.fromisoformat(row["created_at"]).astimezone(UTC),
        datetime.fromisoformat(row["expires_at"]).astimezone(UTC) if row["expires_at"] else None,
        json.loads(row["metadata"]),
    )
