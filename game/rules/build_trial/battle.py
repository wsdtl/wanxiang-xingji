"""把当前玩家构筑接入三个固定、无收益的试炼目标。"""

from __future__ import annotations

from dataclasses import replace

from game.content.catalog.character import CHARACTER_LEVEL_PROGRESSION_ID
from game.content.catalog.trial import BUILD_TRIAL_ENDURANCE_ID
from game.core.gameplay import (
    COMBAT_SPEED,
    HEALTH_CURRENT,
    BattleEngine,
    BattleParticipant,
    BattleRules,
    BattleSession,
    BattleStatus,
    EnemyInstance,
    GameplayExecutor,
    RuleContext,
    TagSet,
)

from .metrics import summarize_build_trial
from .models import BuildTrialBattleOutcome


class BuildTrialBattleSimulator:
    """使用公共战斗核心执行固定种子的构筑验证。"""

    def __init__(self, content, player_lineup) -> None:
        self.content = content
        self.player_lineup = player_lineup

    def simulate(
        self,
        mode,
        *,
        character,
        inventory,
        loadout,
        roster,
        battle_id: str,
        context: RuleContext,
    ) -> BuildTrialBattleOutcome:
        engine = BattleEngine(
            GameplayExecutor(
                self.content.ability_engine,
                self.content.trigger_engine,
            ),
            BattleRules(
                HEALTH_CURRENT,
                COMBAT_SPEED,
                maximum_rounds=mode.maximum_rounds,
                maximum_turns=mode.maximum_turns,
            ),
            self.content.battle_ability_targeting,
            self.content.target_selectors,
        )
        lineup = self.player_lineup.project(
            character,
            inventory,
            loadout,
            roster,
            context_tags=TagSet.of("scene.build_trial", str(mode.id)),
        )
        entities = dict(lineup.entities)
        entities[character.id] = self._fully_restored(entities[character.id])
        level = character.progressions[CHARACTER_LEVEL_PROGRESSION_ID].level
        enemy_instances = self.enemy_instances(mode, level)
        enemies = tuple(
            self.content.enemy_projector.project(instance)
            for instance in enemy_instances
        )
        entities.update({value.instance.id: value.entity for value in enemies})
        participants = tuple(
            BattleParticipant(entity_id, "team.player", index)
            for index, entity_id in enumerate(lineup.participant_ids)
        ) + tuple(
            BattleParticipant(value.instance.id, "team.trial", index)
            for index, value in enumerate(enemies)
        )
        started = BattleSession.start(
            engine,
            battle_id,
            participants=participants,
            entities=entities,
            context=context,
        )
        if started.failure or started.value is None:
            raise RuntimeError(
                started.failure.message if started.failure else "构筑试炼启动失败"
            )
        session = started.value
        rules = self.player_lineup.ai_rules(lineup)
        rules.update({value.instance.id: value.ai_rules for value in enemies})
        while session.state.status is BattleStatus.ACTIVE:
            actor_id = session.state.current_actor_id
            if actor_id is None:
                raise RuntimeError("构筑试炼缺少当前行动者")
            action = self.content.battle_ai_engine.decide(
                rules[actor_id],
                session.state,
                actor_id,
                context=context,
            )
            if action is None:
                raise RuntimeError(f"构筑试炼无法为 {actor_id} 选择行动")
            outcome = session.execute_turn(action, context=context)
            if outcome.failure or outcome.value is None:
                raise RuntimeError(
                    outcome.failure.message if outcome.failure else "构筑试炼执行失败"
                )

        state = session.state
        player_ids = lineup.participant_ids
        enemy_ids = tuple(value.instance.id for value in enemies)
        player_alive = any(value not in state.inactive_ids for value in player_ids)
        victory = "team.player" in state.winning_teams
        draw = state.status is BattleStatus.DRAW
        completed = (
            player_alive if mode.id == BUILD_TRIAL_ENDURANCE_ID else victory
        )
        trace = session.trace
        return BuildTrialBattleOutcome(
            completed=completed,
            victory=victory,
            draw=draw,
            turns=state.turn_number,
            trace=trace,
            metrics=summarize_build_trial(
                trace,
                character_id=character.id,
                player_entity_ids=player_ids,
                enemy_entity_ids=enemy_ids,
                attribute_resolver=self.content.enemy_projector.attributes,
            ),
            player_entity_ids=player_ids,
            enemy_entity_ids=enemy_ids,
            companion_id=(
                lineup.companion.companion_id
                if lineup.companion is not None
                else None
            ),
        )

    def enemy_instances(self, mode, level: int) -> tuple[EnemyInstance, ...]:
        return tuple(
            EnemyInstance(
                id=f"build-trial-target:{mode.id}:{index}",
                definition_id=mode.target_definition_id,
                level=level,
                rank_id="enemy.rank.build_trial",
                behavior_ids=(),
                generation_seed=f"{mode.random_seed}:{index}",
                content_version=self.content.report.content_fingerprint,
            )
            for index in range(1, mode.target_count + 1)
        )

    def _fully_restored(self, entity):
        snapshot = entity.snapshot(self.content.enemy_projector.attributes)
        resources = {}
        for resource_id, definition in self.content.resources.items():
            if definition.maximum_attribute is not None:
                resources[resource_id] = snapshot.value(definition.maximum_attribute)
            elif definition.fixed_maximum is not None:
                resources[resource_id] = definition.fixed_maximum
            else:
                resources[resource_id] = definition.minimum
        return replace(entity, resources=resources)


__all__ = ["BuildTrialBattleSimulator"]
