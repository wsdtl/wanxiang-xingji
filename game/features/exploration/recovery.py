"""探险会话与正式休息行动之间的原子协调端口。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from game.content.catalog.exploration import EXPLORATION_BATCH_SECONDS

from game.rules.exploration import (
    EXPLORATION_AGGREGATE,
    ExplorationState,
    ExplorationStatus,
    resume_exploration,
)


class ExplorationRestCoordinator:
    """只协调暂停和续行；资源恢复始终由 RestFeature 结算。"""

    def __init__(self, database, snapshots, rest) -> None:
        if database.path != rest.database.path:
            raise ValueError("探险和休息服务必须使用同一个数据库")
        self.database = database
        self.snapshots = snapshots
        self.rest = rest

    def start_in_uow(self, uow, state: ExplorationState) -> ExplorationState:
        if state.status is not ExplorationStatus.RESTING:
            raise ValueError("只有休整中的探险可以启动正式休息")
        if state.rest_started_at is None or state.rest_completes_at is None:
            raise ValueError("探险休整缺少开始或完成时间")
        result = self.rest.start_exploration_in_uow(
            uow,
            self._operation_id("start", state),
            state.character_id,
            state.session_id,
            logical_time=state.rest_started_at,
        )
        if result.status not in {"started", "already_running"} or result.action is None:
            raise RuntimeError(result.failure_message or "探险自动休整没有开始")
        if result.action.completes_at == state.rest_completes_at:
            return state
        adjusted = replace(
            state,
            rest_completes_at=result.action.completes_at,
            next_batch_at=result.action.completes_at
            + timedelta(seconds=EXPLORATION_BATCH_SECONDS),
            revision=state.revision + 1,
        )
        self.snapshots.update(
            uow,
            EXPLORATION_AGGREGATE,
            state.character_id,
            state,
            adjusted,
            state.rest_started_at,
        )
        return adjusted

    def resume_due(
        self,
        character_id: str,
        *,
        logical_time: datetime,
    ) -> ExplorationState | None:
        with self.database.unit_of_work() as uow:
            state = self.snapshots.load(
                uow,
                EXPLORATION_AGGREGATE,
                character_id,
                ExplorationState,
            )
            if state is None or state.status is not ExplorationStatus.RESTING:
                return state
            action = self.rest.exploration_action_in_uow(
                uow,
                character_id,
                state.session_id,
            )
            if action is None:
                raise RuntimeError("休整中的探险缺少正式休息行动")
            if action.completes_at > logical_time:
                return state
            result = self.rest.stop_exploration_in_uow(
                uow,
                self._operation_id("complete", state),
                character_id,
                state.session_id,
                logical_time=action.completes_at,
            )
            if result.status != "completed":
                raise RuntimeError(result.failure_message or "探险休整没有完成")
            resumed = resume_exploration(
                state,
                logical_time=action.completes_at,
            )
            self.snapshots.update(
                uow,
                EXPLORATION_AGGREGATE,
                character_id,
                state,
                resumed,
                action.completes_at,
            )
            uow.commit()
            return resumed

    def stop_in_uow(
        self,
        uow,
        state: ExplorationState,
        *,
        logical_time: datetime,
    ) -> None:
        if state.status is not ExplorationStatus.RESTING:
            return
        action = self.rest.exploration_action_in_uow(
            uow,
            state.character_id,
            state.session_id,
        )
        if action is None:
            raise RuntimeError("休整中的探险缺少正式休息行动")
        result = self.rest.stop_exploration_in_uow(
            uow,
            self._operation_id("stop", state),
            state.character_id,
            state.session_id,
            logical_time=logical_time,
        )
        if result.status not in {"stopped", "completed"}:
            raise RuntimeError(result.failure_message or "探险休整没有停止")

    @staticmethod
    def _operation_id(kind: str, state: ExplorationState) -> str:
        return f"exploration-rest:{kind}:{state.session_id}:{state.rest_count}"


__all__ = ["ExplorationRestCoordinator"]
