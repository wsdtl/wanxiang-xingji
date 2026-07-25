"""正式敌人名录、遭遇生成、共享特效、AI 与展示回归测试。"""

from datetime import datetime, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.content import build_official_content  # noqa: E402
from game.content.catalog import (  # noqa: E402
    PARTY_BOSS_ENCOUNTER_ID,
    PERSONAL_BOSS_ENCOUNTER_ID,
    PERSONAL_ELITE_ENCOUNTER_ID,
    PERSONAL_NORMAL_ENCOUNTER_ID,
)
from game.content.catalog.enemy import (  # noqa: E402
    BEHAVIOR_BLUEPRINTS,
    BOSS_BLUEPRINTS,
    PARTY_BOSS_ENEMIES,
    PERSONAL_BOSS_ENEMIES,
    REGULAR_ENEMIES,
)
from game.content.catalog.weapon.blueprints import WEAPON_BLUEPRINTS  # noqa: E402
from game.content.catalog.weapon.registry import OFFICIAL_WEAPON_MECHANICS  # noqa: E402
from game.content.catalog.disaster.combat import DISASTER_ENEMY_DEFINITIONS  # noqa: E402
from game.content.catalog.trial import (  # noqa: E402
    BUILD_TRIAL_TARGETS,
)
from game.core.gameplay import (  # noqa: E402
    BATTLE_AI_FOUNDATION_VERSION,
    COMBAT_SPEED,
    HEALTH_CURRENT,
    BattleEngine,
    BattleParticipant,
    BattleRules,
    EnemyInstance,
    ENEMY_FOUNDATION_VERSION,
    GameplayExecutor,
    AbilityUse,
    RuleEntity,
    RuleContext,
    Ruleset,
    SeededRandomSource,
)
from game.rules import EnemyDefeatRewardPlanner, EnemyEncounterGenerator  # noqa: E402
from game.rules.battle_report import KNOWN_BATTLE_EVENT_KINDS  # noqa: E402


def main() -> None:
    assert BATTLE_AI_FOUNDATION_VERSION == "combat-ai.foundation.v2"
    assert ENEMY_FOUNDATION_VERSION == "enemy.foundation.v3"
    cultivation = build_official_content()
    magic = build_official_content("skin.magic")
    catalog = cultivation.catalog

    assert BEHAVIOR_BLUEPRINTS
    assert BOSS_BLUEPRINTS
    assert all(
        not hasattr(value, "source_weapon_key")
        and value.mechanic_recipe_id.startswith("combat.recipe.")
        for value in BEHAVIOR_BLUEPRINTS
    )
    recipe_ids = {
        OFFICIAL_WEAPON_MECHANICS.recipe_id(value.key)
        for value in WEAPON_BLUEPRINTS
    }
    assert {
        value.mechanic_recipe_id for value in BEHAVIOR_BLUEPRINTS
    } <= recipe_ids
    assert REGULAR_ENEMIES
    assert PERSONAL_BOSS_ENEMIES
    assert PARTY_BOSS_ENEMIES
    assert DISASTER_ENEMY_DEFINITIONS
    assert BUILD_TRIAL_TARGETS
    personal_ids = {value.id for value in PERSONAL_BOSS_ENEMIES}
    party_ids = {value.id for value in PARTY_BOSS_ENEMIES}
    disaster_ids = {value.id for value in DISASTER_ENEMY_DEFINITIONS}
    trial_ids = {value.id for value in BUILD_TRIAL_TARGETS}
    gameplay_ids = {
        *(value.id for value in REGULAR_ENEMIES),
        *personal_ids,
        *party_ids,
        *disaster_ids,
    }
    assert gameplay_ids <= set(catalog.enemies.definitions.ids())
    assert {
        f"enemy.behavior.{value.key}" for value in BEHAVIOR_BLUEPRINTS
    } <= set(catalog.enemies.behaviors.ids())
    assert {
        PERSONAL_NORMAL_ENCOUNTER_ID,
        PERSONAL_ELITE_ENCOUNTER_ID,
        PERSONAL_BOSS_ENCOUNTER_ID,
        PARTY_BOSS_ENCOUNTER_ID,
    } <= set(catalog.enemies.encounters.ids())
    assert not gameplay_ids & trial_ids
    assert not any(
        trial_ids & set(spawn.enemy_ids)
        for encounter in catalog.enemies.encounters
        for spawn in encounter.spawns
    )
    assert not personal_ids & party_ids
    assert not personal_ids & disaster_ids
    assert not party_ids & disaster_ids
    assert all(
        not hasattr(value, field_name)
        for value in catalog.enemies.definitions
        for field_name in ("default_behavior_ids", "available_behavior_ids", "phases")
    )

    shared_enemy = catalog.abilities.require("ability.enemy.heavy_strike")
    shared_weapon = catalog.abilities.require("ability.weapon.mountain_cleaver")
    assert shared_enemy.effects == shared_weapon.effects
    assert shared_enemy.costs == shared_weapon.costs
    assert shared_enemy.cooldown_turns == shared_weapon.cooldown_turns

    generator = EnemyEncounterGenerator(
        catalog.enemies,
        content_version=catalog.report.content_fingerprint,
    )
    first = generator.generate(
        PERSONAL_ELITE_ENCOUNTER_ID,
        level=36,
        generation_seed="elite-demo",
        random=SeededRandomSource("elite-demo"),
        behavior_weights=cultivation.enemy_behavior_profiles.require(
            cultivation.world.id
        ).behavior_weights,
    )
    repeated = generator.generate(
        PERSONAL_ELITE_ENCOUNTER_ID,
        level=36,
        generation_seed="elite-demo",
        random=SeededRandomSource("elite-demo"),
        behavior_weights=cultivation.enemy_behavior_profiles.require(
            cultivation.world.id
        ).behavior_weights,
    )
    assert first == repeated
    assert len(first.enemies) == 1
    elite = first.enemies[0]
    assert len(elite.behavior_ids) == 2

    same_identity_builds = set()
    for index in range(24):
        generated = generator.generate(
            PERSONAL_ELITE_ENCOUNTER_ID,
            level=36,
            generation_seed=f"elite-variety:{index}",
            random=SeededRandomSource(f"elite-variety:{index}"),
            allowed_enemy_ids=frozenset({elite.definition_id}),
            behavior_weights=cultivation.enemy_behavior_profiles.require(
                cultivation.world.id
            ).behavior_weights,
        ).enemies[0]
        same_identity_builds.add(generated.behavior_ids)
        _assert_compatible_loadout(catalog, generated)
    assert len(same_identity_builds) > 1

    cultivation_name = cultivation.enemy_projector.enemy(elite).name
    magic_name = magic.enemy_projector.enemy(elite).name
    assert "·" in cultivation_name and "·" in magic_name
    assert cultivation_name == cultivation.enemy_projector.enemy(elite).name
    assert cultivation_name != magic_name

    boss_encounter = generator.generate(
        PERSONAL_BOSS_ENCOUNTER_ID,
        level=50,
        generation_seed="boss-demo",
        random=SeededRandomSource("boss-demo"),
        allowed_enemy_ids=frozenset({"enemy.boss.nine_headed_plague"}),
        behavior_weights=cultivation.enemy_behavior_profiles.require(
            cultivation.world.id
        ).behavior_weights,
    )
    boss = boss_encounter.enemies[0]
    assert len(boss.behavior_ids) == 3
    assert len(boss.phase_loadouts) == 2
    assert len(
        {
            *boss.behavior_ids,
            *(behavior_id for phase in boss.phase_loadouts for behavior_id in phase.behavior_ids),
        }
    ) == 5
    assert cultivation.enemy_projector.enemy(boss).name == "化蛇·洪涛妖君"
    assert magic.enemy_projector.enemy(boss).name == "九头蛇·沼泽暴君"
    _assert_compatible_loadout(catalog, boss)

    known_behaviors = set(catalog.enemies.behaviors.ids())
    for world_id in cultivation.worlds.world_ids():
        weights = cultivation.enemy_behavior_profiles.require(world_id).behavior_weights
        assert set(weights) == known_behaviors
        assert all(weight > 0 for weight in weights.values())
        assert max(weights.values()) > min(weights.values())

    reward = EnemyDefeatRewardPlanner(catalog.enemy_threat).quote(first.enemies)
    assert reward.character_experience > 0
    assert reward.weapon_experience > 0
    assert reward.threat_score > 0
    assert reward.loot and reward.loot[0].table_id == "loot.enemy.elite"

    trial_reward = catalog.enemies.reward_profiles.require("enemy.reward.build_trial")
    assert trial_reward.character_experience_per_level == 0
    assert trial_reward.weapon_experience_per_level == 0
    assert trial_reward.base_loot_rolls == 0
    assert trial_reward.loot_table_id is None

    _assert_ai_executes(cultivation)
    _assert_all_behavior_abilities_execute(cultivation)
    print("official enemy catalog test passed")


def _assert_ai_executes(content) -> None:
    catalog = content.catalog
    fingerprint = catalog.report.content_fingerprint
    attacker = EnemyInstance(
        "enemy-attacker",
        "enemy.mountain_ape",
        20,
        "enemy.rank.normal",
        ("enemy.behavior.heavy_strike",),
        "ai-attacker",
        fingerprint,
    )
    target = EnemyInstance(
        "enemy-target",
        "enemy.stone_guardian",
        20,
        "enemy.rank.normal",
        ("enemy.behavior.block",),
        "ai-target",
        fingerprint,
    )
    attacker_projection = catalog.enemy_projector.project(attacker)
    target_projection = catalog.enemy_projector.project(target)
    context = RuleContext(
        "enemy-ai-test",
        "rule.enemy.test.v1",
        Ruleset("ruleset.enemy.test"),
        datetime.now(timezone.utc),
        SeededRandomSource("enemy-ai-test"),
    )
    engine = BattleEngine(
        GameplayExecutor(catalog.ability_engine, catalog.trigger_engine),
        BattleRules(HEALTH_CURRENT, COMBAT_SPEED),
        catalog.battle_ability_targeting,
        catalog.target_selectors,
    )
    started = engine.start(
        "battle-enemy-ai",
        participants=(
            BattleParticipant(attacker.id, "team.attackers", 0),
            BattleParticipant(target.id, "team.targets", 0),
        ),
        entities={
            attacker.id: attacker_projection.entity,
            target.id: target_projection.entity,
        },
        context=context,
    )
    assert started.ok
    state = started.value.state
    rules_by_id = {
        attacker.id: attacker_projection.ai_rules,
        target.id: target_projection.ai_rules,
    }
    actor_id = state.current_actor_id
    assert actor_id is not None
    action = catalog.battle_ai_engine.decide(
        rules_by_id[actor_id],
        state,
        actor_id,
        context=context,
    )
    assert action is not None
    assert action.ability_id.startswith("ability.enemy.")
    result = engine.execute_turn(state, action, context=context)
    assert result.ok
    assert any(event.kind == "combat.turn.ended" for event in result.value.events)


def _assert_all_behavior_abilities_execute(content) -> None:
    catalog = content.catalog
    executor = GameplayExecutor(catalog.ability_engine, catalog.trigger_engine)
    covered = set()
    for index, behavior in enumerate(catalog.enemies.behaviors):
        assert len(behavior.contribution.abilities) == 1
        ability_id = next(iter(behavior.contribution.abilities))
        actor = _effect_combatant("actor", ability_id)
        target = _effect_combatant("target")
        outcome = executor.execute_ability(
            AbilityUse(f"enemy-behavior:{index}", ability_id),
            actor=actor,
            target=target,
            context=RuleContext(
                f"enemy-behavior:{index}",
                "rule.enemy.behavior_test.v1",
                Ruleset("ruleset.enemy.behavior_test"),
                datetime.now(timezone.utc),
                SeededRandomSource(index),
            ),
        )
        assert outcome.failure is None, (behavior.id, outcome.failure)
        assert outcome.value is not None
        unknown = {
            str(event.kind) for event in outcome.value.events
        } - KNOWN_BATTLE_EVENT_KINDS
        assert not unknown, (behavior.id, unknown)
        covered.add(behavior.id)
    assert covered == set(catalog.enemies.behaviors.ids())
    assert all(
        set(profile.behavior_weights) == covered
        for profile in (
            content.enemy_behavior_profiles.require(world_id)
            for world_id in content.worlds.world_ids()
        )
    )


def _assert_compatible_loadout(catalog, enemy: EnemyInstance) -> None:
    behavior_ids = [
        *enemy.behavior_ids,
        *(
            behavior_id
            for phase in enemy.phase_loadouts
            for behavior_id in phase.behavior_ids
        ),
    ]
    assert len(behavior_ids) == len(set(behavior_ids))
    for behavior_id in behavior_ids:
        behavior = catalog.enemies.behaviors.require(behavior_id)
        assert not behavior.incompatible_behavior_ids.intersection(behavior_ids)


def _effect_combatant(entity_id: str, ability_id: str | None = None) -> RuleEntity:
    return RuleEntity(
        entity_id,
        base_attributes={
            "health.maximum": 100_000,
            "spirit.maximum": 10_000,
            "combat.attack": 1_000,
            "combat.defense.physical": 100,
            "combat.speed": 100,
            "combat.accuracy": 1,
            "combat.critical.chance": 0.5,
            "combat.critical.damage": 0.5,
        },
        resources={
            "health.current": 50_000,
            "spirit.current": 10_000,
            "combat.shield.current": 1_000,
        },
        base_abilities=frozenset({ability_id}) if ability_id else frozenset(),
    )


if __name__ == "__main__":
    main()
