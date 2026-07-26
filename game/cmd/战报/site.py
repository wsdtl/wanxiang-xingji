"""公开战报页面与版本化 JSON 协议入口。"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from game.app import current_game_services
from game.content.presentation import GAME_NAME
from game.features.battle_report import (
    PUBLIC_BATTLE_REPORT_SCHEMA,
    PUBLIC_BATTLE_REPORT_VERSION,
    PublicBattleReportProjector,
    build_public_battle_events,
    build_public_battle_participants,
    build_public_battle_raw,
    build_public_battle_report,
    build_public_battle_transition,
    validate_public_battle_report,
)
from launch import config
from launch.paths import static_path


router = APIRouter()
_REPORT_PAGE = static_path("battle-report", "index.html")
_PUBLIC_HEADERS = {
    "Cache-Control": "public, max-age=60",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


@router.get("/battle/{share_id}", response_class=FileResponse)
def public_battle_report(share_id: str) -> FileResponse:
    """保留公开分享地址；浏览器从同路径的 data 端点读取战报。"""

    services = current_game_services()
    if not services.battle_reports.public_exists(
        share_id,
        logical_time=_logical_time(),
    ):
        raise HTTPException(status_code=404, detail="战报不存在或已经过期")
    return FileResponse(
        _REPORT_PAGE,
        media_type="text/html",
        headers=_PUBLIC_HEADERS,
    )


@router.get("/battle/{share_id}/data", response_class=JSONResponse)
def public_battle_report_data(share_id: str) -> JSONResponse:
    """返回摘要和首个片段的紧凑内容。"""

    selection = _load_public_selection(share_id, 0)
    document = build_public_battle_report(
        selection.report,
        segment_index=selection.segment_index,
        segment_count=selection.segment_count,
    )
    document["game_name"] = GAME_NAME
    validate_public_battle_report(document)
    return JSONResponse(document, headers=_PUBLIC_HEADERS)


@router.get("/battle/{share_id}/segments/{segment_index}", response_class=JSONResponse)
def public_battle_report_segment(share_id: str, segment_index: int) -> JSONResponse:
    """按公开序号返回一个完整紧凑片段，不暴露持久化片段身份。"""

    selection = _load_public_selection(share_id, segment_index)
    segment = _selected_segment(selection)
    document = {
        "schema": PUBLIC_BATTLE_REPORT_SCHEMA,
        "version": PUBLIC_BATTLE_REPORT_VERSION,
        "segment": PublicBattleReportProjector(segment).compact_segment(
            segment_index=segment_index,
            segment_count=selection.segment_count,
        ),
    }
    validate_public_battle_report(document)
    return JSONResponse(document, headers=_PUBLIC_HEADERS)


@router.get(
    "/battle/{share_id}/segments/{segment_index}/events",
    response_class=JSONResponse,
)
def public_battle_report_events(share_id: str, segment_index: int) -> JSONResponse:
    """用户切换到全部事件时，一次返回当前片段的完整事件。"""

    selection = _load_public_selection(share_id, segment_index)
    document = build_public_battle_events(
        _selected_segment(selection),
        segment_index=segment_index,
    )
    return JSONResponse(document, headers=_PUBLIC_HEADERS)


@router.get(
    "/battle/{share_id}/segments/{segment_index}/participants/{snapshot}",
    response_class=JSONResponse,
)
def public_battle_report_participants(
    share_id: str,
    segment_index: int,
    snapshot: str,
) -> JSONResponse:
    """参与者面板展开后再返回完整状态。"""

    selection = _load_public_selection(share_id, segment_index)
    try:
        document = build_public_battle_participants(
            _selected_segment(selection),
            segment_index=segment_index,
            snapshot=snapshot,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="战报快照不存在") from exc
    return JSONResponse(document, headers=_PUBLIC_HEADERS)


@router.get(
    "/battle/{share_id}/segments/{segment_index}/transitions/{sequence}",
    response_class=JSONResponse,
)
def public_battle_report_transition(
    share_id: str,
    segment_index: int,
    sequence: int,
) -> JSONResponse:
    """行动对比展开后再返回这一次转场的前后状态。"""

    selection = _load_public_selection(share_id, segment_index)
    try:
        document = build_public_battle_transition(
            _selected_segment(selection),
            segment_index=segment_index,
            sequence=sequence,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="战报行动不存在") from exc
    return JSONResponse(document, headers=_PUBLIC_HEADERS)


@router.get(
    "/battle/{share_id}/segments/{segment_index}/raw",
    response_class=JSONResponse,
)
def public_battle_report_raw(share_id: str, segment_index: int) -> JSONResponse:
    """明确展开原始数据后才生成经过白名单清洗的片段事实。"""

    selection = _load_public_selection(share_id, segment_index)
    document = build_public_battle_raw(
        _selected_segment(selection),
        segment_index=segment_index,
    )
    return JSONResponse(document, headers=_PUBLIC_HEADERS)


def _load_public_selection(share_id: str, segment_index: int):
    if segment_index < 0:
        raise HTTPException(status_code=404, detail="战报片段不存在")
    services = current_game_services()
    selection = services.battle_reports.load_public_selection(
        share_id,
        logical_time=_logical_time(),
        segment_index=segment_index,
    )
    if selection is None:
        raise HTTPException(status_code=404, detail="战报不存在或已经过期")
    return selection


def _selected_segment(selection):
    if not selection.report.detail_available or not selection.report.segments:
        raise HTTPException(status_code=404, detail="战报完整行动已经归档")
    return selection.report.segments[0]


def _logical_time() -> datetime:
    return datetime.now(ZoneInfo(config.project.timezone))


__all__ = [
    "public_battle_report",
    "public_battle_report_data",
    "public_battle_report_events",
    "public_battle_report_participants",
    "public_battle_report_raw",
    "public_battle_report_segment",
    "public_battle_report_transition",
    "router",
]
