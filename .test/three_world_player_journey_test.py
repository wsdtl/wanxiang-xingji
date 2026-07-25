"""同一角色跨三个世界完成玩家主循环的本地驱动验收。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
from importlib import import_module
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.app import build_game_services, install_game_services, restore_game_services  # noqa: E402
from game.content import (  # noqa: E402
    CHARACTER_LEVEL_PROGRESSION_ID,
    DIMENSION_SHIFT_ITEM_ID,
    MAGIC_WORLD_ID,
    SMALL_HEALTH_MEDICINE_ITEM_ID,
    STELLAR_RING_WORLD_ID,
    TAIXUAN_WORLD_ID,
)
from game.content.catalog.world import GREEN_CLOUD_PLAIN_ID, STARTING_CITY_ID  # noqa: E402
from game.core.gameplay import (  # noqa: E402
    HEALTH_CURRENT,
    HEALTH_MAXIMUM,
    SPIRIT_CURRENT,
    CharacterState,
    GrantStack,
    InventoryState,
    InventoryTransaction,
    SourceReceipt,
)
from game.core.persistence import CHARACTER_AGGREGATE, INVENTORY_AGGREGATE  # noqa: E402
from game.rules import game_operation_context  # noqa: E402
from game.rules.exploration import ExplorationStatus  # noqa: E402
from game.rules.item import asset_reference  # noqa: E402
from game.cmd import 地图 as map_component  # noqa: E402,F401
from game.cmd import 角色 as character_component  # noqa: E402,F401
from game.cmd import 休息 as rest_component  # noqa: E402,F401
from game.cmd import 回收 as recycle_component  # noqa: E402,F401
from game.cmd import 探险 as exploration_component  # noqa: E402,F401
from game.cmd import 物品 as item_component  # noqa: E402,F401
from game.cmd import 装配 as loadout_component  # noqa: E402,F401
from game.cmd import 跃迁 as shift_component  # noqa: E402,F401
from launch.adapter.local import LocalEventHandler, dispatch  # noqa: E402


TIMEZONE = ZoneInfo("Asia/Shanghai")
STARTED_AT = datetime(2026, 7, 21, 12, 0, tzinfo=TIMEZONE)
CLIENT_ID = "three-world-journey"


def main() -> None:
    asyncio.run(_main())
    print("three world player journey tests passed")


async def _main() -> None:
    clock = [STARTED_AT]
    for module_name in (
        "game.cmd.地图.service",
        "game.cmd.角色.service",
        "game.cmd.休息.service",
        "game.cmd.探险.service",
        "game.cmd.物品.service",
        "game.cmd.装配.service",
        "game.cmd.跃迁.service",
    ):
        module = import_module(module_name)
        if hasattr(module, "command_time"):
            module.command_time = lambda clock=clock: clock[0]

    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "three-world-journey.db",
            identity_secret="three-world-journey-secret",
        )
        services.character_creation.workflow.id_factory = (
            lambda kind: f"{kind}-three-world-journey"
        )
        services.database.initialize()
        previous = install_game_services(services)
        try:
            await LocalEventHandler.run()
            created = await _dispatch("创建角色 界海行者", "journey-create")
            assert "行纪开篇" in _content(created)
            character = _created_character(services)
            _grant_journey_items(services, character.id)
            auto_medicine = await _dispatch(
                "自动用药 关闭",
                "journey-auto-medicine-off",
            )
            assert "关闭" in _content(auto_medicine)

            initial = services.load_character_overview(character).overview
            assert initial is not None
            world_order = (
                initial.character_world.world_id,
                *(
                    value
                    for value in (
                        TAIXUAN_WORLD_ID,
                        MAGIC_WORLD_ID,
                        STELLAR_RING_WORLD_ID,
                    )
                    if value != initial.character_world.world_id
                ),
            )
            starter_assets = frozenset(initial.inventory.instances)
            expected_loadout = initial.loadout

            for index, world_id in enumerate(world_order):
                if index:
                    shifted = await _dispatch(
                        f"跃迁 {world_id}",
                        f"journey-shift-{index}",
                    )
                    assert "目标世界已完成化身重构" in _content(shifted)
                    after_shift = services.load_character_overview(character).overview
                    assert after_shift is not None
                    assert after_shift.loadout == expected_loadout
                    assert starter_assets <= set(after_shift.inventory.instances)

                before = services.load_character_overview(character).overview
                assert before is not None
                assert before.character_world.world_id == world_id
                view = services.world_views.require(world_id)

                assert "界海行者" in _content(
                    await _dispatch("我的角色", f"journey-profile-{index}")
                )
                assert "武库" in _content(
                    await _dispatch("武库", f"journey-armory-{index}")
                )
                assert "当前装配" in _content(
                    await _dispatch("装配", f"journey-loadout-{index}")
                )

                map_result = await _dispatch("地图", f"journey-map-{index}")
                map_text = _content(map_result)
                assert view.skin.name in map_text
                assert len(services.content.worlds.bindings_for_world(world_id)) == 17
                assert all(
                    view.projector.name(binding.display_ref) in map_text
                    for binding in services.content.worlds.bindings_for_world(world_id)
                )

                if index:
                    city_name = view.projector.name(STARTING_CITY_ID)
                    city_detail = await _dispatch(
                        f"地图 {city_name}",
                        f"journey-city-detail-{index}",
                    )
                    city_action = next(
                        value for value in city_detail.replies[0].message.actions
                        if value.label == "前往"
                    )
                    assert "抵达" in _content(
                        await _dispatch(city_action.data, f"journey-city-move-{index}")
                    )

                region_name = view.projector.name(GREEN_CLOUD_PLAIN_ID)
                region_detail = await _dispatch(
                    f"地图 {region_name}",
                    f"journey-region-detail-{index}",
                )
                assert "Lv1-12" in _content(region_detail)
                region_action = next(
                    value for value in region_detail.replies[0].message.actions
                    if value.label == "前往"
                )
                assert "抵达" in _content(
                    await _dispatch(region_action.data, f"journey-region-move-{index}")
                )

                (
                    after_exploration,
                    baseline_instances,
                    baseline_trophies,
                ) = await _explore_until_progress(
                    services,
                    character,
                    clock,
                    world_id,
                    index,
                )
                assert await _process_new_drop(
                    services,
                    after_exploration,
                    baseline_instances,
                    baseline_trophies,
                    index,
                )

                latest = services.load_character_overview(character).overview
                assert latest is not None
                expected_loadout = latest.loadout
                maximum_health = latest.character.core_attributes[HEALTH_MAXIMUM]
                _set_resources(
                    services,
                    character.id,
                    health=max(1, maximum_health / 2),
                    spirit=latest.character.resources[SPIRIT_CURRENT],
                    logical_time=clock[0],
                )
                medicine = next(
                    stack
                    for stack in services.load_character_overview(character).overview.inventory.stacks.values()
                    if stack.definition_id == SMALL_HEALTH_MEDICINE_ITEM_ID
                )
                medicine_ref = services.load_character_overview(
                    character
                ).overview.inventory.reference_number(medicine.id)
                used = await _dispatch(
                    f"使用 I{medicine_ref} 1",
                    f"journey-medicine-{index}",
                )
                assert "消耗: _1_" in _content(used)

                assert "已经开始休息" in _content(
                    await _dispatch("休息", f"journey-rest-{index}")
                )
                clock[0] += timedelta(minutes=2)
                rested = await _dispatch("结束休息", f"journey-rest-stop-{index}")
                assert "恢复" in _content(rested) or "结束" in _content(rested)

                restarted = await _dispatch(
                    "开始探险",
                    f"journey-restart-{index}",
                )
                assert "首次结算" in _content(restarted)
                assert "停止" in _content(
                    await _dispatch("停止探险", f"journey-final-stop-{index}")
                )
                final = services.load_character_overview(character).overview
                assert final is not None
                expected_loadout = final.loadout
        finally:
            restore_game_services(previous)


async def _explore_until_progress(
    services,
    character,
    clock: list[datetime],
    world_id: str,
    index: int,
):
    initial = services.load_character_overview(character).overview
    assert initial is not None
    baseline_experience = initial.character.progressions[
        CHARACTER_LEVEL_PROGRESSION_ID
    ].total_experience
    baseline_instances = set(initial.inventory.instances)
    baseline_trophies = _trophy_quantity(services, initial)
    attempts = []

    for attempt in range(1, 5):
        started = await _dispatch(
            "开始探险",
            f"journey-start-{index}-{attempt}",
        )
        assert "首次结算" in _content(started)
        batches = []
        for _ in range(12):
            clock[0] += timedelta(minutes=10)
            settled = services.exploration.settle_due(
                character.id,
                logical_time=clock[0],
            )
            batches.extend(settled.batches)
            latest = services.load_character_overview(character).overview
            assert latest is not None
            gained_experience = latest.character.progressions[
                CHARACTER_LEVEL_PROGRESSION_ID
            ].total_experience > baseline_experience
            gained_drop = bool(
                set(latest.inventory.instances) - baseline_instances
                or _trophy_quantity(services, latest) > baseline_trophies
            )
            if gained_experience and gained_drop:
                break
            if settled.state is None or settled.state.status is not ExplorationStatus.RUNNING:
                break
        assert batches, f"{world_id} 第 {attempt} 次探险没有形成结算批次"
        assert "探险" in _content(
            await _dispatch(
                "探险总结",
                f"journey-summary-{index}-{attempt}",
            )
        )
        state = services.exploration.load(
            character.id,
            logical_time=clock[0],
        ).state
        if state is not None and state.status is ExplorationStatus.RUNNING:
            assert "停止" in _content(
                await _dispatch(
                    "停止探险",
                    f"journey-stop-{index}-{attempt}",
                )
            )
        latest = services.load_character_overview(character).overview
        assert latest is not None
        gained_experience = latest.character.progressions[
            CHARACTER_LEVEL_PROGRESSION_ID
        ].total_experience > baseline_experience
        gained_drop = bool(
            set(latest.inventory.instances) - baseline_instances
            or _trophy_quantity(services, latest) > baseline_trophies
        )
        attempts.append((state, batches, latest.character.resources))
        if gained_experience and gained_drop:
            return latest, baseline_instances, baseline_trophies

        rest = await _dispatch(
            "休息",
            f"journey-recovery-rest-{index}-{attempt}",
        )
        assert "已经开始休息" in _content(rest)
        clock[0] += timedelta(minutes=30)
        recovered = await _dispatch(
            "结束休息",
            f"journey-recovery-stop-{index}-{attempt}",
        )
        assert "恢复" in _content(recovered) or "结束" in _content(recovered)

    raise AssertionError((world_id, "四次探险仍未形成经验与掉落闭环", attempts))


async def _process_new_drop(
    services,
    overview,
    baseline_instances: set[str],
    baseline_trophies: int,
    index: int,
) -> bool:
    for instance in overview.inventory.instances.values():
        if instance.id in baseline_instances:
            continue
        definition = services.content.catalog.items.require(instance.definition_id)
        if definition.tags.has("item.weapon") or definition.tags.has("item.equipment"):
            reference = asset_reference(
                overview.inventory,
                instance,
                services.content.catalog.items,
            )
            result = await _dispatch(
                f"装备 {reference}",
                f"journey-equip-{index}",
            )
            assert "装配" in _content(result) or "装备" in _content(result)
            return True
    if _trophy_quantity(services, overview) > baseline_trophies:
        result = await _dispatch("回收战利品", f"journey-recycle-{index}")
        assert "回收" in _content(result)
        return True
    return False


def _trophy_quantity(services, overview) -> int:
    return sum(
        stack.quantity
        for stack in overview.inventory.stacks.values()
        if services.content.catalog.items.require(stack.definition_id).tags.has(
            "item.trophy"
        )
    )


def _created_character(services):
    with services.database.unit_of_work(write=False) as uow:
        row = uow.connection.execute(
            "SELECT aggregate_id FROM aggregate_snapshot WHERE aggregate_kind = ?",
            (CHARACTER_AGGREGATE,),
        ).fetchone()
    character = services.characters.load_character(str(row[0]))
    assert character is not None
    return character


def _grant_journey_items(services, character_id: str) -> None:
    snapshots = services.character_creation.snapshots
    with services.database.unit_of_work() as uow:
        inventory = snapshots.require(
            uow,
            INVENTORY_AGGREGATE,
            character_id,
            InventoryState,
        )
        special = next(
            value.id
            for value in inventory.containers.values()
            if value.kind == "container.special"
        )
        receipt = SourceReceipt(
            "three-world-journey-receipt",
            "source.test",
            character_id,
            STARTED_AT,
        )
        outcome = services.inventory_engine.execute(
            InventoryTransaction(
                "three-world-journey-grant",
                character_id,
                "inventory.test_setup",
                (
                    GrantStack(
                        "three-world-shift-stack",
                        DIMENSION_SHIFT_ITEM_ID,
                        special,
                        2,
                        receipt,
                    ),
                    GrantStack(
                        "three-world-health-stack",
                        SMALL_HEALTH_MEDICINE_ITEM_ID,
                        special,
                        3,
                        receipt,
                    ),
                ),
            ),
            state=inventory,
            context=game_operation_context(
                "three-world-journey-grant",
                logical_time=STARTED_AT,
            ),
        ).unwrap()
        snapshots.update(
            uow,
            INVENTORY_AGGREGATE,
            character_id,
            inventory,
            outcome.state,
            STARTED_AT,
        )
        uow.commit()


def _set_resources(
    services,
    character_id: str,
    *,
    health: float,
    spirit: float,
    logical_time: datetime,
) -> None:
    snapshots = services.character_creation.snapshots
    with services.database.unit_of_work() as uow:
        character = snapshots.require(
            uow,
            CHARACTER_AGGREGATE,
            character_id,
            CharacterState,
        )
        updated = replace(
            character,
            resources={HEALTH_CURRENT: health, SPIRIT_CURRENT: spirit},
            revision=character.revision + 1,
        )
        snapshots.update(
            uow,
            CHARACTER_AGGREGATE,
            character_id,
            character,
            updated,
            logical_time,
        )
        uow.commit()


async def _dispatch(command: str, event_id: str):
    return await dispatch(
        client_id=CLIENT_ID,
        raw_message=command,
        sender_name="界海行者",
        event_id=event_id,
    )


def _content(result) -> str:
    assert result.matched and result.matched_count == 1, result
    assert len(result.replies) == 1, result
    message = result.replies[0].message
    assert message.kind == "markdown"
    assert message.content.strip()
    return message.content


if __name__ == "__main__":
    main()
