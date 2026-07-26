"""自动用药、铭刻入口、原名偏好和装配命令的本地驱动测试。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
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
    TAIXUAN_WORLD_ID,
    DIMENSION_SHIFT_ITEM_ID,
    INSCRIPTION_FEATHER_ITEM_ID,
    MAGIC_WORLD_ID,
    PRIMARY_CURRENCY_ID,
)
from game.content.catalog.character import REST_ACTION_ID  # noqa: E402
from game.core.gameplay import (  # noqa: E402
    INSCRIPTION_MEDIUM_DATA_KEY,
    GrantInstance,
    GrantStack,
    HEALTH_CURRENT,
    HEALTH_MAXIMUM,
    SPIRIT_CURRENT,
    SPIRIT_MAXIMUM,
    CharacterState,
    InscriptionMediumData,
    InventoryEngine,
    InventoryState,
    InventoryTransaction,
    SourceReceipt,
    WEAPON_SLOT_ID,
    equipment_state_data,
)
from game.core.persistence import CHARACTER_AGGREGATE, INVENTORY_AGGREGATE  # noqa: E402
from game.rules import (  # noqa: E402
    EquipmentGenerationRequest,
    EquipmentInstanceGenerator,
    game_operation_context,
)
from game.features.world_travel import WorldLocationIntent  # noqa: E402
from game.cmd import 角色 as character_component  # noqa: E402,F401
from game.cmd import 跃迁 as dimension_component  # noqa: E402,F401
from game.cmd import 休息 as rest_component  # noqa: E402,F401
from game.cmd import 提醒 as reminder_component  # noqa: E402,F401
from game.cmd import 铭刻 as inscription_component  # noqa: E402,F401
from game.cmd import 装配 as loadout_component  # noqa: E402,F401
from game.cmd import 物品 as item_component  # noqa: E402,F401
from game.cmd import 伙伴 as companion_component  # noqa: E402,F401
from game.cmd import 探险 as exploration_component  # noqa: E402,F401
from launch.adapter.local import LocalEventHandler, dispatch  # noqa: E402
from launch.adapter.qq import QqEventHandler  # noqa: E402


def main() -> None:
    asyncio.run(_main())
    print("small command component tests passed")


async def _main() -> None:
    for command in (
        "自动用药",
        "自动休整",
        "铭刻",
        "铭刻能力",
        "铭刻原名",
        "inscription_confirm_asset",
        "inscription_confirm_ability",
        "装配",
        "装备",
        "卸下",
        "配装",
        "纳戒",
        "跃迁",
    ):
        assert len(LocalEventHandler.exact_rules[command]) == 1
        assert len(QqEventHandler.exact_rules[command]) == 1

    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "small-command.db",
            identity_secret="small-command-test-secret",
        )
        services.database.initialize()
        previous = install_game_services(services)
        try:
            await LocalEventHandler.run()
            await dispatch(
                client_id="small-command-player",
                raw_message="创建角色 试剑客",
                sender_name="试剑客",
                event_id="small-command-create",
            )

            with services.database.unit_of_work(write=False) as uow:
                row = uow.connection.execute(
                    "SELECT aggregate_id FROM aggregate_snapshot "
                    "WHERE aggregate_kind = ?",
                    (CHARACTER_AGGREGATE,),
                ).fetchone()
            character = services.characters.load_character(str(row[0]))
            assert character is not None
            initial_overview = services.load_character_overview(character).overview
            assert initial_overview is not None
            initial_view = services.world_views.require(initial_overview.character_world.world_id)
            starter_weapon_id = initial_overview.loadout.slots[WEAPON_SLOT_ID]
            starter_weapon_ref = initial_overview.inventory.reference_number(starter_weapon_id)
            starter_weapon_detail = await dispatch(
                client_id="small-command-player",
                raw_message=f"查看 W{starter_weapon_ref}",
                sender_name="试剑客",
                event_id="small-command-starter-weapon-detail",
            )
            starter_weapon_text = starter_weapon_detail.replies[0].message.content
            assert "来源" in starter_weapon_text
            assert "初始获得" in starter_weapon_text
            assert "获得" in starter_weapon_text
            initial_world = initial_overview.world
            target_world_id = (
                MAGIC_WORLD_ID
                if initial_overview.character_world.world_id == TAIXUAN_WORLD_ID
                else TAIXUAN_WORLD_ID
            )
            target_view = services.world_views.require(target_world_id)
            worlds = await dispatch(
                client_id="small-command-player",
                raw_message="跃迁",
                sender_name="试剑客",
                event_id="small-command-worlds",
            )
            assert "太玄界" in worlds.replies[0].message.content
            assert "魔法世界" in worlds.replies[0].message.content
            assert not worlds.replies[0].message.actions
            target_command = f"跃迁 {target_world_id}"
            missing_shift = await dispatch(
                client_id="small-command-player",
                raw_message=target_command,
                sender_name="试剑客",
                event_id="small-command-shift-missing-item",
            )
            assert "纳戒中没有可用的跃迁凭证" in missing_shift.replies[0].message.content
            assert missing_shift.replies[0].message.actions[0].data == "纳戒"
            unchanged = services.load_character_overview(character).overview
            assert unchanged is not None
            assert unchanged.character_world == initial_overview.character_world
            assert unchanged.world == initial_world
            _grant_dimension_shift_items(services, character.id, 2)
            initial_overview = services.load_character_overview(character).overview
            assert initial_overview is not None
            initial_inventory = initial_overview.inventory
            shift_stack = next(
                value
                for value in initial_inventory.stacks.values()
                if value.definition_id == DIMENSION_SHIFT_ITEM_ID
            )
            shift_reference = initial_inventory.reference_number(shift_stack.id)
            shift_detail = await dispatch(
                client_id="small-command-player",
                raw_message=f"查看 {shift_reference}",
                sender_name="试剑客",
                event_id="small-command-shift-item-detail",
            )
            assert shift_detail.replies[0].message.actions[0].data == "跃迁"
            manual_use = await dispatch(
                client_id="small-command-player",
                raw_message=f"使用 {shift_reference}",
                sender_name="试剑客",
                event_id="small-command-shift-item-manual-use",
            )
            assert "成功跃迁时自动消耗" in manual_use.replies[0].message.content
            assert _stack_quantity(
                services.load_character_overview(character).overview.inventory,
                DIMENSION_SHIFT_ITEM_ID,
            ) == 2
            old_armory = await dispatch(
                client_id="small-command-player",
                raw_message="武库",
                sender_name="试剑客",
                event_id="small-command-old-armory",
            )
            old_weapon_command = f"武库 {WEAPON_SLOT_ID}"
            assert target_view.projector.name(WEAPON_SLOT_ID) not in old_armory.replies[0].message.content
            assert initial_view.projector.name(WEAPON_SLOT_ID) in old_armory.replies[0].message.content
            old_people = await dispatch(
                client_id="small-command-player",
                raw_message="人物",
                sender_name="试剑客",
                event_id="small-command-old-people",
            )
            assert not old_people.replies[0].message.actions
            person_location = services.content.companions.people_for_world(
                initial_overview.character_world.world_id
            )[0].location_id
            person_binding = services.content.worlds.require_binding_for_display(
                initial_overview.character_world.world_id,
                person_location,
            )
            person_anchor = person_binding.anchor_id
            old_location_command = WorldLocationIntent(
                initial_overview.character_world.world_id,
                person_anchor,
                person_binding.function_id,
                person_binding.version,
            ).command()
            stale_version = services.world_travel.move(
                character.id,
                person_anchor,
                logical_time=datetime.now(ZoneInfo("Asia/Shanghai")),
                intent=WorldLocationIntent(
                    initial_overview.character_world.world_id,
                    person_anchor,
                    "location.function.companion_person",
                    999,
                ),
            )
            assert stale_version.status == "stale_binding"
            shifted_world = await dispatch(
                client_id="small-command-player",
                raw_message=target_command,
                sender_name="试剑客",
                event_id="small-command-shift-world",
            )
            assert "跃迁" in shifted_world.replies[0].message.content
            assert "消耗" in shifted_world.replies[0].message.content
            assert target_view.skin.name in shifted_world.replies[0].message.content
            shifted_overview = services.load_character_overview(character).overview
            assert shifted_overview is not None
            assert shifted_overview.inventory.containers == initial_inventory.containers
            assert shifted_overview.inventory.instances == initial_inventory.instances
            assert _stack_quantity(shifted_overview.inventory, DIMENSION_SHIFT_ITEM_ID) == (
                _stack_quantity(initial_inventory, DIMENSION_SHIFT_ITEM_ID) - 1
            )
            assert shifted_overview.world.revision == initial_world.revision + 1
            assert shifted_overview.character_world.world_id == target_world_id
            initial_presence = next(
                value
                for value in initial_world.presences.values()
                if value.owner_id == character.id
            )
            shifted_presence = next(
                value
                for value in shifted_overview.world.presences.values()
                if value.owner_id == character.id
            )
            assert shifted_presence.position.space_id != initial_presence.position.space_id
            already_there = services.shift_character_world(
                character.id,
                target_world_id,
                logical_time=datetime.now(ZoneInfo("Asia/Shanghai")),
            )
            assert already_there.status == "already_there"
            after_idempotent = services.load_character_overview(character).overview
            assert after_idempotent is not None
            assert after_idempotent.world == shifted_overview.world
            assert _stack_quantity(
                services.load_character_overview(character).overview.inventory,
                DIMENSION_SHIFT_ITEM_ID,
            ) == 1
            old_button_after_shift = await dispatch(
                client_id="small-command-player",
                raw_message=old_weapon_command,
                sender_name="试剑客",
                event_id="small-command-old-button-after-shift",
            )
            assert (
                f"武库·{target_view.projector.name(WEAPON_SLOT_ID)}"
                in old_button_after_shift.replies[0].message.content
            )
            stale_location = await dispatch(
                client_id="small-command-player",
                raw_message=old_location_command,
                sender_name="试剑客",
                event_id="small-command-stale-location",
            )
            assert "地点入口已经失效" in stale_location.replies[0].message.content
            assert stale_location.replies[0].message.actions[0].data == "探险"

            _injure_character(services, character.id)
            await dispatch(
                client_id="small-command-player",
                raw_message="休息",
                sender_name="试剑客",
                event_id="small-command-rest-start",
            )
            original_view = services.world_views.require(initial_overview.character_world.world_id)
            blocked_shift = await dispatch(
                client_id="small-command-player",
                raw_message=f"跃迁 {original_view.skin.name}",
                sender_name="试剑客",
                event_id="small-command-shift-blocked",
            )
            assert "当前正在进行主要行动" in blocked_shift.replies[0].message.content, (
                blocked_shift.replies[0].message.content
            )
            assert _stack_quantity(
                services.load_character_overview(character).overview.inventory,
                DIMENSION_SHIFT_ITEM_ID,
            ) == 1
            await dispatch(
                client_id="small-command-player",
                raw_message="结束休息",
                sender_name="试剑客",
                event_id="small-command-rest-stop",
            )
            region = services.content.exploration_regions.definitions()[0]
            moved = services.world_travel.move(
                character.id,
                services.content.worlds.require_binding_for_display(
                    shifted_overview.character_world.world_id,
                    region.location_id,
                ).anchor_id,
                logical_time=datetime.now(ZoneInfo("Asia/Shanghai")),
            )
            assert moved.status in {"moved", "already_there"}
            started = services.exploration.start(
                character.id,
                logical_time=datetime.now(ZoneInfo("Asia/Shanghai")),
            )
            assert started.status == "started"
            exploration_blocked = services.shift_character_world(
                character.id,
                original_view.world.id,
                logical_time=datetime.now(ZoneInfo("Asia/Shanghai")),
            )
            assert exploration_blocked.status == "main_action_occupied"
            services.exploration.stop(
                character.id,
                logical_time=datetime.now(ZoneInfo("Asia/Shanghai")),
            )

            auto_medicine = await dispatch(
                client_id="small-command-player",
                raw_message="自动用药",
                sender_name="试剑客",
                event_id="small-command-auto-status",
            )
            assert "当前状态: _开启_" in auto_medicine.replies[0].message.content
            assert {action.label for action in auto_medicine.replies[0].message.actions} == {"关闭"}

            disabled = await dispatch(
                client_id="small-command-player",
                raw_message="自动用药 关闭",
                sender_name="试剑客",
                event_id="small-command-auto-disable",
            )
            assert "当前状态: _关闭_" in disabled.replies[0].message.content
            assert {action.label for action in disabled.replies[0].message.actions} == {"开启"}

            auto_rest = await dispatch(
                client_id="small-command-player",
                raw_message="自动休整",
                sender_name="试剑客",
                event_id="small-command-auto-rest-status",
            )
            assert "当前状态: _开启_" in auto_rest.replies[0].message.content
            assert {action.label for action in auto_rest.replies[0].message.actions} == {"关闭"}

            inscription = await dispatch(
                client_id="small-command-player",
                raw_message="铭刻",
                sender_name="试剑客",
                event_id="small-command-inscription",
            )
            assert (
                f"暂无{target_view.projector.name(INSCRIPTION_FEATHER_ITEM_ID)}"
                in inscription.replies[0].message.content
            )
            assert "世界:" in inscription.replies[0].message.content

            original = await dispatch(
                client_id="small-command-player",
                raw_message="铭刻原名 关闭",
                sender_name="试剑客",
                event_id="small-command-original-disable",
            )
            assert "当前状态: _关闭_" in original.replies[0].message.content
            assert {action.label for action in original.replies[0].message.actions} == {"开启"}

            loadout = await dispatch(
                client_id="small-command-player",
                raw_message="装配",
                sender_name="试剑客",
                event_id="small-command-loadout",
            )
            assert "当前装配" in loadout.replies[0].message.content
            assert "世界:" in loadout.replies[0].message.content
            assert target_view.projector.name(WEAPON_SLOT_ID) in loadout.replies[0].message.content

            preset_list = await dispatch(
                client_id="small-command-player",
                raw_message="配装",
                sender_name="试剑客",
                event_id="small-command-presets",
            )
            assert "配装 0" in preset_list.replies[0].message.content
            assert "配装 5" in preset_list.replies[0].message.content
            assert "世界:" in preset_list.replies[0].message.content

            switched = await dispatch(
                client_id="small-command-player",
                raw_message="配装 1",
                sender_name="试剑客",
                event_id="small-command-switch",
            )
            assert "当前配装: _1_" in switched.replies[0].message.content

            (
                equipment_ref,
                candidate_ref,
                inferior_ref,
                feather_ref,
                slot_name,
            ) = _grant_test_assets(services, character.id)

            nacre_after_grant = await dispatch(
                client_id="small-command-player",
                raw_message="纳戒",
                sender_name="试剑客",
                event_id="small-command-nacre-after-grant",
            )
            assert "旧桥挑灯客遗羽" not in nacre_after_grant.replies[0].message.content
            inscription_after_grant = await dispatch(
                client_id="small-command-player",
                raw_message="铭刻",
                sender_name="试剑客",
                event_id="small-command-inscription-after-grant",
            )
            assert "旧桥挑灯客遗羽" in inscription_after_grant.replies[0].message.content

            equipped = await dispatch(
                client_id="small-command-player",
                raw_message=f"装备 E{equipment_ref}",
                sender_name="试剑客",
                event_id="small-command-equip",
            )
            assert f"E{equipment_ref}" in equipped.replies[0].message.content
            assert f"E{candidate_ref}" in equipped.replies[0].message.content
            assert f"E{inferior_ref}" not in equipped.replies[0].message.content

            comparison = await dispatch(
                client_id="small-command-player",
                raw_message=f"查看 E{candidate_ref}",
                sender_name="试剑客",
                event_id="small-command-gear-comparison",
            )
            comparison_message = comparison.replies[0].message
            assert "同槽对比" in comparison_message.content
            assert "候选评分" in comparison_message.content
            assert "当前评分" in comparison_message.content
            assert "来源" in comparison_message.content
            assert "探险" in comparison_message.content
            assert "获得" in comparison_message.content
            assert "2026-07-21 09:10" in comparison_message.content
            assert "exploration-test-session" not in comparison_message.content
            assert "套装进度" in comparison_message.content
            assert "1/4 -> 0/4" in comparison_message.content
            assert "0/4 -> 1/4" in comparison_message.content
            assert {value.label for value in comparison_message.actions} >= {
                "装备",
                "回收",
            }
            recycle = next(
                value
                for value in comparison_message.actions
                if value.label == "回收"
            )
            assert recycle.data == f"回收 E{candidate_ref}"
            assert recycle.behavior == "callback"

            unequipped = await dispatch(
                client_id="small-command-player",
                raw_message=f"卸下 {slot_name}",
                sender_name="试剑客",
                event_id="small-command-unequip",
            )
            assert "当前装配" in unequipped.replies[0].message.content

            completed = await dispatch(
                client_id="small-command-player",
                raw_message=f"铭刻 I{feather_ref} E{equipment_ref} 照夜",
                sender_name="试剑客",
                event_id="small-command-inscription-direct",
            )
            assert "铭刻完成" in completed.replies[0].message.content
            assert "照夜" in completed.replies[0].message.content
            assert "世界:" in completed.replies[0].message.content
            assert not completed.replies[0].message.actions

            overview = services.load_character_overview(character).overview
            assert overview is not None
            equipment_asset_id = overview.inventory.asset_id_for_reference(equipment_ref)
            assert equipment_asset_id in overview.inventory.instances
            assert all(
                value.definition_id != INSCRIPTION_FEATHER_ITEM_ID
                for value in overview.inventory.instances.values()
            )

            magic_view = services.world_views.require(MAGIC_WORLD_ID)
            await dispatch(
                client_id="small-command-player",
                raw_message=f"跃迁 {MAGIC_WORLD_ID}",
                sender_name="试剑客",
                event_id="small-command-final-magic-shift",
            )
            magic_profile = await dispatch(
                client_id="small-command-player",
                raw_message="我的角色",
                sender_name="试剑客",
                event_id="small-command-magic-profile",
            )
            profile_text = magic_profile.replies[0].message.content
            for definition_id in (
                CHARACTER_LEVEL_PROGRESSION_ID,
                HEALTH_CURRENT,
                SPIRIT_CURRENT,
                PRIMARY_CURRENCY_ID,
            ):
                expected = magic_view.projector.name(definition_id).removeprefix("当前")
                assert expected in profile_text
            magic_combat = await dispatch(
                client_id="small-command-player",
                raw_message="战斗面板",
                sender_name="试剑客",
                event_id="small-command-magic-combat",
            )
            combat_text = magic_combat.replies[0].message.content
            for definition_id in (HEALTH_MAXIMUM, SPIRIT_MAXIMUM):
                assert magic_view.projector.name(definition_id) in combat_text
            magic_overview = services.load_character_overview(character).overview
            assert magic_overview is not None
            presence = next(
                value
                for value in magic_overview.world.presences.values()
                if value.owner_id == character.id
            )
            anchor_id = services.content.worlds.anchor_at(
                magic_overview.character_world.world_id,
                presence.position,
            )
            assert anchor_id is not None
            location = services.content.worlds.resolve(
                magic_overview.character_world.world_id,
                anchor_id,
            )
            assert (
                magic_view.projector.name(location.display_id)
                in profile_text
            )
            magic_armory = await dispatch(
                client_id="small-command-player",
                raw_message="武库",
                sender_name="试剑客",
                event_id="small-command-magic-armory",
            )
            assert magic_view.projector.name(WEAPON_SLOT_ID) in magic_armory.replies[0].message.content
            magic_rest = await dispatch(
                client_id="small-command-player",
                raw_message="休息",
                sender_name="试剑客",
                event_id="small-command-magic-rest",
            )
            assert magic_view.projector.name(REST_ACTION_ID) in magic_rest.replies[0].message.content
        finally:
            restore_game_services(previous)


def _grant_test_assets(services, character_id: str) -> tuple[int, int, int, int, str]:
    logical_time = datetime(2026, 7, 21, 9, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    snapshots = services.character_creation.snapshots
    equipment_definition = next(iter(services.content.catalog.equipment.definitions))
    set_ids = tuple(services.content.catalog.equipment.sets.ids())
    set_id = set_ids[0]
    candidate_set_id = set_ids[1]
    generator = EquipmentInstanceGenerator(
        services.content.catalog.equipment,
        services.content.catalog.itemization_engine,
        set_mark_chance=0,
    )
    generated_values = []
    for index in range(24):
        operation_id = f"small-command-equipment-generation-{index}"
        generated_values.append(
            generator.generate(
                EquipmentGenerationRequest(
                    operation_id,
                    f"equipment-command-{index + 1}",
                    equipment_definition.id,
                    services.content.catalog.report.content_fingerprint,
                ),
                context=game_operation_context(
                    operation_id,
                    logical_time=logical_time,
                ),
            )
        )
    by_score = {
        value.state.roll.intrinsic_value.total: value
        for value in generated_values
        if value.state.roll is not None
    }
    scores = sorted(by_score)
    assert len(scores) >= 3
    inferior = by_score[scores[0]]
    generated = by_score[scores[len(scores) // 2]]
    candidate = by_score[scores[-1]]
    generated = replace(generated, state=replace(generated.state, set_id=set_id))
    candidate = replace(candidate, state=replace(candidate.state, set_id=candidate_set_id))
    receipt = SourceReceipt(
        "small-command-assets-receipt",
        "source.exploration",
        "exploration-test-session",
        logical_time,
    )
    with services.database.unit_of_work() as uow:
        inventory = snapshots.require(
            uow,
            INVENTORY_AGGREGATE,
            character_id,
            InventoryState,
        )
        inscription = next(
            value.id
            for value in inventory.containers.values()
            if value.kind == "container.inscription"
        )
        armory = next(
            value.id
            for value in inventory.containers.values()
            if value.kind == "container.armory"
        )
        outcome = InventoryEngine(services.content.catalog.items).execute(
            InventoryTransaction(
                "small-command-grant-assets",
                character_id,
                "inventory.test_setup",
                (
                    GrantInstance(
                        generated.state.asset_id,
                        equipment_definition.item_definition_id,
                        armory,
                        receipt,
                        equipment_state_data(generated.state),
                    ),
                    GrantInstance(
                        candidate.state.asset_id,
                        equipment_definition.item_definition_id,
                        armory,
                        receipt,
                        equipment_state_data(candidate.state),
                    ),
                    GrantInstance(
                        inferior.state.asset_id,
                        equipment_definition.item_definition_id,
                        armory,
                        receipt,
                        equipment_state_data(inferior.state),
                    ),
                    GrantInstance(
                        "feather-command-1",
                        INSCRIPTION_FEATHER_ITEM_ID,
                        inscription,
                        receipt,
                        {
                            INSCRIPTION_MEDIUM_DATA_KEY: InscriptionMediumData(
                                "旧桥挑灯客遗羽",
                                "灯穗落下一枚旧羽，微光随新名散去。",
                            )
                        },
                    ),
                ),
            ),
            state=inventory,
            context=game_operation_context(
                "small-command-grant-assets",
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
    equipment_ref = outcome.state.reference_number(generated.state.asset_id)
    candidate_ref = outcome.state.reference_number(candidate.state.asset_id)
    inferior_ref = outcome.state.reference_number(inferior.state.asset_id)
    feather_ref = outcome.state.reference_number("feather-command-1")
    character = services.characters.load_character(character_id)
    assert character is not None
    overview = services.load_character_overview(character).overview
    assert overview is not None
    slot_name = services.world_view(overview.character_world).projector.name(
        equipment_definition.slot_id
    )
    return equipment_ref, candidate_ref, inferior_ref, feather_ref, slot_name


def _injure_character(services, character_id: str) -> None:
    snapshots = services.character_creation.snapshots
    logical_time = datetime.now(ZoneInfo("Asia/Shanghai"))
    with services.database.unit_of_work() as uow:
        character = snapshots.require(
            uow,
            CHARACTER_AGGREGATE,
            character_id,
            CharacterState,
        )
        resources = dict(character.resources)
        resources[HEALTH_CURRENT] = max(1, resources[HEALTH_CURRENT] - 10)
        updated = replace(
            character,
            resources=resources,
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


def _grant_dimension_shift_items(services, character_id: str, quantity: int) -> None:
    snapshots = services.character_creation.snapshots
    logical_time = datetime.now(ZoneInfo("Asia/Shanghai"))
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
        outcome = services.inventory_engine.execute(
            InventoryTransaction(
                "small-command-grant-dimension-shift-items",
                character_id,
                "inventory.test_setup",
                (
                    GrantStack(
                        "stack:dimension-shift",
                        DIMENSION_SHIFT_ITEM_ID,
                        special,
                        quantity,
                        SourceReceipt(
                            "receipt:dimension-shift",
                            "source.test",
                            character_id,
                            logical_time,
                        ),
                    ),
                ),
            ),
            state=inventory,
            context=game_operation_context(
                "small-command-grant-dimension-shift-items",
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


def _stack_quantity(inventory: InventoryState, definition_id: str) -> int:
    return sum(
        value.quantity
        for value in inventory.stacks.values()
        if value.definition_id == definition_id
    )


if __name__ == "__main__":
    main()
