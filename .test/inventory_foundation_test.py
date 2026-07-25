"""物品与物资底座的原子性、来源和 Ability 联动测试。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
import sys
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.gameplay import (  # noqa: E402
    AbilityDefinition,
    AbilityEngine,
    AbilityUse,
    AttributeDefinition,
    AttributeResolver,
    ChangeResource,
    EffectDefinition,
    EffectEngine,
    EffectReference,
    EffectTarget,
    FixedMagnitude,
    GameplayExecutor,
    ResourceCost,
    ResourceDefinition,
    RuleContext,
    RuleEntity,
    Ruleset,
    SeededRandomSource,
    TagSet,
)
from game.core.gameplay.registry import DefinitionRegistry  # noqa: E402
from game.core.gameplay.inventory import (  # noqa: E402
    AppendStack,
    AssetAvailability,
    ConsumeStack,
    ConsumeInstance,
    DestroyAsset,
    GrantInstance,
    GrantStack,
    INVENTORY_FOUNDATION_VERSION,
    InventoryAbilityExecutor,
    InventoryEngine,
    InventoryState,
    InventoryTransaction,
    ItemAbilityComponent,
    ItemAbilityUse,
    ItemAssetKind,
    ItemCatalog,
    ItemComponentRegistry,
    ItemContainer,
    ItemDefinition,
    ItemStorageComponent,
    MergeStacks,
    MoveAsset,
    ProtectAsset,
    ReleaseReservation,
    ReservationMode,
    ReserveAsset,
    SourceReceipt,
    SplitStack,
    UnprotectAsset,
    UpdateInstance,
    register_item_ability_component,
    register_item_storage_component,
)


TIME = datetime(2026, 7, 12, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def main() -> None:
    _assert_definition_and_container_boundaries()
    _assert_append_stack()
    _assert_asset_transactions_and_provenance()
    _assert_asset_protection()
    _assert_reservations_and_escrow()
    _assert_atomic_cross_owner_failure()
    _assert_expiration()
    _assert_item_ability_atomicity()
    print("inventory foundation tests passed")


def _context(*, at: datetime = TIME, seed: int = 7) -> RuleContext:
    return RuleContext(
        trace_id=f"inventory-test-{seed}-{at.timestamp()}",
        rule_version="rules.v1",
        ruleset=Ruleset("ruleset.standard"),
        logical_time=at,
        random=SeededRandomSource(seed),
    )


def _receipt(receipt_id: str, source_id: str = "reward-1") -> SourceReceipt:
    return SourceReceipt(receipt_id, "source.gameplay_reward", source_id, TIME)


def _catalog(*, with_ability: bool = False) -> ItemCatalog:
    components = ItemComponentRegistry()
    register_item_storage_component(components)
    if with_ability:
        register_item_ability_component(components)
    catalog = ItemCatalog(components)
    catalog.register(
        ItemDefinition(
            "item.spirit_ore",
            ItemAssetKind.STACK,
            tags=TagSet.of("item.material"),
            stack_limit=100,
            components={"item_component.storage": ItemStorageComponent(2)},
        )
    )
    catalog.register(
        ItemDefinition(
            "item.training_sword",
            ItemAssetKind.INSTANCE,
            tags=TagSet.of("item.equipment"),
            components={"item_component.storage": ItemStorageComponent(3)},
        )
    )
    if with_ability:
        catalog.register(
            ItemDefinition(
                "item.healing_pill",
                ItemAssetKind.STACK,
                tags=TagSet.of("item.consumable"),
                stack_limit=99,
                components={
                    "item_component.use_ability": ItemAbilityComponent(
                        "ability.use_healing_pill"
                    ),
                    "item_component.storage": ItemStorageComponent(1),
                },
            )
        )
        catalog.register(
            ItemDefinition(
                "item.reusable_charm",
                ItemAssetKind.INSTANCE,
                tags=TagSet.of("item.usable"),
                components={
                    "item_component.use_ability": ItemAbilityComponent(
                        "ability.use_healing_pill",
                        consume_quantity=0,
                    ),
                    "item_component.storage": ItemStorageComponent(1),
                },
            )
        )
    return catalog


def _containers() -> dict[str, ItemContainer]:
    return {
        "bag-a": ItemContainer("bag-a", "container.inventory", "player-a"),
        "bag-b": ItemContainer("bag-b", "container.inventory", "player-b"),
        "escrow": ItemContainer("escrow", "container.trade_escrow", "market-system"),
        "equipment-a": ItemContainer(
            "equipment-a",
            "container.equipment_slot",
            "player-a",
            accepted_kinds=frozenset({ItemAssetKind.INSTANCE}),
            required_item_tags=TagSet.of("item.equipment"),
            maximum_assets=1,
        ),
        "small-bag": ItemContainer(
            "small-bag",
            "container.inventory",
            "player-a",
            maximum_assets=1,
        ),
        "space-bag": ItemContainer(
            "space-bag",
            "container.backpack",
            "player-a",
            maximum_space=8,
        ),
    }


def _execute(
    engine: InventoryEngine,
    state: InventoryState,
    transaction_id: str,
    *operations,
    context: RuleContext | None = None,
):
    outcome = engine.execute(
        InventoryTransaction(
            transaction_id,
            "player-a",
            "inventory.test_operation",
            tuple(operations),
        ),
        state=state,
        context=context or _context(),
    )
    assert outcome.ok and outcome.value, outcome.failure
    return outcome.value


def _assert_definition_and_container_boundaries() -> None:
    catalog = _catalog()
    engine = InventoryEngine(catalog)
    assert catalog.finalized
    assert INVENTORY_FOUNDATION_VERSION == "inventory.foundation.v6"
    state = InventoryState(containers=_containers())
    rejected = engine.execute(
        InventoryTransaction(
            "reject-stack-equipment",
            "player-a",
            "inventory.test_operation",
            (
                GrantStack(
                    "ore-rejected",
                    "item.spirit_ore",
                    "equipment-a",
                    1,
                    _receipt("receipt-rejected"),
                ),
            ),
        ),
        state=state,
        context=_context(),
    )
    assert rejected.failure and rejected.failure.code == "inventory.container_rejected"
    assert not state.stacks

    try:
        catalog.register(ItemDefinition("item.too_late", ItemAssetKind.STACK))
        raise AssertionError("运行期不能修改已冻结物品目录")
    except RuntimeError:
        pass


def _base_assets() -> tuple[InventoryEngine, InventoryState]:
    engine = InventoryEngine(_catalog())
    state = InventoryState(containers=_containers())
    result = _execute(
        engine,
        state,
        "grant-assets",
        GrantStack("ore-a", "item.spirit_ore", "bag-a", 30, _receipt("receipt-a")),
        GrantStack("ore-b", "item.spirit_ore", "bag-a", 20, _receipt("receipt-b")),
        GrantInstance(
            "sword-a",
            "item.training_sword",
            "bag-a",
            _receipt("receipt-sword", "forge-1"),
            {"quality_seed": 17},
        ),
    )
    assert [event.kind for event in result.events] == ["inventory.item.granted"] * 3
    assert result.state.asset_references == {
        "ore-a": 1,
        "ore-b": 2,
        "sword-a": 3,
    }
    assert result.state.next_reference_number == 4
    return engine, result.state


def _assert_append_stack() -> None:
    engine, state = _base_assets()
    appended = _execute(
        engine,
        state,
        "append-ore",
        AppendStack("ore-a", 5, _receipt("receipt-appended")),
    )
    stack = appended.state.stacks["ore-a"]
    assert stack.quantity == 35
    assert stack.revision == 1
    assert [(lot.receipt.id, lot.quantity) for lot in stack.lots] == [
        ("receipt-a", 30),
        ("receipt-appended", 5),
    ]
    assert appended.state.reference_number("ore-a") == 1


def _assert_asset_protection() -> None:
    engine, state = _base_assets()
    protected = _execute(
        engine,
        state,
        "protect-sword",
        ProtectAsset("sword-a"),
    )
    assert protected.state.is_protected("sword-a")
    assert protected.state.revision == state.revision + 1
    assert protected.events[-1].kind == "inventory.item.protected"

    repeated = _execute(
        engine,
        protected.state,
        "protect-sword-again",
        ProtectAsset("sword-a"),
    )
    assert repeated.state is protected.state
    assert repeated.state.revision == protected.state.revision
    assert not repeated.events

    moved = _execute(
        engine,
        protected.state,
        "equip-protected-sword",
        MoveAsset("sword-a", "equipment-a"),
    ).state
    assert moved.is_protected("sword-a")
    assert moved.instances["sword-a"].container_id == "equipment-a"
    current_sword = moved.instances["sword-a"]
    updated = _execute(
        engine,
        moved,
        "update-protected-sword",
        UpdateInstance(
            replace(current_sword, data={"quality_seed": 18}),
            current_sword.revision,
        ),
    ).state
    assert updated.is_protected("sword-a")
    assert updated.instances["sword-a"].data["quality_seed"] == 18
    moved = updated

    for operation in (
        DestroyAsset("sword-a"),
        ConsumeInstance("sword-a"),
        MoveAsset("sword-a", "bag-b"),
        ReserveAsset(
            "protected-escrow",
            "sword-a",
            ReservationMode.ESCROWED,
            "business.market_order",
            "protected-order",
        ),
    ):
        rejected = engine.execute(
            InventoryTransaction(
                f"reject-protected-{type(operation).__name__}",
                "player-a",
                "inventory.test_operation",
                (operation,),
            ),
            state=moved,
            context=_context(),
        )
        assert rejected.failure and rejected.failure.code == "inventory.asset_protected"

    stack_rejected = engine.execute(
        InventoryTransaction(
            "reject-stack-protection",
            "player-a",
            "inventory.test_operation",
            (ProtectAsset("ore-a"),),
        ),
        state=moved,
        context=_context(),
    )
    assert stack_rejected.failure and stack_rejected.failure.code == "inventory.instance_unknown"

    unprotected = _execute(
        engine,
        moved,
        "unprotect-sword",
        UnprotectAsset("sword-a"),
    )
    assert not unprotected.state.is_protected("sword-a")
    repeated_unprotect = _execute(
        engine,
        unprotected.state,
        "unprotect-sword-again",
        UnprotectAsset("sword-a"),
    )
    assert repeated_unprotect.state.revision == unprotected.state.revision
    transferred = _execute(
        engine,
        repeated_unprotect.state,
        "transfer-unprotected-sword",
        MoveAsset("sword-a", "bag-b"),
    ).state
    assert transferred.owner_of("sword-a") == "player-b"


def _assert_asset_transactions_and_provenance() -> None:
    engine, state = _base_assets()
    merged = _execute(
        engine,
        state,
        "merge-ore",
        MergeStacks("ore-b", "ore-a"),
    ).state
    assert merged.stacks["ore-a"].quantity == 50
    assert merged.reference_number("ore-a") == 1
    assert "ore-b" not in merged.asset_references
    assert [lot.receipt.id for lot in merged.stacks["ore-a"].lots] == [
        "receipt-a",
        "receipt-b",
    ]
    split = _execute(
        engine,
        merged,
        "split-ore",
        SplitStack("ore-a", "ore-transfer", 35),
    ).state
    assert split.stacks["ore-a"].quantity == 15
    assert split.stacks["ore-transfer"].quantity == 35
    assert split.reference_number("ore-transfer") == 4
    assert split.asset_id_for_reference(4) == "ore-transfer"
    assert [(lot.receipt.id, lot.quantity) for lot in split.stacks["ore-transfer"].lots] == [
        ("receipt-a", 30),
        ("receipt-b", 5),
    ]
    moved = _execute(
        engine,
        split,
        "transfer-ore",
        MoveAsset("ore-transfer", "bag-b"),
    )
    assert moved.state.owner_of("ore-transfer") == "player-b"
    assert moved.state.reference_number("ore-transfer") == 4
    assert moved.events[-1].kind == "inventory.item.transferred"
    assert moved.events[-1].values["from_owner_id"] == "player-a"

    small = InventoryState(containers=_containers())
    full = _execute(
        engine,
        small,
        "grant-small-bag",
        GrantStack(
            "ore-small",
            "item.spirit_ore",
            "small-bag",
            2,
            _receipt("receipt-small"),
        ),
    ).state
    rejected_split = engine.execute(
        InventoryTransaction(
            "split-full-container",
            "player-a",
            "inventory.test_operation",
            (SplitStack("ore-small", "ore-small-split", 1),),
        ),
        state=full,
        context=_context(),
    )
    assert rejected_split.failure
    assert rejected_split.failure.code == "inventory.container_full"
    assert set(full.stacks) == {"ore-small"}

    space_limited = _execute(
        engine,
        InventoryState(containers=_containers()),
        "fill-space-bag",
        GrantStack(
            "space-ore",
            "item.spirit_ore",
            "space-bag",
            4,
            _receipt("receipt-space"),
        ),
    ).state
    rejected_space = engine.execute(
        InventoryTransaction(
            "overflow-space-bag",
            "player-a",
            "inventory.test_operation",
            (
                GrantInstance(
                    "space-sword",
                    "item.training_sword",
                    "space-bag",
                    _receipt("receipt-space-sword"),
                ),
            ),
        ),
        state=space_limited,
        context=_context(),
    )
    assert rejected_space.failure
    assert rejected_space.failure.code == "inventory.container_space_full"
    assert "space-sword" not in space_limited.asset_references


def _assert_reservations_and_escrow() -> None:
    engine, state = _base_assets()
    reserved = _execute(
        engine,
        state,
        "reserve-ore",
        ReserveAsset(
            "reservation-ore",
            "ore-a",
            ReservationMode.LOCKED,
            "business.crafting",
            "craft-7",
            quantity=25,
        ),
    ).state
    assert reserved.availability("ore-a") is AssetAvailability.LOCKED
    blocked = engine.execute(
        InventoryTransaction(
            "consume-reserved-without-token",
            "player-a",
            "inventory.test_operation",
            (ConsumeStack("ore-a", 10),),
        ),
        state=reserved,
        context=_context(),
    )
    assert blocked.failure and blocked.failure.code == "inventory.asset_reserved"
    assert reserved.stacks["ore-a"].quantity == 30
    consumed = _execute(
        engine,
        reserved,
        "consume-reserved",
        ConsumeStack("ore-a", 10, "reservation-ore"),
    ).state
    assert consumed.stacks["ore-a"].quantity == 20
    assert consumed.reservations["reservation-ore"].quantity == 15

    escrowed = _execute(
        engine,
        consumed,
        "escrow-sword",
        ReserveAsset(
            "reservation-sword",
            "sword-a",
            ReservationMode.ESCROWED,
            "business.market_order",
            "order-9",
        ),
        MoveAsset("sword-a", "escrow", "reservation-sword"),
    ).state
    assert escrowed.owner_of("sword-a") == "market-system"
    assert escrowed.reservations["reservation-sword"].mode is ReservationMode.ESCROWED
    released = _execute(
        engine,
        escrowed,
        "release-sword",
        ReleaseReservation("reservation-sword"),
    ).state
    assert "reservation-sword" not in released.reservations


def _assert_atomic_cross_owner_failure() -> None:
    engine, state = _base_assets()
    context = _context(seed=91)
    random_checkpoint = context.random.checkpoint()
    failed = engine.execute(
        InventoryTransaction(
            "failed-cross-owner",
            "player-a",
            "inventory.test_operation",
            (
                MoveAsset("sword-a", "bag-b"),
                GrantStack(
                    "invalid-grant",
                    "item.unknown",
                    "bag-b",
                    1,
                    _receipt("receipt-invalid"),
                ),
            ),
        ),
        state=state,
        context=context,
    )
    assert failed.failure and failed.failure.code == "inventory.item_unknown"
    assert state.owner_of("sword-a") == "player-a"
    assert state.revision == 1
    assert context.random.checkpoint() == random_checkpoint


def _assert_expiration() -> None:
    engine, state = _base_assets()
    reserved = _execute(
        engine,
        state,
        "expiring-reservation",
        ReserveAsset(
            "reservation-expiring",
            "ore-a",
            ReservationMode.RESERVED,
            "business.reward_choice",
            "choice-1",
            quantity=30,
            expires_at=TIME + timedelta(minutes=5),
        ),
    ).state
    after_expiry = _execute(
        engine,
        reserved,
        "consume-after-expiry",
        ConsumeStack("ore-a", 1),
        context=_context(at=TIME + timedelta(minutes=6)),
    )
    assert "reservation-expiring" not in after_expiry.state.reservations
    assert [event.values.get("release_cause") for event in after_expiry.events] == [
        "expired",
        None,
    ]
    assert [event.values.get("reason") for event in after_expiry.events] == [
        "inventory.test_operation",
        "inventory.test_operation",
    ]


def _ability_executor() -> tuple[InventoryAbilityExecutor, InventoryEngine]:
    catalog = _catalog(with_ability=True)
    inventory = InventoryEngine(catalog)
    attributes = {
        "health.maximum": AttributeDefinition("health.maximum", default=100, minimum=1),
    }
    resources = {
        "health.current": ResourceDefinition(
            "health.current",
            maximum_attribute="health.maximum",
        ),
        "energy.current": ResourceDefinition("energy.current", fixed_maximum=10),
    }
    effects = DefinitionRegistry[EffectDefinition]("Effect")
    effects.register(
        EffectDefinition(
            "effect.healing_pill",
            operations=(
                ChangeResource(
                    "operation.healing_pill",
                    "health.current",
                    FixedMagnitude(20),
                ),
            ),
        )
    )
    effect_engine = EffectEngine(effects, AttributeResolver(attributes), resources)
    abilities = DefinitionRegistry[AbilityDefinition]("Ability")
    abilities.register(
        AbilityDefinition(
            "ability.use_healing_pill",
            costs=(ResourceCost("energy.current", FixedMagnitude(5)),),
            effects=(EffectReference("effect.healing_pill", EffectTarget.SELF),),
        )
    )
    gameplay = GameplayExecutor(AbilityEngine(abilities, effect_engine))
    return InventoryAbilityExecutor(catalog, inventory, gameplay), inventory


def _assert_item_ability_atomicity() -> None:
    executor, inventory = _ability_executor()
    state = InventoryState(containers=_containers())
    granted = _execute(
        inventory,
        state,
        "grant-pills",
        GrantStack(
            "pill-stack",
            "item.healing_pill",
            "bag-a",
            2,
            _receipt("receipt-pill", "alchemy-1"),
        ),
    ).state
    actor = RuleEntity(
        "player-a",
        base_attributes={"health.maximum": 100},
        resources={"health.current": 50, "energy.current": 0},
    )
    use = ItemAbilityUse(
        "use-pill-1",
        "pill-stack",
        AbilityUse("ability-use-pill-1", "ability.use_healing_pill"),
    )
    context = _context(seed=101)
    checkpoint = context.random.checkpoint()
    failed = executor.execute(
        use,
        inventory_state=granted,
        actor=actor,
        target=actor,
        context=context,
    )
    assert failed.failure and failed.failure.code == "resource.insufficient"
    assert granted.stacks["pill-stack"].quantity == 2
    assert context.random.checkpoint() == checkpoint

    ready = replace(actor, resources={"health.current": 50, "energy.current": 10})
    success = executor.execute(
        replace(use, transaction_id="use-pill-2"),
        inventory_state=granted,
        actor=ready,
        target=ready,
        context=_context(seed=102),
    )
    assert success.ok and success.value, success.failure
    assert success.value.inventory.stacks["pill-stack"].quantity == 1
    assert success.value.actor.resources["health.current"] == 70
    assert success.value.actor.resources["energy.current"] == 5
    assert "ability.use_healing_pill" not in success.value.actor.base_abilities
    kinds = [event.kind for event in success.value.events]
    assert kinds[0] == "inventory.item.consumed"
    assert kinds[-1] == "inventory.item.used"

    with_charm = _execute(
        inventory,
        success.value.inventory,
        "grant-reusable-charm",
        GrantInstance(
            "reusable-charm",
            "item.reusable_charm",
            "bag-a",
            _receipt("receipt-reusable-charm", "crafting-1"),
        ),
    ).state
    reserved = _execute(
        inventory,
        with_charm,
        "reserve-reusable-charm",
        ReserveAsset(
            "reservation-reusable-charm",
            "reusable-charm",
            ReservationMode.LOCKED,
            "business.test_lock",
            "lock-1",
        ),
    ).state
    reusable_use = ItemAbilityUse(
        "use-reusable-charm",
        "reusable-charm",
        AbilityUse("ability-use-reusable-charm", "ability.use_healing_pill"),
    )
    blocked = executor.execute(
        reusable_use,
        inventory_state=reserved,
        actor=ready,
        target=ready,
        context=_context(seed=103),
    )
    assert blocked.failure and blocked.failure.code == "inventory.asset_reserved"
    authorized = executor.execute(
        replace(reusable_use, reservation_id="reservation-reusable-charm"),
        inventory_state=reserved,
        actor=ready,
        target=ready,
        context=_context(seed=104),
    )
    assert authorized.ok and authorized.value, authorized.failure
    assert "reusable-charm" in authorized.value.inventory.instances
    assert authorized.value.inventory.revision == reserved.revision


if __name__ == "__main__":
    main()
