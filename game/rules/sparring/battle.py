"""把两个真实角色的当前配装按满资源状态接入公共自动战斗核心。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.gameplay import (
    COMBAT_SPEED,
    HEALTH_CURRENT,
    SPIRIT_CURRENT,
    BattleEngine,
    BattleParticipant,
    BattleRules,
    BattleSession,
    BattleStatus,
    BattleTrace,
    GameplayExecutor,
    InventoryState,
    LoadoutState,
    RuleContext,
    TagSet,
)
from game.core.gameplay.character import CharacterState
from game.rules.combat import fully_restored_entity
from game.rules.companion import CompanionRosterState, PlayerBattleLineupProjector


@dataclass(frozen=True)
class SparringBattleOutcome:
    challenger_victory: bool
    draw: bool
    challenger_health_after: float
    challenger_spirit_after: float
    defender_health_after: float
    defender_spirit_after: float
    turns: int
    trace: BattleTrace
    challenger_companion_id: str | None = None
    defender_companion_id: str | None = None


class SparringBattleSimulator:
    """切磋以满资源投影双方当前配装，不修改任何持久状态。"""

    def __init__(self, content, player_lineup: PlayerBattleLineupProjector) -> None:
        self.content = content
        self.player_lineup = player_lineup
        self.engine = BattleEngine(
            GameplayExecutor(content.ability_engine, content.trigger_engine),
            BattleRules(
                HEALTH_CURRENT,
                COMBAT_SPEED,
                maximum_rounds=100,
                maximum_turns=1000,
            ),
            content.battle_ability_targeting,
            content.target_selectors,
        )

    def simulate(
        self,
        challenger: CharacterState,
        challenger_inventory: InventoryState,
        challenger_loadout: LoadoutState,
        challenger_roster: CompanionRosterState,
        defender: CharacterState,
        defender_inventory: InventoryState,
        defender_loadout: LoadoutState,
        defender_roster: CompanionRosterState,
        *,
        battle_id: str,
        context: RuleContext,
    ) -> SparringBattleOutcome:
        challenger_lineup = self.player_lineup.project(
            challenger,
            challenger_inventory,
            challenger_loadout,
            challenger_roster,
            context_tags=TagSet.of("scene.sparring", "side.challenger"),
        )
        defender_lineup = self.player_lineup.project(
            defender,
            defender_inventory,
            defender_loadout,
            defender_roster,
            context_tags=TagSet.of("scene.sparring", "side.defender"),
        )
        entities = {**challenger_lineup.entities, **defender_lineup.entities}
        for character_id in (challenger.id, defender.id):
            entities[character_id] = fully_restored_entity(
                entities[character_id],
                self.content.resources,
                self.content.enemy_projector.attributes,
            )
        participants = tuple(
            BattleParticipant(entity_id, "team.challenger", index)
            for index, entity_id in enumerate(challenger_lineup.participant_ids)
        ) + tuple(
            BattleParticipant(entity_id, "team.defender", index)
            for index, entity_id in enumerate(defender_lineup.participant_ids)
        )
        started = BattleSession.start(
            self.engine,
            battle_id,
            participants=participants,
            entities=entities,
            context=context,
        )
        if started.failure or started.value is None:
            raise RuntimeError(started.failure.message if started.failure else "切磋战斗启动失败")
        session = started.value
        rules = self.player_lineup.ai_rules(challenger_lineup)
        rules.update(self.player_lineup.ai_rules(defender_lineup))
        while session.state.status is BattleStatus.ACTIVE:
            actor_id = session.state.current_actor_id
            if actor_id is None:
                raise RuntimeError("切磋战斗缺少当前行动者")
            action = self.content.battle_ai_engine.decide(
                rules[actor_id],
                session.state,
                actor_id,
                context=context,
            )
            if action is None:
                raise RuntimeError(f"切磋自动战斗无法为 {actor_id} 选择行动")
            outcome = session.execute_turn(action, context=context)
            if outcome.failure or outcome.value is None:
                raise RuntimeError(
                    outcome.failure.message if outcome.failure else "切磋战斗执行失败"
                )
        state = session.state
        challenger_after = state.entities[challenger.id]
        defender_after = state.entities[defender.id]
        return SparringBattleOutcome(
            challenger_victory="team.challenger" in state.winning_teams,
            draw=state.status is BattleStatus.DRAW,
            challenger_health_after=float(challenger_after.resources[HEALTH_CURRENT]),
            challenger_spirit_after=float(challenger_after.resources[SPIRIT_CURRENT]),
            defender_health_after=float(defender_after.resources[HEALTH_CURRENT]),
            defender_spirit_after=float(defender_after.resources[SPIRIT_CURRENT]),
            turns=state.turn_number,
            trace=session.trace,
            challenger_companion_id=(
                challenger_lineup.companion.companion_id
                if challenger_lineup.companion is not None
                else None
            ),
            defender_companion_id=(
                defender_lineup.companion.companion_id
                if defender_lineup.companion is not None
                else None
            ),
        )


__all__ = ["SparringBattleOutcome", "SparringBattleSimulator"]
