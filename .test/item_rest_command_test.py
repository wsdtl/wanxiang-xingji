"""物品查询、百件分页、手动用药与休息恢复闭环测试。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.app import build_game_services, install_game_services, restore_game_services  # noqa: E402
from game.content import (  # noqa: E402
    COMMON_QUALITY_ID,
    SMALL_HEALTH_MEDICINE_ITEM_ID,
    STARTER_WEAPON_ID,
    STARTER_WEAPON_ITEM_ID,
)
from game.core.gameplay import (  # noqa: E402
    HEALTH_CURRENT,
    SPIRIT_CURRENT,
    WEAPON_SLOT_ID,
    GrantInstance,
    CharacterState,
    InventoryEngine,
    InventoryState,
    InventoryTransaction,
    SourceReceipt,
    weapon_state_data,
    weapon_state_from_instance,
)
from game.core.persistence import CHARACTER_AGGREGATE, INVENTORY_AGGREGATE  # noqa: E402
from game.rules import game_operation_context  # noqa: E402
from game.rules.item import asset_reference  # noqa: E402
from game.cmd import 休息 as rest_component  # noqa: E402,F401
from game.cmd import 物品 as item_component  # noqa: E402,F401
from game.cmd import 角色 as character_component  # noqa: E402,F401
from game.cmd.物品.service import _armory_assets, _asset_page  # noqa: E402
from launch.adapter.local import LocalEventHandler, dispatch  # noqa: E402
from launch.adapter.qq import QqEventHandler  # noqa: E402
from launch.adapter.qq.render import render_qq_message  # noqa: E402


TIMEZONE = ZoneInfo("Asia/Shanghai")


def main() -> None:
    asyncio.run(_main())
    print("item and rest command tests passed")


async def _main() -> None:
    for command in (
        "纳戒",
        "武库",
        "背包",
        "查看",
        "珍藏",
        "取消珍藏",
        "使用",
        "休息",
        "结束休息",
    ):
        assert len(LocalEventHandler.exact_rules[command]) == 1
        assert len(QqEventHandler.exact_rules[command]) == 1

    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "item-rest.db",
            identity_secret="item-rest-command-secret",
        )
        services.database.initialize()
        previous = install_game_services(services)
        try:
            await LocalEventHandler.run()
            await dispatch(
                client_id="item-rest-player",
                raw_message="创建角色 归藏客",
                sender_name="归藏客",
                event_id="item-rest-create",
            )
            character = _character(services)
            overview = services.load_character_overview(character).overview
            assert overview is not None
            view = services.world_view(overview.character_world)
            assert any(
                container.kind == "container.inscription"
                and container.required_item_tags.has("storage.inscription")
                for container in overview.inventory.containers.values()
            )
            medicine = next(
                stack
                for stack in overview.inventory.stacks.values()
                if stack.definition_id == SMALL_HEALTH_MEDICINE_ITEM_ID
            )
            medicine_ref = overview.inventory.reference_number(medicine.id)

            nacre = await _dispatch("纳戒", "item-rest-nacre")
            assert view.projector.name(SMALL_HEALTH_MEDICINE_ITEM_ID) in nacre.replies[0].message.content
            detail = await _dispatch(f"查看 I{medicine_ref}", "item-rest-inspect")
            assert "数量: _2_" in detail.replies[0].message.content
            assert "单次: _12_" in detail.replies[0].message.content
            wrong_prefix = await _dispatch(f"查看 W{medicine_ref}", "item-rest-prefix")
            assert "前缀应为 I" in wrong_prefix.replies[0].message.content
            stack_protection = await _dispatch(
                f"珍藏 I{medicine_ref}",
                "item-rest-protect-stack",
            )
            assert "只有武器和装备可以加入珍藏" in stack_protection.replies[0].message.content

            _set_resources(services, character.id, health=10, spirit=20)
            used = await _dispatch(f"使用 I{medicine_ref} 2", "item-rest-use")
            assert "消耗: _2_" in used.replies[0].message.content
            character = services.characters.load_character(character.id)
            assert character is not None and character.resources[HEALTH_CURRENT] == 34

            _grant_weapons(services, character.id, 101)
            armory = await _dispatch("武库", "item-rest-armory")
            slot_name = view.projector.name(WEAPON_SLOT_ID)
            assert f"{slot_name}: _102_" in armory.replies[0].message.content
            first_page = await _dispatch(f"武库 {slot_name}", "item-rest-armory-page-1")
            overview = services.load_character_overview(character).overview
            assert overview is not None
            starter = next(
                value
                for value in overview.inventory.instances.values()
                if value.definition_id == STARTER_WEAPON_ITEM_ID
            )
            starter_name = view.gear_projector.weapon(
                weapon_state_from_instance(starter),
                starter,
            ).name
            starter_reference = asset_reference(
                overview.inventory,
                starter,
                services.content.catalog.items,
            )
            protected = await _dispatch(
                f"珍藏 {starter_reference}",
                "item-rest-protect-weapon",
            )
            assert "已加入珍藏" in protected.replies[0].message.content
            repeated = await _dispatch(
                f"珍藏 {starter_reference}",
                "item-rest-protect-weapon-again",
            )
            assert "已经处于珍藏状态" in repeated.replies[0].message.content
            detail = await _dispatch(
                f"查看 {starter_reference}",
                "item-rest-protected-detail",
            )
            assert "珍藏: _是_" in detail.replies[0].message.content
            assert any(
                action.data == f"取消珍藏 {starter_reference}"
                for action in detail.replies[0].message.actions
            )
            protected_page = await _dispatch(
                f"武库 {slot_name}",
                "item-rest-protected-page",
            )
            assert "珍藏" in protected_page.replies[0].message.content
            unprotected = await _dispatch(
                f"取消珍藏 {starter_reference}",
                "item-rest-unprotect-weapon",
            )
            assert "已取消珍藏" in unprotected.replies[0].message.content
            first_page_count = first_page.replies[0].message.content.count(starter_name)
            assert first_page_count == 100, (
                first_page_count,
                first_page.replies[0].message.content[:500],
            )
            assert any(action.label == "下一页" for action in first_page.replies[0].message.actions)
            qq_payload = render_qq_message(
                _asset_page(
                    f"武库·{slot_name}",
                    "equipment",
                    _armory_assets(overview, WEAPON_SLOT_ID),
                    1,
                    overview,
                    page_command=f"武库 {slot_name}",
                )
            )
            assert qq_payload["markdown"]["content"].count("mqqapi://aio/inlinecmd") == 200
            assert sum(
                len(row["buttons"])
                for row in qq_payload["keyboard"]["content"]["rows"]
            ) == 2
            second_page = await _dispatch(f"武库 {slot_name} 2", "item-rest-armory-page-2")
            assert second_page.replies[0].message.content.count(starter_name) == 2
            backpack = await _dispatch("背包", "item-rest-backpack")
            assert "空间: _0/40_" in backpack.replies[0].message.content

            await _assert_rest_window_and_exploration(
                services,
                character.id,
                overview.character_world.world_id,
            )
            _set_resources(services, character.id, health=25, spirit=25)
            rest_result = await _dispatch("休息", "item-rest-start")
            assert "已经开始休息" in rest_result.replies[0].message.content
            assert rest_result.replies[0].message.actions[0].data == "结束休息"
            await _dispatch("结束休息", "item-rest-stop")
        finally:
            restore_game_services(previous)


async def _assert_rest_window_and_exploration(
    services,
    character_id: str,
    world_id: str,
) -> None:
    started_at = datetime.now(TIMEZONE)
    first = services.rest.start(
        "rest-test-start-1",
        character_id,
        logical_time=started_at,
    )
    assert first.status == "started"
    stopped = services.rest.stop(
        "rest-test-stop-1",
        character_id,
        logical_time=started_at + timedelta(minutes=1),
    )
    assert stopped.status == "stopped"
    assert stopped.progress_ratio == 0.5
    assert stopped.recovered_health == 33
    assert stopped.recovered_spirit == 40

    resumed = services.rest.start(
        "rest-test-start-2",
        character_id,
        logical_time=started_at + timedelta(seconds=61),
    )
    assert resumed.status == "started"
    second = services.rest.stop(
        "rest-test-stop-2",
        character_id,
        logical_time=started_at + timedelta(seconds=121),
    )
    assert second.status == "stopped"
    assert 0.5 < second.progress_ratio < 0.53
    assert second.recovered_health < 2
    assert second.recovered_spirit < 2

    region = services.content.exploration_regions.definitions()[0]
    moved = services.world_travel.move(
        character_id,
        services.content.worlds.require_binding_for_display(
            world_id,
            region.location_id,
        ).anchor_id,
        logical_time=started_at + timedelta(seconds=125),
    )
    assert moved.status == "moved"
    active_rest = services.rest.start(
        "rest-test-start-3",
        character_id,
        logical_time=started_at + timedelta(seconds=130),
    )
    assert active_rest.status == "started"
    blocked = services.exploration.start(
        character_id,
        logical_time=started_at + timedelta(seconds=131),
    )
    assert blocked.status == "main_action_occupied"
    services.rest.stop(
        "rest-test-stop-3",
        character_id,
        logical_time=started_at + timedelta(seconds=132),
    )
    exploring = services.exploration.start(
        character_id,
        logical_time=started_at + timedelta(seconds=133),
    )
    assert exploring.status == "started"
    blocked_rest = services.rest.start(
        "rest-test-start-4",
        character_id,
        logical_time=started_at + timedelta(seconds=134),
    )
    assert blocked_rest.status == "exploring"
    services.exploration.stop(
        character_id,
        logical_time=started_at + timedelta(seconds=135),
    )
    _set_resources(services, character_id, health=25, spirit=25)
    final_started_at = started_at + timedelta(seconds=200)
    final_rest = services.rest.start(
        "rest-test-start-final",
        character_id,
        logical_time=final_started_at,
    )
    assert final_rest.status == "started"
    assert services.rest.settle_all_due(
        logical_time=final_started_at + timedelta(minutes=30)
    ) == 1
    completed = services.rest.view(
        character_id,
        logical_time=final_started_at + timedelta(minutes=30),
    )
    assert completed.status == "idle"
    assert completed.character is not None
    assert completed.character.resources[HEALTH_CURRENT] == completed.health_maximum
    assert completed.character.resources[SPIRIT_CURRENT] == completed.spirit_maximum


async def _dispatch(command: str, event_id: str):
    return await dispatch(
        client_id="item-rest-player",
        raw_message=command,
        sender_name="归藏客",
        event_id=event_id,
    )


def _character(services):
    with services.database.unit_of_work(write=False) as uow:
        row = uow.connection.execute(
            "SELECT aggregate_id FROM aggregate_snapshot WHERE aggregate_kind = ?",
            (CHARACTER_AGGREGATE,),
        ).fetchone()
    character = services.characters.load_character(str(row[0]))
    assert character is not None
    return character


def _set_resources(services, character_id: str, *, health: float, spirit: float) -> None:
    snapshots = services.character_creation.snapshots
    logical_time = datetime.now(TIMEZONE)
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


def _grant_weapons(services, character_id: str, quantity: int) -> None:
    snapshots = services.character_creation.snapshots
    logical_time = datetime.now(TIMEZONE)
    with services.database.unit_of_work() as uow:
        inventory = snapshots.require(
            uow,
            INVENTORY_AGGREGATE,
            character_id,
            InventoryState,
        )
        armory_id = next(
            value.id
            for value in inventory.containers.values()
            if value.kind == "container.armory"
        )
        operations = []
        for index in range(quantity):
            asset_id = f"pagination-weapon-{index}"
            state = services.content.catalog.weapons.create_state(
                asset_id=asset_id,
                definition_id=STARTER_WEAPON_ID,
                quality_id=COMMON_QUALITY_ID,
            )
            operations.append(
                GrantInstance(
                    asset_id,
                    services.content.catalog.weapons.require(STARTER_WEAPON_ID).item_definition_id,
                    armory_id,
                    SourceReceipt(
                        f"pagination-receipt-{index}",
                        "source.test_setup",
                        asset_id,
                        logical_time,
                    ),
                    weapon_state_data(state),
                )
            )
        outcome = InventoryEngine(services.content.catalog.items).execute(
            InventoryTransaction(
                "pagination-grant-weapons",
                character_id,
                "inventory.test_setup",
                tuple(operations),
            ),
            state=inventory,
            context=game_operation_context(
                "pagination-grant-weapons",
                logical_time=logical_time,
            ),
        ).unwrap()
        snapshots.update(
            uow,
            INVENTORY_AGGREGATE,
            character_id,
            inventory,
            outcome.state,
            logical_time,
        )
        uow.commit()


if __name__ == "__main__":
    main()
