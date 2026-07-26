"""探险持久化快照的业务类型白名单。"""

from game.core.gameplay import EnemyEncounterInstance, EnemyInstance, EnemyPhaseLoadout
from game.rules.exploration import (
    ExplorationBatchPlan,
    ExplorationBatchResult,
    ExplorationEncounterKind,
    ExplorationRewardKind,
    ExplorationRewardReference,
    ExplorationRestReason,
    ExplorationState,
    ExplorationStatus,
    ExplorationStopReason,
    ExplorationVictoryFact,
)


def exploration_codec_registrations() -> tuple[tuple[str, type[object]], ...]:
    """由应用组合根注入公共快照 codec，纯规则层不认识持久化登记。"""

    return (
        ("product.enemy_instance", EnemyInstance),
        ("product.enemy_phase_loadout", EnemyPhaseLoadout),
        ("product.enemy_encounter_instance", EnemyEncounterInstance),
        ("product.exploration_status", ExplorationStatus),
        ("product.exploration_stop_reason", ExplorationStopReason),
        ("product.exploration_encounter_kind", ExplorationEncounterKind),
        ("product.exploration_reward_kind", ExplorationRewardKind),
        ("product.exploration_reward_reference", ExplorationRewardReference),
        ("product.exploration_rest_reason", ExplorationRestReason),
        ("product.exploration_batch_plan", ExplorationBatchPlan),
        ("product.exploration_batch_result", ExplorationBatchResult),
        ("product.exploration_state", ExplorationState),
        ("game.exploration.victory_fact.v1", ExplorationVictoryFact),
    )


__all__ = ["exploration_codec_registrations"]
