"""短期事实、通知和可选外部投递的安全清理。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .sqlite import SqliteDatabase


FACT_RETENTION = timedelta(days=7)
READ_NOTIFICATION_RETENTION = timedelta(days=3)
UNREAD_NOTIFICATION_RETENTION = timedelta(days=14)
PUBLISHED_DELIVERY_RETENTION = timedelta(days=1)
RETENTION_BATCH_SIZE = 5_000


@dataclass(frozen=True)
class RetentionReceipt:
    notifications: int
    facts: int
    published_deliveries: int


class PersistenceRetentionService:
    """按事实检查点清理可重建数据，不触碰角色和资产聚合。"""

    def __init__(
        self,
        database: SqliteDatabase,
        *,
        fact_retention: timedelta = FACT_RETENTION,
        read_notification_retention: timedelta = READ_NOTIFICATION_RETENTION,
        unread_notification_retention: timedelta = UNREAD_NOTIFICATION_RETENTION,
        published_delivery_retention: timedelta = PUBLISHED_DELIVERY_RETENTION,
        batch_size: int = RETENTION_BATCH_SIZE,
    ) -> None:
        if any(
            value.total_seconds() < 0
            for value in (
                fact_retention,
                read_notification_retention,
                unread_notification_retention,
                published_delivery_retention,
            )
        ):
            raise ValueError("持久化保留期限不能为负数")
        if batch_size < 1:
            raise ValueError("持久化清理批量必须大于 0")
        self.database = database
        self.fact_retention = fact_retention
        self.read_notification_retention = read_notification_retention
        self.unread_notification_retention = unread_notification_retention
        self.published_delivery_retention = published_delivery_retention
        self.batch_size = batch_size

    def cleanup(self, *, logical_time: datetime) -> RetentionReceipt:
        _aware(logical_time)
        with self.database.unit_of_work() as uow:
            notifications = self._cleanup_notifications(uow, logical_time)
            published_deliveries = self._cleanup_published_deliveries(uow, logical_time)
            facts = self._cleanup_facts(uow, logical_time)
            uow.commit()
        return RetentionReceipt(notifications, facts, published_deliveries)

    def _cleanup_notifications(self, uow, logical_time: datetime) -> int:
        now = logical_time.isoformat()
        read_cutoff = (logical_time - self.read_notification_retention).isoformat()
        unread_cutoff = (logical_time - self.unread_notification_retention).isoformat()
        cursor = uow.connection.execute(
            """
            DELETE FROM notification_entry
            WHERE notification_id IN (
                SELECT notification_id
                FROM notification_entry
                WHERE (expires_at IS NOT NULL AND julianday(expires_at) <= julianday(?))
                   OR (status <> 'unread' AND julianday(COALESCE(read_at, created_at)) <= julianday(?))
                   OR (status = 'unread' AND julianday(created_at) <= julianday(?))
                ORDER BY created_at, notification_id
                LIMIT ?
            )
            """,
            (now, read_cutoff, unread_cutoff, self.batch_size),
        )
        return cursor.rowcount

    def _cleanup_published_deliveries(self, uow, logical_time: datetime) -> int:
        cutoff = (logical_time - self.published_delivery_retention).isoformat()
        cursor = uow.connection.execute(
            """
            DELETE FROM outbox_event
            WHERE (transaction_id, sequence) IN (
                SELECT transaction_id, sequence
                FROM outbox_event
                WHERE published_at IS NOT NULL
                  AND julianday(published_at) <= julianday(?)
                ORDER BY published_at, transaction_id, sequence
                LIMIT ?
            )
            """,
            (cutoff, self.batch_size),
        )
        return cursor.rowcount

    def _cleanup_facts(self, uow, logical_time: datetime) -> int:
        cutoff = (logical_time - self.fact_retention).isoformat()
        checkpoint = uow.connection.execute(
            "SELECT MIN(fact_offset) AS value FROM projection_checkpoint"
        ).fetchone()
        if checkpoint["value"] is None:
            watermark = uow.connection.execute(
                "SELECT COALESCE(MAX(fact_offset), 0) AS value FROM fact_journal"
            ).fetchone()["value"]
        else:
            watermark = checkpoint["value"]
        cursor = uow.connection.execute(
            """
            DELETE FROM fact_journal
            WHERE fact_offset IN (
                SELECT fact_offset
                FROM fact_journal AS fact
                WHERE fact.fact_offset <= ?
                  AND julianday(fact.occurred_at) <= julianday(?)
                  AND NOT EXISTS (
                      SELECT 1
                      FROM notification_entry AS notification
                      WHERE notification.source_fact_offset = fact.fact_offset
                  )
                ORDER BY fact.fact_offset
                LIMIT ?
            )
            """,
            (int(watermark), cutoff, self.batch_size),
        )
        return cursor.rowcount


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("持久化清理时间必须包含时区")


__all__ = [
    "FACT_RETENTION",
    "PUBLISHED_DELIVERY_RETENTION",
    "READ_NOTIFICATION_RETENTION",
    "RetentionReceipt",
    "PersistenceRetentionService",
    "RETENTION_BATCH_SIZE",
    "UNREAD_NOTIFICATION_RETENTION",
]
