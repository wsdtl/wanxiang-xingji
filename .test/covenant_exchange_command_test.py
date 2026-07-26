"""归航兑换与套装图纸通过本地驱动器的最终回复验收。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / ".test") not in sys.path:
    sys.path.insert(0, str(ROOT / ".test"))

from covenant_exchange_test import _grant_stack, _inventory  # noqa: E402
from game.app import build_game_services, install_game_services, restore_game_services  # noqa: E402
from game.content.catalog.item import EXCHANGE_MATERIAL_ITEM_ID  # noqa: E402
from game.core.persistence import CHARACTER_AGGREGATE  # noqa: E402
from game.rules.item import asset_reference  # noqa: E402
from launch.adapter.local import LocalEventHandler, dispatch  # noqa: E402
from launch.adapter.qq import QqEventHandler  # noqa: E402
from launch.message_events import (  # noqa: E402
    subscribe_message_events,
    unsubscribe_message_events,
)


def main() -> None:
    asyncio.run(_main())
    print("covenant exchange command tests passed")


async def _main() -> None:
    import_module("game.cmd.归航兑换")
    import_module("game.cmd.构筑试炼")
    import_module("game.cmd.物品")
    import_module("game.cmd.装配")
    import_module("game.cmd.角色")
    for command in ("归航兑换", "归航兑换记录"):
        assert len(LocalEventHandler.exact_rules[command]) == 1
        assert len(QqEventHandler.exact_rules[command]) == 1
    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "exchange-command.db",
            identity_secret="exchange-command-test-secret",
        )
        services.database.initialize()
        previous = install_game_services(services)
        events = []
        listener = events.append
        subscribe_message_events(listener)
        try:
            await LocalEventHandler.run()
            await _dispatch("exchange-user", "创建角色 归航测试", "exchange-create")
            character = _character(services)
            _grant_stack(
                services,
                character.id,
                "stack:exchange-material",
                EXCHANGE_MATERIAL_ITEM_ID,
                100,
                "container.special",
            )
            home = await _dispatch("exchange-user", "归航兑换", "exchange-home")
            assert "定相尘" in home.replies[0].message.content
            assert "套装图纸" in home.replies[0].message.content
            assert not home.replies[0].message.actions
            page = await _dispatch(
                "exchange-user",
                "归航兑换 套装",
                "exchange-page",
            )
            assert "归航兑换·套装" in page.replies[0].message.content
            assert "页码: _1/1_" in page.replies[0].message.content
            assert f"总计: _{len(services.content.catalog.equipment.sets.ids())}_" in page.replies[0].message.content
            assert not page.replies[0].message.actions
            set_id = services.content.catalog.equipment.sets.ids()[0]
            overview = services.load_character_overview(character).overview
            assert overview is not None
            view = services.world_view(overview.character_world)
            set_name = view.projector.name(set_id)
            page_links = {
                (value.label, value.data)
                for value in _outgoing(events, "exchange-page").interactions
                if value.kind == "command_link"
            }
            assert (set_name, f"归航兑换 {set_id}") in page_links
            assert ("套装效果", f"特效 {set_name}") in page_links
            completed = await _dispatch(
                "exchange-user",
                f"归航兑换 {set_id}",
                "exchange-direct",
            )
            assert "归航兑换·完成" in completed.replies[0].message.content
            assert completed.replies[0].message.actions[1].data == "归航兑换 套装"
            assert all("确认" not in action.label for action in completed.replies[0].message.actions)

            inventory = _inventory(services, character.id)
            blueprint = next(
                stack
                for stack in inventory.stacks.values()
                if services.content.catalog.items.require(stack.definition_id).tags.has("item.blueprint")
            )
            reference = asset_reference(inventory, blueprint, services.content.catalog.items)
            used = await _dispatch(
                "exchange-user",
                f"使用 {reference}",
                "exchange-use-blueprint",
            )
            assert "套装图纸" in used.replies[0].message.content
            assert "部位、底座、品阶、词条" in used.replies[0].message.content
            used_links = {
                (value.label, value.data)
                for value in _outgoing(events, "exchange-use-blueprint").interactions
                if value.kind == "command_link"
            }
            assert (set_name, f"特效 {set_name}") in used_links
            inventory = _inventory(services, character.id)
            equipment = next(
                instance
                for instance in inventory.instances.values()
                if services.content.catalog.items.require(instance.definition_id).tags.has(
                    "item.equipment"
                )
            )
            equipment_reference = asset_reference(
                inventory,
                equipment,
                services.content.catalog.items,
            )
            equipped = await _dispatch(
                "exchange-user",
                f"装备 {equipment_reference}",
                "exchange-equip-generated",
            )
            assert "当前装配" in equipped.replies[0].message.content
            overview = services.load_character_overview(character).overview
            assert overview is not None
            assert equipment.id in overview.loadout.equipment_asset_ids

            trial = await _dispatch(
                "exchange-user",
                "开始试炼 单体",
                "exchange-build-trial",
            )
            assert "构筑试炼·单体" in trial.replies[0].message.content
            assert "查看完整战报" in trial.replies[0].message.content
            with services.database.unit_of_work(write=False) as uow:
                share_id = uow.connection.execute(
                    "SELECT share_id FROM battle_report ORDER BY created_at DESC LIMIT 1"
                ).fetchone()[0]
            report = services.battle_reports.load_public(
                str(share_id),
                logical_time=datetime.now(timezone.utc),
            )
            assert report is not None and report.segments
            segment = report.segments[0]
            assert segment.transitions and segment.final_participants
            assert any(
                combatant.label == character.name
                for combatant in segment.combatants
            )
            history = await _dispatch(
                "exchange-user",
                "归航兑换记录",
                "exchange-history",
            )
            assert "归航兑换记录" in history.replies[0].message.content
            assert "定相尘" in history.replies[0].message.content
            history_links = {
                (value.label, value.data)
                for value in _outgoing(events, "exchange-history").interactions
                if value.kind == "command_link"
            }
            assert (set_name, f"特效 {set_name}") in history_links
        finally:
            unsubscribe_message_events(listener)
            restore_game_services(previous)


async def _dispatch(client_id: str, raw_message: str, event_id: str):
    return await dispatch(
        client_id=client_id,
        raw_message=raw_message,
        sender_name=client_id,
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


def _outgoing(events, request_id: str):
    return next(
        value
        for value in reversed(events)
        if value.direction == "outgoing" and value.request_id == request_id
    )


if __name__ == "__main__":
    main()
