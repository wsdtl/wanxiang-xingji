"""三名玩家和三只伙伴共同挑战组队首领的战斗编排。"""

from __future__ import annotations

from dataclasses import dataclass

from game.content.catalog.social import (
    PARTY_BATTLE_MAXIMUM_ROUNDS,
    PARTY_BATTLE_MAXIMUM_TURNS,
)
from game.core.gameplay import (
    COMBAT_SPEED,
    HEALTH_CURRENT,
    HEALTH_MAXIMUM,
    SPIRIT_CURRENT,
    BattleEngine,
    BattleParticipant,
    BattleRules,
    BattleSession,
    BattleStatus,
    BattleTrace,
    GameplayExecutor,
    RuleContext,
    RuleEvent,
    TagSet,
)


@dataclass(frozen=True)
class PartyBattleOutcome:
    victory: bool
    draw: bool
    turns: int
    trace: BattleTrace
    enemy_instance: object
    player_resources: dict[str, tuple[float, float]]
    lineups: dict[str, object]


class PartyBattleSimulator:
    """只负责把阵容放进公共战斗核心，不负责奖励和持久化。"""

    def __init__(self, content, player_lineup) -> None:
        self.content = content
        self.player_lineup = player_lineup
        self.engine = BattleEngine(
            GameplayExecutor(content.ability_engine, content.trigger_engine),
            BattleRules(
                HEALTH_CURRENT,
                COMBAT_SPEED,
                maximum_rounds=PARTY_BATTLE_MAXIMUM_ROUNDS,
                maximum_turns=PARTY_BATTLE_MAXIMUM_TURNS,
            ),
            content.battle_ability_targeting,
            content.target_selectors,
        )

    def simulate(self, members, bundles, challenge, *, context: RuleContext) -> PartyBattleOutcome:
        lineups = {}
        entities = {}
        participants = []
        rules = {}
        for member, (inventory, loadout, roster) in zip(members, bundles):
            lineup = self.player_lineup.project(
                member,
                inventory,
                loadout,
                roster,
                context_tags=TagSet.of("scene.party_battle"),
            )
            lineups[member.id] = lineup
            entities.update(lineup.entities)
            rules.update(self.player_lineup.ai_rules(lineup))
            slot = challenge.member_slots[member.id]
            for offset, entity_id in enumerate(lineup.participant_ids):
                participants.append(
                    BattleParticipant(entity_id, "team.party", slot * 2 + offset)
                )

        enemy_instance = challenge.encounter.enemies[0]
        enemy = self.content.enemy_projector.project(enemy_instance)
        entities[enemy.instance.id] = enemy.entity
        rules[enemy.instance.id] = enemy.ai_rules
        participants.append(BattleParticipant(enemy.instance.id, "team.enemy", 0))
        started = BattleSession.start(
            self.engine,
            f"battle:{challenge.session_id}",
            participants=tuple(participants),
            entities=entities,
            context=context,
        )
        if started.failure or started.value is None:
            raise RuntimeError(started.failure.message if started.failure else "组队战斗启动失败")
        session = started.value
        active_phases = frozenset()
        while session.state.status is BattleStatus.ACTIVE:
            actor_id = session.state.current_actor_id
            if actor_id is None:
                raise RuntimeError("组队战斗缺少当前行动者")
            action = self.content.battle_ai_engine.decide(
                rules[actor_id],
                session.state,
                actor_id,
                context=context,
            )
            if action is None:
                raise RuntimeError(f"组队战斗无法为 {actor_id} 选择行动")
            outcome = session.execute_turn(action, context=context)
            if outcome.failure or outcome.value is None:
                raise RuntimeError(outcome.failure.message if outcome.failure else "组队战斗执行失败")
            state = session.state
            if state.status is BattleStatus.ACTIVE and enemy.instance.id not in state.inactive_ids:
                updates, phase_rules, active_phases, phase_events = self._phase_updates(
                    state,
                    enemy_instance,
                    enemy.instance.id,
                    active_phases,
                    context,
                )
                if updates or phase_events:
                    phase_outcome = session.apply_external(
                        updates,
                        phase_events,
                        subject_id="battle.party_boss.phase",
                        context=context,
                    )
                    if phase_outcome.failure:
                        raise RuntimeError(phase_outcome.failure.message)
                if phase_rules:
                    rules[enemy.instance.id] = (*rules[enemy.instance.id], *phase_rules)
        state = session.state
        player_resources = {
            member.id: (
                float(state.entities[member.id].resources[HEALTH_CURRENT]),
                float(state.entities[member.id].resources[SPIRIT_CURRENT]),
            )
            for member in members
        }
        return PartyBattleOutcome(
            "team.party" in state.winning_teams,
            state.status is BattleStatus.DRAW,
            state.turn_number,
            session.trace,
            enemy_instance,
            player_resources,
            lineups,
        )

    def _phase_updates(self, state, instance, enemy_id, active_phases, context):
        entity = state.entities[enemy_id]
        maximum = entity.snapshot(self.content.enemy_projector.attributes).value(HEALTH_MAXIMUM)
        ratio = entity.resources[HEALTH_CURRENT] / maximum if maximum > 0 else 0.0
        pending = self.content.enemy_projector.pending_phases(instance, ratio, active_phases)
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
        return {enemy_id: entity}, tuple(phase_rules), active_phases, tuple(phase_events)


__all__ = ["PartyBattleOutcome", "PartyBattleSimulator"]
