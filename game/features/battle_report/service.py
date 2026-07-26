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
    report_id_matches_content_scope,
)

from .assembly import BattleReportBuilder


DETAIL_RETENTION = timedelta(hours=3)
SUMMARY_RETENTION = timedelta(hours=12)


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


@dataclass(frozen=True)
class PublicBattleReportSelection:
    """公开读取的一份报告头和至多一个按序号选择的片段。"""

    report: BattleReportView
    segment_index: int
    segment_count: int

    def __post_init__(self) -> None:
        if self.segment_index < 0 or self.segment_count < 0:
            raise ValueError("公开战报片段序号或总数无效")


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

        segment_exists = self.store.segment_exists_in_uow(
            uow,
            draft.report_id,
            draft.segment.segment_id,
        )
        if segment_exists:
            return BattleReportReference(draft.report_id, share_id)
        if existing is not None and not report_id_matches_content_scope(
            draft.report_id,
            draft.content_fingerprint,
        ):
            raise ValueError("可追加战报身份必须包含当前内容指纹")

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
        stored = self._load_public_row(
            str(share_id or "").strip(),
            logical_time=logical_time,
        )
        if stored is None:
            return None
        return _view(stored)

    def load_public_selection(
        self,
        share_id: str,
        *,
        logical_time: datetime,
        segment_index: int = 0,
    ) -> PublicBattleReportSelection | None:
        """只解码指定片段；首屏和切换片段都走这一读取边界。"""

        _aware(logical_time)
        if segment_index < 0:
            raise ValueError("segment_index 不能小于 0")
        stored = self._load_public_row(
            str(share_id or "").strip(),
            logical_time=logical_time,
            segment_offset=segment_index,
            segment_limit=1,
        )
        if stored is None:
            return None
        if stored.detail_available and segment_index >= stored.segment_count:
            return None
        return PublicBattleReportSelection(
            _view(stored),
            segment_index,
            stored.segment_count,
        )

    def public_exists(self, share_id: str, *, logical_time: datetime) -> bool:
        """供 HTML 分享入口做轻量存在性检查。"""

        _aware(logical_time)
        return self.store.public_exists(
            str(share_id or "").strip(),
            logical_time=logical_time.isoformat(),
            summary_finished_after=(logical_time - SUMMARY_RETENTION).isoformat(),
        )

    def _load_public_row(
        self,
        share_id: str,
        *,
        logical_time: datetime,
        segment_offset: int | None = None,
        segment_limit: int | None = None,
    ):
        return self.store.load_public(
            share_id,
            logical_time=logical_time.isoformat(),
            detail_finished_after=(logical_time - DETAIL_RETENTION).isoformat(),
            summary_finished_after=(logical_time - SUMMARY_RETENTION).isoformat(),
            segment_offset=segment_offset,
            segment_limit=segment_limit,
        )

    def cleanup(self, *, logical_time: datetime) -> tuple[int, int]:
        """删除超过短期保留期的明细与摘要。"""

        _aware(logical_time)
        return self.store.cleanup(
            logical_time=logical_time.isoformat(),
            detail_finished_cutoff=(logical_time - DETAIL_RETENTION).isoformat(),
            summary_finished_cutoff=(logical_time - SUMMARY_RETENTION).isoformat(),
        )

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


def _view(stored) -> BattleReportView:
    row = stored.header
    return BattleReportView(
        share_id=row.share_id,
        mode_id=row.mode_id,
        content_fingerprint=row.content_fingerprint,
        summary=_decode_summary(row.summary_payload),
        started_at=datetime.fromisoformat(row.started_at),
        finished_at=datetime.fromisoformat(row.finished_at),
        detail_available=stored.detail_available,
        segments=tuple(decode_segment(value) for value in stored.segment_payloads),
    )


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("战报逻辑时间必须包含时区")


__all__ = [
    "BattleReportService",
    "DETAIL_RETENTION",
    "PreparedBattleReport",
    "PublicBattleReportSelection",
    "SUMMARY_RETENTION",
]
