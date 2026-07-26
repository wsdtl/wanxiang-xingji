"""持续探险会话的纯状态转换。"""

from dataclasses import replace
from datetime import datetime, timedelta

from game.content.catalog.exploration import EXPLORATION_BATCH_SECONDS

from .models import (
    ExplorationBatchResult,
    ExplorationRestReason,
    ExplorationState,
    ExplorationStatus,
    ExplorationStopReason,
)


def start_exploration(
    character_id: str,
    session_id: str,
    region_id: str,
    location_id: str,
    *,
    logical_time: datetime,
) -> ExplorationState:
    return ExplorationState(
        character_id,
        session_id,
        region_id,
        location_id,
        ExplorationStatus.RUNNING,
        logical_time,
        logical_time + timedelta(seconds=EXPLORATION_BATCH_SECONDS),
    )


def record_batch(
    state: ExplorationState,
    result: ExplorationBatchResult,
    *,
    stop_reason: ExplorationStopReason | None = None,
    rest_reason: ExplorationRestReason | None = None,
    rest_completes_at: datetime | None = None,
) -> ExplorationState:
    if state.status is not ExplorationStatus.RUNNING:
        raise ValueError("只有运行中的探险可以记录批次")
    if result.plan.session_id != state.session_id:
        raise ValueError("探险批次不属于当前会话")
    if result.plan.batch_index != state.batch_index + 1:
        raise ValueError("探险批次序号不连续")
    if stop_reason is not None and rest_reason is not None:
        raise ValueError("探险批次不能同时停止并进入休整")
    if (rest_reason is None) != (rest_completes_at is None):
        raise ValueError("探险批次休整原因和完成时间必须同时提供")
    stopped = stop_reason is not None
    resting = rest_reason is not None
    next_batch_at = state.next_batch_at + timedelta(seconds=EXPLORATION_BATCH_SECONDS)
    if resting:
        assert rest_completes_at is not None
        next_batch_at = rest_completes_at + timedelta(seconds=EXPLORATION_BATCH_SECONDS)
    return replace(
        state,
        status=(
            ExplorationStatus.STOPPED
            if stopped
            else ExplorationStatus.RESTING
            if resting
            else ExplorationStatus.RUNNING
        ),
        next_batch_at=next_batch_at,
        batch_index=result.plan.batch_index,
        completed_batches=state.completed_batches + 1,
        victories=state.victories + int(result.victory),
        defeats=state.defeats + int(not result.victory and not result.draw and result.plan.encounter is not None),
        character_experience=state.character_experience + result.character_experience,
        weapon_experience=state.weapon_experience + result.weapon_experience,
        companion_experience=state.companion_experience + result.companion_experience,
        weapon_drops=state.weapon_drops + result.weapon_drops,
        equipment_drops=state.equipment_drops + result.equipment_drops,
        trophy_drops=state.trophy_drops + result.trophy_drops,
        medicine_drops=state.medicine_drops + result.medicine_drops,
        draw_ticket_drops=state.draw_ticket_drops + result.draw_ticket_drops,
        trophy_value=state.trophy_value + result.trophy_value,
        rest_count=state.rest_count + int(resting),
        rest_reason=rest_reason,
        rest_started_at=result.resolved_at if resting else None,
        rest_completes_at=rest_completes_at,
        stopped_at=result.resolved_at if stopped else None,
        stop_reason=stop_reason,
        last_result=result,
        revision=state.revision + 1,
    )


def resume_exploration(
    state: ExplorationState,
    *,
    logical_time: datetime,
) -> ExplorationState:
    if state.status is not ExplorationStatus.RESTING:
        raise ValueError("只有休整中的探险可以续行")
    if state.rest_started_at is None or state.rest_completes_at is None:
        raise ValueError("探险休整状态缺少时间")
    if logical_time < state.rest_completes_at:
        raise ValueError("探险休整尚未完成")
    elapsed = (state.rest_completes_at - state.rest_started_at).total_seconds()
    return replace(
        state,
        status=ExplorationStatus.RUNNING,
        next_batch_at=logical_time + timedelta(seconds=EXPLORATION_BATCH_SECONDS),
        rest_seconds=state.rest_seconds + elapsed,
        rest_reason=None,
        rest_started_at=None,
        rest_completes_at=None,
        revision=state.revision + 1,
    )


def stop_exploration(
    state: ExplorationState,
    reason: ExplorationStopReason,
    *,
    logical_time: datetime,
) -> ExplorationState:
    if state.status is ExplorationStatus.STOPPED:
        return state
    rest_seconds = state.rest_seconds
    if state.status is ExplorationStatus.RESTING:
        assert state.rest_started_at is not None
        assert state.rest_completes_at is not None
        effective = min(max(logical_time, state.rest_started_at), state.rest_completes_at)
        rest_seconds += (effective - state.rest_started_at).total_seconds()
    return replace(
        state,
        status=ExplorationStatus.STOPPED,
        rest_seconds=rest_seconds,
        rest_reason=None,
        rest_started_at=None,
        rest_completes_at=None,
        stopped_at=logical_time,
        stop_reason=reason,
        revision=state.revision + 1,
    )


__all__ = [
    "record_batch",
    "resume_exploration",
    "start_exploration",
    "stop_exploration",
]
