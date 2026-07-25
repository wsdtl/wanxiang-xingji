"""物品使用、角色资源写回、持久化防重与故障回滚测试。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.gameplay import (  # noqa: E402
    AbilityDefinition,
    AbilityEngine,
    AbilityUse,
    AttributeResolver,
    AttributeGrant,
    ChangeResource,
    EffectDefinition,
    EffectEngine,
    EffectReference,
    EffectTarget,
    FixedMagnitude,
    GameplayExecutor,
    CharacterContribution,
    ContributionSpec,
    ModifierLayer,
    ResourceCost,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    TagSet,
)
from game.core.gameplay.character import (  # noqa: E402
    COMBAT_ATTACK,
    COMBAT_DEFENSE,
    COMBAT_SPEED,
    HEALTH_CURRENT,
    HEALTH_MAXIMUM,
    SPIRIT_CURRENT,
    SPIRIT_MAXIMUM,
    CharacterCatalog,
    CharacterEngine,
    CharacterProjector,
    CharacterState,
    CharacterTemplateDefinition,
    core_attribute_definitions,
    persistent_resource_definitions,
)
from game.core.gameplay.inventory import (  # noqa: E402
    CharacterItemUse,
    CharacterItemUseEngine,
    GrantStack,
    InventoryAbilityExecutor,
    InventoryEngine,
    InventoryState,
    InventoryTransaction,
    ItemAbilityComponent,
    ItemAssetKind,
    ItemCatalog,
    ItemComponentRegistry,
    ItemContainer,
    ItemDefinition,
    SourceReceipt,
    register_item_ability_component,
)
from game.core.gameplay.registry import DefinitionRegistry  # noqa: E402
from game.core.persistence import (  # noqa: E402
    CHARACTER_AGGREGATE,
    INVENTORY_AGGREGATE,
    PersistedItemUseService,
    SnapshotRepository,
    SqliteDatabase,
    TransactionMismatch,
)


TIME = datetime(2026, 7, 13, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
INVENTORY_ID = "inventory-character-a"


def main() -> None:
    with TemporaryDirectory() as directory:
        _assert_persisted_item_use(Path(directory) / "item-use.db")
        _assert_equipped_maximum_item_use(Path(directory) / "item-use-equipped.db")
    print("item use foundation tests passed")


def _context(seed: int) -> RuleContext:
    return RuleContext(
        f"item-use-{seed}",
        "rules.v1",
        Ruleset("ruleset.standard"),
        TIME,
        SeededRandomSource(seed),
    )


def _environment(path: Path):
    components = ItemComponentRegistry()
    register_item_ability_component(components)
    items = ItemCatalog(components)
    items.register(
        ItemDefinition(
            "item.healing_pill",
            ItemAssetKind.STACK,
            TagSet.of("item.consumable"),
            99,
            {"item_component.use_ability": ItemAbilityComponent("ability.healing_pill")},
        )
    )
    items.register(
        ItemDefinition(
            "item.expensive_pill",
            ItemAssetKind.STACK,
            TagSet.of("item.consumable"),
            99,
            {"item_component.use_ability": ItemAbilityComponent("ability.expensive_pill")},
        )
    )
    items.register(
        ItemDefinition(
            "item.cooldown_talisman",
            ItemAssetKind.STACK,
            TagSet.of("item.consumable"),
            99,
            {"item_component.use_ability": ItemAbilityComponent("ability.cooldown_talisman")},
        )
    )
    items.register(
        ItemDefinition(
            "item.reusable_charm",
            ItemAssetKind.STACK,
            TagSet.of("item.usable"),
            1,
            {
                "item_component.use_ability": ItemAbilityComponent(
                    "ability.healing_pill",
                    consume_quantity=0,
                )
            },
        )
    )
    items.register(
        ItemDefinition(
            "item.plain_material",
            ItemAssetKind.STACK,
            TagSet.of("item.material"),
            99,
        )
    )

    attributes = core_attribute_definitions()
    resources = persistent_resource_definitions()
    effects = DefinitionRegistry[EffectDefinition]("Effect")
    effects.register(
        EffectDefinition(
            "effect.heal_twenty",
            operations=(
                ChangeResource(
                    "operation.heal_twenty",
                    HEALTH_CURRENT,
                    FixedMagnitude(20),
                ),
            ),
        )
    )
    effect_engine = EffectEngine(effects, AttributeResolver(attributes), resources)
    abilities = DefinitionRegistry[AbilityDefinition]("Ability")
    abilities.register(
        AbilityDefinition(
            "ability.healing_pill",
            effects=(EffectReference("effect.heal_twenty", EffectTarget.TARGET),),
        )
    )
    abilities.register(
        AbilityDefinition(
            "ability.expensive_pill",
            costs=(ResourceCost(SPIRIT_CURRENT, FixedMagnitude(100)),),
        )
    )
    abilities.register(AbilityDefinition("ability.cooldown_talisman", cooldown_turns=2))

    inventory_engine = InventoryEngine(items)
    item_abilities = InventoryAbilityExecutor(
        items,
        inventory_engine,
        GameplayExecutor(AbilityEngine(abilities, effect_engine)),
    )
    characters = CharacterCatalog()
    characters.templates.register(
        CharacterTemplateDefinition(
            "character_template.test",
            {
                HEALTH_MAXIMUM: 100,
                SPIRIT_MAXIMUM: 60,
                COMBAT_ATTACK: 10,
                COMBAT_DEFENSE: 5,
                COMBAT_SPEED: 4,
            },
        )
    )
    character_engine = CharacterEngine(characters)
    projector = CharacterProjector(
        characters,
        AttributeResolver(attributes),
        resources,
        ability_ids=frozenset(abilities.ids()),
    )
    engine = CharacterItemUseEngine(item_abilities, character_engine, projector)

    actor = replace(
        characters.create_character(
            character_id="character-a",
            account_id="account-a",
            name="使用者",
            template_id="character_template.test",
            created_at=TIME,
        ),
        resources={HEALTH_CURRENT: 50, SPIRIT_CURRENT: 60},
    )
    target = replace(
        characters.create_character(
            character_id="character-b",
            account_id="account-b",
            name="目标角色",
            template_id="character_template.test",
            created_at=TIME,
        ),
        resources={HEALTH_CURRENT: 40, SPIRIT_CURRENT: 60},
    )
    inventory = InventoryState(
        containers={
            "bag-a": ItemContainer("bag-a", "container.inventory", actor.id),
        }
    )
    grants = inventory_engine.execute(
        InventoryTransaction(
            "grant-item-use-assets",
            "system.test",
            "inventory.test_setup",
            (
                _grant("healing-stack", "item.healing_pill", 3),
                _grant("expensive-stack", "item.expensive_pill", 1),
                _grant("cooldown-stack", "item.cooldown_talisman", 1),
                _grant("reusable-charm", "item.reusable_charm", 1),
                _grant("material-stack", "item.plain_material", 1),
            ),
        ),
        state=inventory,
        context=_context(1),
    )
    assert grants.ok and grants.value
    inventory = grants.value.state

    database = SqliteDatabase(path)
    database.initialize()
    snapshots = SnapshotRepository()
    with database.unit_of_work() as uow:
        snapshots.insert(uow, INVENTORY_AGGREGATE, INVENTORY_ID, inventory, TIME)
        snapshots.insert(uow, CHARACTER_AGGREGATE, actor.id, actor, TIME)
        snapshots.insert(uow, CHARACTER_AGGREGATE, target.id, target, TIME)
        uow.commit()
    return database, snapshots, PersistedItemUseService(database, engine, snapshots)


def _grant(asset_id: str, definition_id: str, quantity: int) -> GrantStack:
    return GrantStack(
        asset_id,
        definition_id,
        "bag-a",
        quantity,
        SourceReceipt(
            f"receipt:{asset_id}",
            "source.test_setup",
            asset_id,
            TIME,
        ),
    )


def _assert_equipped_maximum_item_use(path: Path) -> None:
    database, snapshots, service = _environment(path)
    with database.unit_of_work() as uow:
        character = snapshots.require(
            uow,
            CHARACTER_AGGREGATE,
            "character-a",
            CharacterState,
        )
        updated = replace(
            character,
            resources={HEALTH_CURRENT: 100, SPIRIT_CURRENT: 60},
            revision=character.revision + 1,
        )
        snapshots.update(
            uow,
            CHARACTER_AGGREGATE,
            character.id,
            character,
            updated,
            TIME,
        )
        uow.commit()
    contribution = CharacterContribution(
        "equipment.health.maximum",
        "source.equipment_instance",
        "equipment-health",
        ContributionSpec(
            attributes=(
                AttributeGrant(
                    HEALTH_MAXIMUM,
                    ModifierLayer.GLOBAL_FLAT,
                    50,
                ),
            ),
        ),
    )
    outcome = service.use(
        CharacterItemUse(
            "item-use-equipped-maximum",
            "character-a",
            "character-a",
            "healing-stack",
            AbilityUse("ability-use-equipped-maximum", "ability.healing_pill"),
        ),
        inventory_id=INVENTORY_ID,
        contributions={"character-a": (contribution,)},
        context=_context(9),
    )
    assert outcome.ok and outcome.value, outcome.failure
    _, character, _ = _load(database, snapshots)
    assert character.resources[HEALTH_CURRENT] == 120


def _assert_persisted_item_use(path: Path) -> None:
    database, snapshots, service = _environment(path)
    self_use = CharacterItemUse(
        "item-use-self",
        "character-a",
        "character-a",
        "healing-stack",
        AbilityUse("ability-use-self", "ability.healing_pill"),
    )
    result = service.use(self_use, inventory_id=INVENTORY_ID, context=_context(10))
    assert result.ok and result.value, result.failure
    assert result.value.resource_changes == {
        "character-a": {HEALTH_CURRENT: 20.0},
    }
    inventory, actor, target = _load(database, snapshots)
    assert inventory.stacks["healing-stack"].quantity == 2
    assert actor.resources[HEALTH_CURRENT] == 70 and actor.revision == 1
    assert target.resources[HEALTH_CURRENT] == 40 and target.revision == 0
    committed = service.committed_receipt(self_use.id, actor_id="character-a")
    assert committed and committed.replayed and committed == replace(result.value, replayed=True)
    assert service.committed_receipt("missing-item-use", actor_id="character-a") is None
    outbox_count = _outbox_count(path)

    restarted = PersistedItemUseService(database, service.engine, snapshots)
    replay = restarted.use(self_use, inventory_id=INVENTORY_ID, context=_context(11))
    assert replay.ok and replay.value and replay.value.replayed
    assert _load(database, snapshots) == (inventory, actor, target)
    assert _outbox_count(path) == outbox_count

    try:
        restarted.use(
            replace(self_use, target_id="character-b"),
            inventory_id=INVENTORY_ID,
            context=_context(12),
        )
        raise AssertionError("同一事务 ID 改变目标必须拒绝")
    except TransactionMismatch:
        pass

    other_use = CharacterItemUse(
        "item-use-other",
        "character-a",
        "character-b",
        "healing-stack",
        AbilityUse("ability-use-other", "ability.healing_pill"),
    )
    result = service.use(other_use, inventory_id=INVENTORY_ID, context=_context(20))
    assert result.ok and result.value, result.failure
    inventory, actor, target = _load(database, snapshots)
    assert inventory.stacks["healing-stack"].quantity == 1
    assert actor.resources[HEALTH_CURRENT] == 70 and actor.revision == 1
    assert target.resources[HEALTH_CURRENT] == 60 and target.revision == 1

    before = (inventory, actor, target)
    failed = service.use(
        CharacterItemUse(
            "item-use-insufficient",
            "character-a",
            "character-a",
            "expensive-stack",
            AbilityUse("ability-use-insufficient", "ability.expensive_pill"),
        ),
        inventory_id=INVENTORY_ID,
        context=_context(30),
    )
    assert failed.failure and failed.failure.code == "resource.insufficient"
    assert _load(database, snapshots) == before

    transient = service.use(
        CharacterItemUse(
            "item-use-transient",
            "character-a",
            "character-a",
            "cooldown-stack",
            AbilityUse("ability-use-transient", "ability.cooldown_talisman"),
        ),
        inventory_id=INVENTORY_ID,
        context=_context(31),
    )
    assert transient.failure and transient.failure.code == "item_use.transient_state_not_persistable"
    assert _load(database, snapshots) == before

    wrong_owner = service.use(
        CharacterItemUse(
            "item-use-wrong-owner",
            "character-b",
            "character-b",
            "healing-stack",
            AbilityUse("ability-use-wrong-owner", "ability.healing_pill"),
        ),
        inventory_id=INVENTORY_ID,
        context=_context(32),
    )
    assert wrong_owner.failure and wrong_owner.failure.code == "inventory.owner_mismatch"
    assert _load(database, snapshots) == before

    not_usable = service.use(
        CharacterItemUse(
            "item-use-material",
            "character-a",
            "character-a",
            "material-stack",
            AbilityUse("ability-use-material", "ability.healing_pill"),
        ),
        inventory_id=INVENTORY_ID,
        context=_context(33),
    )
    assert not_usable.failure and not_usable.failure.code == "inventory.item_not_usable"
    assert _load(database, snapshots) == before

    crash_use = CharacterItemUse(
        "item-use-crash-retry",
        "character-a",
        "character-a",
        "healing-stack",
        AbilityUse("ability-use-crash-retry", "ability.healing_pill"),
    )
    original_update = snapshots.update

    def fail_character_update(uow, aggregate_kind, *args, **kwargs):
        if aggregate_kind == CHARACTER_AGGREGATE:
            raise RuntimeError("injected item use persistence failure")
        return original_update(uow, aggregate_kind, *args, **kwargs)

    snapshots.update = fail_character_update
    context = _context(40)
    checkpoint = context.random.checkpoint()
    try:
        service.use(crash_use, inventory_id=INVENTORY_ID, context=context)
        raise AssertionError("故障注入必须中断物品使用提交")
    except RuntimeError as exc:
        assert str(exc) == "injected item use persistence failure"
    finally:
        snapshots.update = original_update
    assert context.random.checkpoint() == checkpoint
    assert _load(database, snapshots) == before
    with database.unit_of_work(write=False) as uow:
        assert uow.load_transaction(crash_use.id) is None

    retried = service.use(crash_use, inventory_id=INVENTORY_ID, context=_context(41))
    assert retried.ok and retried.value and not retried.value.replayed
    inventory, actor, target = _load(database, snapshots)
    assert "healing-stack" not in inventory.stacks
    assert actor.resources[HEALTH_CURRENT] == 90 and actor.revision == 2
    assert target.resources[HEALTH_CURRENT] == 60 and target.revision == 1
    inventory_revision = inventory.revision
    reusable = service.use(
        CharacterItemUse(
            "item-use-reusable",
            "character-a",
            "character-a",
            "reusable-charm",
            AbilityUse("ability-use-reusable", "ability.healing_pill"),
        ),
        inventory_id=INVENTORY_ID,
        context=_context(42),
    )
    assert reusable.ok and reusable.value and reusable.value.consumed_quantity == 0
    inventory, actor, target = _load(database, snapshots)
    assert inventory.revision == inventory_revision
    assert inventory.stacks["reusable-charm"].quantity == 1
    assert actor.resources[HEALTH_CURRENT] == 100 and actor.revision == 3
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM committed_transaction").fetchone()[0] == 4
    finally:
        connection.close()


def _load(database: SqliteDatabase, snapshots: SnapshotRepository):
    with database.unit_of_work(write=False) as uow:
        return (
            snapshots.require(uow, INVENTORY_AGGREGATE, INVENTORY_ID, InventoryState),
            snapshots.require(uow, CHARACTER_AGGREGATE, "character-a", CharacterState),
            snapshots.require(uow, CHARACTER_AGGREGATE, "character-b", CharacterState),
        )


def _outbox_count(path: Path) -> int:
    connection = sqlite3.connect(path)
    try:
        return connection.execute("SELECT COUNT(*) FROM outbox_event").fetchone()[0]
    finally:
        connection.close()


if __name__ == "__main__":
    main()
