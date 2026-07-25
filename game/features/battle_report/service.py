"""统一战报的持久化、公开读取和保留期清理。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import json
from secrets import token_urlsafe

from game.rules.battle_report import (
    BattleReportDraft,
    BattleReportReference,
    BattleReportSummary,
    BattleReportView,
    decode_segment,
    encode_segment,
)

from .assembly import BattleReportBuilder


DETAIL_RETENTION = timedelta(hours=6)
SUMMARY_RETENTION = timedelta(hours=24)


@dataclass(frozen=True)
class PreparedBattleReport:
    """已经在写事务外完成序列化和压缩的战报。"""

    draft: BattleReportDraft
    detail_payload: bytes
    uncompressed_bytes: int

    def __post_init__(self) -> None:
        if not isinstance(self.draft, BattleReportDraft):
            raise TypeError("PreparedBattleReport.draft 类型不正确")
        if not isinstance(self.detail_payload, bytes) or not self.detail_payload:
            raise ValueError("PreparedBattleReport.detail_payload 不能为空")
        if self.uncompressed_bytes < 1:
            raise ValueError("PreparedBattleReport.uncompressed_bytes 必须大于 0")

    def with_summary(self, summary: BattleReportSummary) -> "PreparedBattleReport":
        """保留已冻结片段，只替换最终结算后才能确定的摘要。"""

        if not isinstance(summary, BattleReportSummary):
            raise TypeError("summary 必须是 BattleReportSummary")
        return replace(self, draft=replace(self.draft, summary=summary))


class BattleReportService:
    """一张报告主表和一张片段表承接所有战斗模式。"""

    def __init__(self, database, store, builder: BattleReportBuilder) -> None:
        self.database = database
        self.store = store
        self.builder = builder

    def capture(self, draft: BattleReportDraft) -> BattleReportReference:
        prepared = self.prepare_capture(draft)
        with self.database.unit_of_work() as uow:
            reference = self.capture_prepared_in_uow(uow, prepared)
            uow.commit()
            return reference

    @staticmethod
    def prepare_capture(draft: BattleReportDraft) -> PreparedBattleReport:
        """在写事务外冻结战报负载，避免压缩过程占用 SQLite 写锁。"""

        compressed, uncompressed_bytes = encode_segment(draft.segment)
        return PreparedBattleReport(draft, compressed, uncompressed_bytes)

    def capture_in_uow(self, uow, draft: BattleReportDraft) -> BattleReportReference:
        """与玩法结算共用工作单元，战报失败时不会留下半份结算。"""

        return self.capture_prepared_in_uow(uow, self.prepare_capture(draft))

    def capture_prepared_in_uow(
        self,
        uow,
        prepared: PreparedBattleReport,
    ) -> BattleReportReference:
        """只写入已经编码的战报，供玩法最终短事务原子提交。"""

        if not isinstance(prepared, PreparedBattleReport):
            raise TypeError("prepared 必须是 PreparedBattleReport")
        draft = prepared.draft
        existing = self.store.header_in_uow(uow, draft.report_id)
        if existing is None:
            share_id = self._new_share_id(uow)
            started_at = draft.segment.started_at
            finished_at = draft.segment.finished_at
            self.store.insert_header_in_uow(
                uow,
                report_id=draft.report_id,
                share_id=share_id,
                mode_id=draft.mode_id,
                content_fingerprint=draft.content_fingerprint,
                summary_payload=_encode_summary(draft.summary),
                started_at=started_at.isoformat(),
                finished_at=finished_at.isoformat(),
                detail_expires_at=(finished_at + DETAIL_RETENTION).isoformat(),
                summary_expires_at=(finished_at + SUMMARY_RETENTION).isoformat(),
                created_at=finished_at.isoformat(),
            )
        else:
            self._validate_identity(existing, draft)
            share_id = existing.share_id

        if self.store.segment_exists_in_uow(
            uow,
            draft.report_id,
            draft.segment.segment_id,
        ):
            return BattleReportReference(draft.report_id, share_id)

        self.store.append_segment_in_uow(
            uow,
            report_id=draft.report_id,
            segment_id=draft.segment.segment_id,
            detail_payload=prepared.detail_payload,
            uncompressed_bytes=prepared.uncompressed_bytes,
            summary_payload=_encode_summary(draft.summary),
            started_at=draft.segment.started_at.isoformat(),
            finished_at=draft.segment.finished_at.isoformat(),
            detail_expires_at=(draft.segment.finished_at + DETAIL_RETENTION).isoformat(),
            summary_expires_at=(draft.segment.finished_at + SUMMARY_RETENTION).isoformat(),
        )
        return BattleReportReference(draft.report_id, share_id)

    def reference(self, report_id: str) -> BattleReportReference | None:
        with self.database.unit_of_work(write=False) as uow:
            return self.reference_in_uow(uow, report_id)

    def reference_in_uow(self, uow, report_id: str) -> BattleReportReference | None:
        row = self.store.header_in_uow(uow, str(report_id or "").strip())
        if row is None:
            return None
        return BattleReportReference(row.report_id, row.share_id)

    def load_public(
        self,
        share_id: str,
        *,
        logical_time: datetime,
    ) -> BattleReportView | None:
        _aware(logical_time)
        stored = self.store.load_public(
            str(share_id or "").strip(),
            logical_time=logical_time.isoformat(),
        )
        if stored is None:
            return None
        row = stored.header
        segments = tuple(decode_segment(value) for value in stored.segment_payloads)
        return BattleReportView(
            share_id=row.share_id,
            mode_id=row.mode_id,
            content_fingerprint=row.content_fingerprint,
            summary=_decode_summary(row.summary_payload),
            started_at=datetime.fromisoformat(row.started_at),
            finished_at=datetime.fromisoformat(row.finished_at),
            detail_available=stored.detail_available,
            segments=segments,
        )

    def cleanup(self, *, logical_time: datetime) -> tuple[int, int]:
        """删除超过短期保留期的明细与摘要。"""

        _aware(logical_time)
        return self.store.cleanup(logical_time=logical_time.isoformat())

    @staticmethod
    def _validate_identity(row, draft: BattleReportDraft) -> None:
        expected = (
            draft.mode_id,
            draft.content_fingerprint,
        )
        actual = (
            row.mode_id,
            row.content_fingerprint,
        )
        if actual != expected:
            raise ValueError("同一战报身份对应了不同模式或内容版本")

    def _new_share_id(self, uow) -> str:
        while True:
            value = token_urlsafe(18)
            if not self.store.share_id_exists_in_uow(uow, value):
                return value


def _encode_summary(summary: BattleReportSummary) -> str:
    return json.dumps(
        {
            "title": summary.title,
            "outcome": summary.outcome,
            "lines": summary.lines,
            "tone": summary.tone,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _decode_summary(payload: str) -> BattleReportSummary:
    value = json.loads(payload)
    return BattleReportSummary(
        str(value["title"]),
        str(value["outcome"]),
        tuple(str(item) for item in value.get("lines", ())),
        str(value["tone"]),
    )


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("战报逻辑时间必须包含时区")


__all__ = [
    "BattleReportService",
    "DETAIL_RETENTION",
    "PreparedBattleReport",
    "SUMMARY_RETENTION",
]
