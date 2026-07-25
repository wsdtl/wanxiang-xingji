"""真实角色配装对抗单只次元灾厄的限时战斗。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.gameplay import (
    COMBAT_SPEED,
    ENEMY_RANK_BOSS_ID,
    HEALTH_CURRENT,
    HEALTH_MAXIMUM,
    SPIRIT_CURRENT,
    BattleEngine,
    BattleParticipant,
    BattleRules,
    BattleSession,
    BattleStatus,
    BattleTrace,
    EnemyInstance,
    GameplayExecutor,
    InventoryState,
    LoadoutState,
    RuleContext,
    RuleEvent,
    TagSet,
)
from game.rules.companion import CompanionRosterState, PlayerBattleLineupProjector
from game.rules.disaster import DisasterCombatSnapshot


@dataclass(frozen=True)
class DimensionalDisasterBattleOutcome:
    damage: int
    player_health_after: float
    player_spirit_after: float
    turns: int
    player_victory: bool
    draw: bool
    trace: BattleTrace
    player_companion_id: str | None = None


class DimensionalDisasterBattleSimulator:
    """只编排灾厄场景，所有伤害和特效仍由公共战斗核心执行。"""

    def __init__(
        self,
        content,
        player_lineup: PlayerBattleLineupProjector,
        *,
        maximum_rounds: int,
    ) -> None:
        self.content = content
        self.player_lineup = player_lineup
        self.engine = BattleEngine(
            GameplayExecutor(content.ability_engine, content.trigger_engine),
            BattleRules(
                HEALTH_CURRENT,
                COMBAT_SPEED,
                maximum_rounds=maximum_rounds,
                maximum_turns=max(100, maximum_rounds * 20),
            ),
            content.battle_ability_targeting,
            content.target_selectors,
        )

    def enemy_maximum_health(self, combat: DisasterCombatSnapshot, event_id: str) -> float:
        projection = self.content.enemy_projector.project(
            self._enemy(combat, event_id)
        )
        return projection.entity.snapshot(
            self.content.enemy_projector.attributes
        ).value(HEALTH_MAXIMUM)

    def simulate(
        self,
        combat: DisasterCombatSnapshot,
        event_id: str,
        *,
        character,
        inventory: InventoryState,
        loadout: LoadoutState,
        roster: CompanionRosterState,
        context: RuleContext,
    ) -> DimensionalDisasterBattleOutcome:
        lineup = self.player_lineup.project(
            character,
            inventory,
            loadout,
            roster,
            context_tags=TagSet.of("scene.dimensional_disaster"),
        )
        enemy_instance = self._enemy(combat, event_id)
        enemy = self.content.enemy_projector.project(enemy_instance)
        enemy_maximum = enemy.entity.snapshot(
            self.content.enemy_projector.attributes
        ).value(HEALTH_MAXIMUM)
        entities = lineup.entities
        entities[enemy.instance.id] = enemy.entity
        participants = tuple(
            BattleParticipant(entity_id, "team.player", index)
            for index, entity_id in enumerate(lineup.participant_ids)
        ) + (BattleParticipant(enemy.instance.id, "team.enemy", 0),)
        started = BattleSession.start(
            self.engine,
            f"battle:{event_id}:{context.trace_id}",
            participants=participants,
            entities=entities,
            context=context,
        )
        if started.failure or started.value is None:
            raise RuntimeError(
                started.failure.message if started.failure else "灾厄战斗启动失败"
            )
        session = started.value
        rules = self.player_lineup.ai_rules(lineup)
        rules[enemy.instance.id] = enemy.ai_rules
        active_phases = frozenset()
        while session.state.status is BattleStatus.ACTIVE:
            state = session.state
            actor_id = state.current_actor_id
            if actor_id is None:
                raise RuntimeError("灾厄战斗缺少当前行动者")
            action = self.content.battle_ai_engine.decide(
                rules[actor_id],
                state,
                actor_id,
                context=context,
            )
            if action is None:
                raise RuntimeError(f"灾厄战斗无法为 {actor_id} 选择行动")
            outcome = session.execute_turn(action, context=context)
            if outcome.failure or outcome.value is None:
                raise RuntimeError(
                    outcome.failure.message if outcome.failure else "灾厄战斗执行失败"
                )
            state = session.state
            if state.status is BattleStatus.ACTIVE and enemy.instance.id not in state.inactive_ids:
                entity_updates, phase_rules, active_phases, phase_events = self._phase_updates(
                    state,
                    enemy_instance,
                    enemy.instance.id,
                    active_phases,
                    context,
                )
                if entity_updates or phase_events:
                    phase_outcome = session.apply_external(
                        entity_updates,
                        phase_events,
                        subject_id="battle.transition.enemy_phase",
                        context=context,
                    )
                    if phase_outcome.failure:
                        raise RuntimeError(phase_outcome.failure.message)
                if phase_rules:
                    rules[enemy.instance.id] = (*rules[enemy.instance.id], *phase_rules)
        state = session.state
        enemy_after = state.entities[enemy.instance.id]
        player_after = state.entities[character.id]
        damage = max(
            0,
            round(enemy_maximum - float(enemy_after.resources[HEALTH_CURRENT])),
        )
        return DimensionalDisasterBattleOutcome(
            damage,
            float(player_after.resources[HEALTH_CURRENT]),
            float(player_after.resources[SPIRIT_CURRENT]),
            state.turn_number,
            "team.player" in state.winning_teams,
            state.status is BattleStatus.DRAW,
            session.trace,
            (
                lineup.companion.companion_id
                if lineup.companion is not None
                else None
            ),
        )

    def _phase_updates(self, state, instance, enemy_id, active_phases, context):
        entity = state.entities[enemy_id]
        maximum = entity.snapshot(self.content.enemy_projector.attributes).value(
            HEALTH_MAXIMUM
        )
        ratio = entity.resources[HEALTH_CURRENT] / maximum if maximum > 0 else 0.0
        pending = self.content.enemy_projector.pending_phases(
            instance,
            ratio,
            active_phases,
        )
        if not pending:
            return {}, (), active_phases, ()
        phase_rules = []
        phase_events = []
        for phase in pending:
            entity, added_rules = self.content.enemy_projector.apply_phase(
                entity,
                instance,
                phase,
            )
            phase_rules.extend(added_rules)
            active_phases = active_phases | {phase.id}
            phase_events.append(
                RuleEvent.from_context(
                    context,
                    kind="combat.phase.activated",
                    source_id=enemy_id,
                    target_id=enemy_id,
                    subject_id=phase.id,
                    values={
                        "health_ratio": ratio,
                        "threshold": phase.health_ratio,
                        "behavior_count": len(phase.behavior_ids),
                        "behavior_ids": tuple(phase.behavior_ids),
                    },
                )
            )
        return (
            {enemy_id: entity},
            tuple(phase_rules),
            active_phases,
            tuple(phase_events),
        )

    @staticmethod
    def _enemy(combat: DisasterCombatSnapshot, event_id: str) -> EnemyInstance:
        return EnemyInstance(
            f"enemy:{event_id}",
            combat.enemy_definition_id,
            combat.level,
            combat.rank_id or ENEMY_RANK_BOSS_ID,
            combat.behavior_ids,
            combat.generation_seed,
            combat.content_version,
            combat.phase_loadouts,
        )


__all__ = [
    "DimensionalDisasterBattleOutcome",
    "DimensionalDisasterBattleSimulator",
]
