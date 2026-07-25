"""新玩家从首次降临到再次探险的完整业务闭环验收。"""

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
from game.content import CHARACTER_LEVEL_PROGRESSION_ID, SMALL_HEALTH_MEDICINE_ITEM_ID  # noqa: E402
from game.content.catalog.world import GREEN_CLOUD_PLAIN_ID  # noqa: E402
from game.core.account import ExternalIdentity, IdentityEvidence  # noqa: E402
from game.core.gameplay import (  # noqa: E402
    HEALTH_CURRENT,
    HEALTH_MAXIMUM,
    SPIRIT_CURRENT,
    CharacterState,
)
from game.core.persistence import CHARACTER_AGGREGATE  # noqa: E402
from game.rules.exploration import ExplorationStatus  # noqa: E402
from game.rules.item import asset_reference  # noqa: E402
from launch import config  # noqa: E402
from launch.adapter.local import LocalEventHandler, dispatch  # noqa: E402


TIMEZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 7, 20, 8, 0, tzinfo=TIMEZONE)
CLIENT_ID = "new-player-journey"


def main() -> None:
    asyncio.run(_main())
    print("new player journey tests passed")


async def _main() -> None:
    clock = [NOW]
    for module_name in (
        "game.cmd.角色.service",
        "game.cmd.探险.service",
        "game.cmd.物品.service",
        "game.cmd.休息.service",
        "game.cmd.装配.service",
        "game.cmd.回收",
    ):
        module = import_module(module_name)
        if hasattr(module, "command_time"):
            module.command_time = lambda clock=clock: clock[0]

    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "new-player-journey.db",
            identity_secret="new-player-journey-secret",
        )
        services.character_creation.workflow.id_factory = (
            lambda kind: f"{kind}-new-player-journey"
        )
        services.database.initialize()
        previous = install_game_services(services)
        try:
            await LocalEventHandler.run()

            created = await _dispatch("创建角色 行舟客", "journey-create")
            assert "行纪开篇" in _content(created)
            assert "首次降临" in _content(created)

            current = services.load_current_character(_evidence(clock[0]))
            assert current.status == "ok" and current.character is not None
            character_id = current.character.id
            before = services.load_character_overview(current.character).overview
            assert before is not None
            initial_instance_ids = set(before.inventory.instances)
            initial_experience = before.character.progressions[
                CHARACTER_LEVEL_PROGRESSION_ID
            ].total_experience

            assert "行舟客" in _content(await _dispatch("我的角色", "journey-profile"))
            assert "武库" in _content(await _dispatch("武库", "journey-armory"))
            assert "当前装配" in _content(await _dispatch("装配", "journey-loadout"))
            assert "配装" in _content(await _dispatch("配装 0", "journey-preset"))

            world = services.world_view(before.character_world)
            region_name = world.projector.name(GREEN_CLOUD_PLAIN_ID)
            assert "抵达" in _content(
                await _dispatch(f"前往 {region_name}", "journey-move")
            )
            assert "首次结算" in _content(
                await _dispatch("开始探险", "journey-exploration-start")
            )

            batches = []
            for index in range(1, 9):
                clock[0] = NOW + timedelta(minutes=10 * index)
                settled = services.exploration.settle_due(
                    character_id,
                    logical_time=clock[0],
                )
                batches.extend(settled.batches)
                if settled.state is None or settled.state.status is not ExplorationStatus.RUNNING:
                    break
                overview = services.load_character_overview(current.character).overview
                assert overview is not None
                gained_experience = overview.character.progressions[
                    CHARACTER_LEVEL_PROGRESSION_ID
                ].total_experience > initial_experience
                if gained_experience and _has_processable_drop(
                    services,
                    overview,
                    initial_instance_ids,
                ):
                    break

            assert batches, "新玩家探险没有形成任何结算批次"
            summary = await _dispatch("探险总结", "journey-summary")
            assert "探险" in _content(summary)

            state = services.exploration.load(character_id, logical_time=clock[0]).state
            if state is not None and state.status is ExplorationStatus.RUNNING:
                assert "停止" in _content(
                    await _dispatch("停止探险", "journey-exploration-stop")
                )

            after = services.load_character_overview(current.character).overview
            assert after is not None
            progression = after.character.progressions[CHARACTER_LEVEL_PROGRESSION_ID]
            assert progression.total_experience > initial_experience, (
                progression,
                batches,
            )

            processed = await _process_drop(services, after, initial_instance_ids)
            assert processed, "探险结算没有产生可装配实例或可回收战利品"

            after = services.load_character_overview(current.character).overview
            assert after is not None
            health_maximum = after.character.core_attributes[HEALTH_MAXIMUM]
            if after.character.resources[HEALTH_CURRENT] >= health_maximum:
                _set_resources(
                    services,
                    character_id,
                    health=max(1, health_maximum / 2),
                    spirit=after.character.resources[SPIRIT_CURRENT],
                    logical_time=clock[0],
                )
                after = services.load_character_overview(current.character).overview
                assert after is not None

            medicine = next(
                stack
                for stack in after.inventory.stacks.values()
                if stack.definition_id == SMALL_HEALTH_MEDICINE_ITEM_ID
            )
            medicine_ref = after.inventory.reference_number(medicine.id)
            used = await _dispatch(f"使用 I{medicine_ref} 1", "journey-medicine")
            assert "消耗: _1_" in _content(used)

            recovered = services.load_character_overview(current.character).overview
            assert recovered is not None
            if recovered.character.resources[HEALTH_CURRENT] >= health_maximum:
                _set_resources(
                    services,
                    character_id,
                    health=max(1, health_maximum / 2),
                    spirit=recovered.character.resources[SPIRIT_CURRENT],
                    logical_time=clock[0],
                )

            assert "已经开始休息" in _content(
                await _dispatch("休息", "journey-rest-start")
            )
            clock[0] += timedelta(minutes=2)
            rest_content = _content(
                await _dispatch("结束休息", "journey-rest-stop")
            )
            assert "恢复" in rest_content or "结束" in rest_content

            restarted = await _dispatch("开始探险", "journey-exploration-restart")
            assert "首次结算" in _content(restarted)
        finally:
            restore_game_services(previous)


async def _process_drop(services, overview, initial_instance_ids: set[str]) -> bool:
    for instance in overview.inventory.instances.values():
        if instance.id in initial_instance_ids:
            continue
        definition = services.content.catalog.items.require(instance.definition_id)
        if definition.tags.has("item.weapon") or definition.tags.has("item.equipment"):
            reference = asset_reference(
                overview.inventory,
                instance,
                services.content.catalog.items,
            )
            result = await _dispatch(f"装备 {reference}", "journey-equip-drop")
            assert "装配" in _content(result) or "装备" in _content(result)
            return True

    trophies = [
        stack
        for stack in overview.inventory.stacks.values()
        if services.content.catalog.items.require(stack.definition_id).tags.has("item.trophy")
    ]
    if trophies:
        result = await _dispatch("回收战利品", "journey-recycle-drop")
        assert "回收" in _content(result)
        return True
    return False


def _has_processable_drop(services, overview, initial_instance_ids: set[str]) -> bool:
    if any(instance.id not in initial_instance_ids for instance in overview.inventory.instances.values()):
        return True
    return any(
        services.content.catalog.items.require(stack.definition_id).tags.has("item.trophy")
        for stack in overview.inventory.stacks.values()
    )


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


def _evidence(logical_time: datetime) -> IdentityEvidence:
    return IdentityEvidence(
        "new-player-journey-evidence",
        ExternalIdentity(
            "platform.local",
            config.project.name,
            "identity.local_user",
            "",
            CLIENT_ID,
        ),
        (),
        "message.local",
        logical_time,
    )


async def _dispatch(command: str, event_id: str):
    return await dispatch(
        client_id=CLIENT_ID,
        raw_message=command,
        sender_name="行舟客",
        event_id=event_id,
    )


def _content(result) -> str:
    assert result.matched and result.matched_count == 1, result
    assert len(result.replies) == 1, result
    content = result.replies[0].message.content
    assert content.strip()
    return content


if __name__ == "__main__":
    main()
