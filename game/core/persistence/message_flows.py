"""协议中立的短期消息流水 SQLite 仓储。"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Iterator


@dataclass(frozen=True)
class MessageFlowRow:
    """持久化层返回的原始消息流水行。"""

    flow_id: int
    direction: str
    adapter: str
    request_id: str
    client_id: str
    sender_name: str
    message_type: str
    content: str
    image: str
    interactions_json: str
    content_truncated: bool
    created_at: str
    created_at_timestamp: float


class MessageFlowStore:
    """只负责短期消息表和分页查询，不解释消息及交互语义。"""

    def __init__(self, path: Path | str, *, busy_timeout_ms: int = 5000) -> None:
        self.path = Path(path)
        self.busy_timeout_ms = max(1, int(busy_timeout_ms))
        self._lock = RLock()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            tables = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' LIMIT 1"
            ).fetchone()
            if tables is None:
                connection.execute("PRAGMA auto_vacuum = INCREMENTAL")
                connection.execute("VACUUM")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS message_console_flows (
                    flow_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    direction TEXT NOT NULL,
                    adapter TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    sender_name TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    image TEXT NOT NULL,
                    interactions_json TEXT NOT NULL,
                    content_truncated INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    created_at_timestamp REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_message_console_created
                ON message_console_flows(created_at_timestamp);
                """
            )

    def insert(
        self,
        *,
        direction: str,
        adapter: str,
        request_id: str,
        client_id: str,
        sender_name: str,
        message_type: str,
        content: str,
        image: str,
        interactions_json: str,
        content_truncated: bool,
        created_at: str,
        created_at_timestamp: float,
    ) -> MessageFlowRow:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO message_console_flows (
                    direction, adapter, request_id, client_id, sender_name,
                    message_type, content, image, interactions_json,
                    content_truncated, created_at, created_at_timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    direction,
                    adapter,
                    request_id,
                    client_id,
                    sender_name,
                    message_type,
                    content,
                    image,
                    interactions_json,
                    int(content_truncated),
                    created_at,
                    created_at_timestamp,
                ),
            )
            row = connection.execute(
                "SELECT * FROM message_console_flows WHERE flow_id = ?",
                (int(cursor.lastrowid),),
            ).fetchone()
        if row is None:
            raise RuntimeError("消息流水写入后无法读取")
        return _row(row)

    def recent(self, *, limit: int, before_id: int | None = None) -> list[MessageFlowRow]:
        count = max(1, int(limit))
        query = "SELECT * FROM message_console_flows"
        parameters: list[object] = []
        if before_id is not None and before_id > 0:
            query += " WHERE flow_id < ?"
            parameters.append(before_id)
        query += " ORDER BY flow_id DESC LIMIT ?"
        parameters.append(count)
        with self._lock, self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return list(reversed([_row(row) for row in rows]))

    def after(self, flow_id: int, *, limit: int) -> list[MessageFlowRow]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM message_console_flows
                WHERE flow_id > ?
                ORDER BY flow_id ASC
                LIMIT ?
                """,
                (max(0, int(flow_id)), max(1, int(limit))),
            ).fetchall()
        return [_row(row) for row in rows]

    def get(self, flow_id: int) -> MessageFlowRow | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM message_console_flows WHERE flow_id = ?",
                (int(flow_id),),
            ).fetchone()
        return _row(row) if row is not None else None

    def cleanup(self, *, cutoff_timestamp: float, max_rows: int) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM message_console_flows WHERE created_at_timestamp < ?",
                (float(cutoff_timestamp),),
            )
            connection.execute(
                """
                DELETE FROM message_console_flows
                WHERE flow_id NOT IN (
                    SELECT flow_id FROM message_console_flows
                    ORDER BY flow_id DESC LIMIT ?
                )
                """,
                (max(1, int(max_rows)),),
            )
            connection.execute("PRAGMA optimize")
            if int(connection.execute("PRAGMA auto_vacuum").fetchone()[0]) == 2:
                connection.execute("PRAGMA incremental_vacuum(128)")

    def referenced_images(self) -> set[str]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT image FROM message_console_flows WHERE image <> ''"
            ).fetchall()
        return {str(row["image"]) for row in rows}

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.path,
            timeout=self.busy_timeout_ms / 1000,
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
            with connection:
                yield connection
        finally:
            connection.close()


def _row(row: sqlite3.Row) -> MessageFlowRow:
    return MessageFlowRow(
        flow_id=int(row["flow_id"]),
        direction=str(row["direction"]),
        adapter=str(row["adapter"]),
        request_id=str(row["request_id"]),
        client_id=str(row["client_id"]),
        sender_name=str(row["sender_name"]),
        message_type=str(row["message_type"]),
        content=str(row["content"]),
        image=str(row["image"]),
        interactions_json=str(row["interactions_json"]),
        content_truncated=bool(row["content_truncated"]),
        created_at=str(row["created_at"]),
        created_at_timestamp=float(row["created_at_timestamp"]),
    )


__all__ = ["MessageFlowRow", "MessageFlowStore"]
