"""统一战报表的 SQLite 仓储；不解释战斗或展示语义。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


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
    segment_count: int = 0


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
                started_at = CASE
                    WHEN julianday(started_at) <= julianday(?) THEN started_at
                    ELSE ?
                END,
                finished_at = CASE
                    WHEN julianday(finished_at) >= julianday(?) THEN finished_at
                    ELSE ?
                END,
                detail_expires_at = CASE
                    WHEN julianday(detail_expires_at) >= julianday(?) THEN detail_expires_at
                    ELSE ?
                END,
                summary_expires_at = CASE
                    WHEN julianday(summary_expires_at) >= julianday(?) THEN summary_expires_at
                    ELSE ?
                END,
                uncompressed_bytes = uncompressed_bytes + ?,
                compressed_bytes = compressed_bytes + ?
            WHERE report_id = ?
            """,
            (
                summary_payload,
                started_at,
                started_at,
                finished_at,
                finished_at,
                detail_expires_at,
                detail_expires_at,
                summary_expires_at,
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
        segment_offset: int | None = None,
        segment_limit: int | None = None,
    ) -> PublicBattleReportRow | None:
        if segment_offset is not None and segment_offset < 0:
            raise ValueError("segment_offset 不能小于 0")
        if segment_limit is not None and segment_limit < 1:
            raise ValueError("segment_limit 必须大于 0")
        with self.database.unit_of_work(write=False) as uow:
            row = uow.connection.execute(
                """
                SELECT report_id, share_id, mode_id, content_fingerprint,
                       summary_payload, started_at, finished_at,
                       detail_expires_at, summary_expires_at
                FROM battle_report
                WHERE share_id = ?
                  AND datetime(summary_expires_at) > datetime(?)
                  AND datetime(finished_at) > datetime(?)
                """,
                (share_id, logical_time, summary_finished_after),
            ).fetchone()
            if row is None:
                return None
            header = _header(row)
            detail_available = (
                _instant_after(header.detail_expires_at, logical_time)
                and _instant_after(header.finished_at, detail_finished_after)
            )
            payloads = ()
            segment_count = 0
            if detail_available:
                segment_count = int(
                    uow.connection.execute(
                        """
                        SELECT COUNT(*) FROM battle_report_segment
                        WHERE report_id = ?
                        """,
                        (header.report_id,),
                    ).fetchone()[0]
                )
                sql = """
                    SELECT detail_payload FROM battle_report_segment
                    WHERE report_id = ? ORDER BY sequence
                """
                parameters: tuple[object, ...] = (header.report_id,)
                if segment_limit is not None:
                    sql += " LIMIT ? OFFSET ?"
                    parameters = (
                        header.report_id,
                        segment_limit,
                        segment_offset or 0,
                    )
                elif segment_offset is not None:
                    sql += " LIMIT -1 OFFSET ?"
                    parameters = (header.report_id, segment_offset)
                segment_rows = uow.connection.execute(sql, parameters).fetchall()
                payloads = tuple(bytes(item[0]) for item in segment_rows)
        return PublicBattleReportRow(
            header,
            detail_available,
            payloads,
            segment_count,
        )

    def public_exists(
        self,
        share_id: str,
        *,
        logical_time: str,
        summary_finished_after: str,
    ) -> bool:
        """只检查公开摘要是否仍有效，不读取或解压战报片段。"""

        with self.database.unit_of_work(write=False) as uow:
            row = uow.connection.execute(
                """
                SELECT 1 FROM battle_report
                WHERE share_id = ?
                  AND datetime(summary_expires_at) > datetime(?)
                  AND datetime(finished_at) > datetime(?)
                """,
                (share_id, logical_time, summary_finished_after),
            ).fetchone()
        return row is not None

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
                    WHERE datetime(detail_expires_at) <= datetime(?)
                       OR datetime(finished_at) <= datetime(?)
                )
                """,
                (logical_time, detail_finished_cutoff),
            ).rowcount
            summaries = uow.connection.execute(
                """
                DELETE FROM battle_report
                WHERE datetime(summary_expires_at) <= datetime(?)
                   OR datetime(finished_at) <= datetime(?)
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


def _instant_after(left: str, right: str) -> bool:
    return datetime.fromisoformat(left) > datetime.fromisoformat(right)


__all__ = [
    "BattleReportHeaderRow",
    "BattleReportStore",
    "PublicBattleReportRow",
]
