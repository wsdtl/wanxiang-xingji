"""统一战报表的 SQLite 仓储；不解释战斗或展示语义。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BattleReportHeaderRow:
    report_id: str
    share_id: str
    mode_id: str
    content_fingerprint: str
    summary_payload: str
    started_at: str
    finished_at: str
    detail_expires_at: str
    summary_expires_at: str


@dataclass(frozen=True)
class PublicBattleReportRow:
    header: BattleReportHeaderRow
    detail_available: bool
    segment_payloads: tuple[bytes, ...] = ()


class BattleReportStore:
    """只拥有战报主表和片段表的 SQL，不生成战报内容。"""

    def __init__(self, database) -> None:
        self.database = database

    def header_in_uow(self, uow, report_id: str) -> BattleReportHeaderRow | None:
        row = uow.connection.execute(
            """
            SELECT report_id, share_id, mode_id, content_fingerprint,
                   summary_payload, started_at, finished_at,
                   detail_expires_at, summary_expires_at
            FROM battle_report WHERE report_id = ?
            """,
            (report_id,),
        ).fetchone()
        return _header(row) if row is not None else None

    def insert_header_in_uow(
        self,
        uow,
        *,
        report_id: str,
        share_id: str,
        mode_id: str,
        content_fingerprint: str,
        summary_payload: str,
        started_at: str,
        finished_at: str,
        detail_expires_at: str,
        summary_expires_at: str,
        created_at: str,
    ) -> None:
        uow.connection.execute(
            """
            INSERT INTO battle_report(
                report_id, share_id, mode_id, content_fingerprint,
                summary_payload, started_at, finished_at,
                detail_expires_at, summary_expires_at,
                uncompressed_bytes, compressed_bytes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?)
            """,
            (
                report_id,
                share_id,
                mode_id,
                content_fingerprint,
                summary_payload,
                started_at,
                finished_at,
                detail_expires_at,
                summary_expires_at,
                created_at,
            ),
        )

    def segment_exists_in_uow(self, uow, report_id: str, segment_id: str) -> bool:
        return (
            uow.connection.execute(
                """
                SELECT 1 FROM battle_report_segment
                WHERE report_id = ? AND segment_id = ?
                """,
                (report_id, segment_id),
            ).fetchone()
            is not None
        )

    def append_segment_in_uow(
        self,
        uow,
        *,
        report_id: str,
        segment_id: str,
        detail_payload: bytes,
        uncompressed_bytes: int,
        summary_payload: str,
        started_at: str,
        finished_at: str,
        detail_expires_at: str,
        summary_expires_at: str,
    ) -> None:
        sequence = int(
            uow.connection.execute(
                """
                SELECT COALESCE(MAX(sequence), -1) + 1
                FROM battle_report_segment WHERE report_id = ?
                """,
                (report_id,),
            ).fetchone()[0]
        )
        compressed_bytes = len(detail_payload)
        uow.connection.execute(
            """
            INSERT INTO battle_report_segment(
                report_id, sequence, segment_id, detail_payload,
                uncompressed_bytes, compressed_bytes
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                report_id,
                sequence,
                segment_id,
                detail_payload,
                uncompressed_bytes,
                compressed_bytes,
            ),
        )
        uow.connection.execute(
            """
            UPDATE battle_report
            SET summary_payload = ?,
                started_at = MIN(started_at, ?),
                finished_at = MAX(finished_at, ?),
                detail_expires_at = MAX(detail_expires_at, ?),
                summary_expires_at = MAX(summary_expires_at, ?),
                uncompressed_bytes = uncompressed_bytes + ?,
                compressed_bytes = compressed_bytes + ?
            WHERE report_id = ?
            """,
            (
                summary_payload,
                started_at,
                finished_at,
                detail_expires_at,
                summary_expires_at,
                uncompressed_bytes,
                compressed_bytes,
                report_id,
            ),
        )

    def reference(self, report_id: str) -> tuple[str, str] | None:
        with self.database.unit_of_work(write=False) as uow:
            row = uow.connection.execute(
                "SELECT report_id, share_id FROM battle_report WHERE report_id = ?",
                (report_id,),
            ).fetchone()
        return (str(row["report_id"]), str(row["share_id"])) if row else None

    def load_public(
        self,
        share_id: str,
        *,
        logical_time: str,
        detail_finished_after: str,
        summary_finished_after: str,
    ) -> PublicBattleReportRow | None:
        with self.database.unit_of_work(write=False) as uow:
            row = uow.connection.execute(
                """
                SELECT report_id, share_id, mode_id, content_fingerprint,
                       summary_payload, started_at, finished_at,
                       detail_expires_at, summary_expires_at
                FROM battle_report
                WHERE share_id = ?
                  AND summary_expires_at > ?
                  AND finished_at > ?
                """,
                (share_id, logical_time, summary_finished_after),
            ).fetchone()
            if row is None:
                return None
            header = _header(row)
            detail_available = (
                header.detail_expires_at > logical_time
                and header.finished_at > detail_finished_after
            )
            payloads = ()
            if detail_available:
                segment_rows = uow.connection.execute(
                    """
                    SELECT detail_payload FROM battle_report_segment
                    WHERE report_id = ? ORDER BY sequence
                    """,
                    (header.report_id,),
                ).fetchall()
                payloads = tuple(bytes(item[0]) for item in segment_rows)
        return PublicBattleReportRow(header, detail_available, payloads)

    def cleanup(
        self,
        *,
        logical_time: str,
        detail_finished_cutoff: str,
        summary_finished_cutoff: str,
    ) -> tuple[int, int]:
        with self.database.unit_of_work() as uow:
            detail = uow.connection.execute(
                """
                DELETE FROM battle_report_segment
                WHERE report_id IN (
                    SELECT report_id FROM battle_report
                    WHERE detail_expires_at <= ? OR finished_at <= ?
                )
                """,
                (logical_time, detail_finished_cutoff),
            ).rowcount
            summaries = uow.connection.execute(
                """
                DELETE FROM battle_report
                WHERE summary_expires_at <= ? OR finished_at <= ?
                """,
                (logical_time, summary_finished_cutoff),
            ).rowcount
            uow.commit()
        return int(detail), int(summaries)

    def share_id_exists_in_uow(self, uow, share_id: str) -> bool:
        return (
            uow.connection.execute(
                "SELECT 1 FROM battle_report WHERE share_id = ?",
                (share_id,),
            ).fetchone()
            is not None
        )


def _header(row) -> BattleReportHeaderRow:
    return BattleReportHeaderRow(
        str(row["report_id"]),
        str(row["share_id"]),
        str(row["mode_id"]),
        str(row["content_fingerprint"]),
        str(row["summary_payload"]),
        str(row["started_at"]),
        str(row["finished_at"]),
        str(row["detail_expires_at"]),
        str(row["summary_expires_at"]),
    )


__all__ = [
    "BattleReportHeaderRow",
    "BattleReportStore",
    "PublicBattleReportRow",
]
