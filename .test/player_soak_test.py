"""多名玩家在同一数据库连续游玩的命令级耐久测试。"""

from __future__ import annotations

import asyncio
from collections import Counter
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
from game.cmd import 休息 as rest_component  # noqa: E402,F401
from game.cmd import 切磋 as sparring_component  # noqa: E402,F401
from game.cmd import 回收 as recycle_component  # noqa: E402,F401
from game.cmd import 地图 as map_component  # noqa: E402,F401
from game.cmd import 探险 as exploration_component  # noqa: E402,F401
from game.cmd import 构筑试炼 as build_trial_component  # noqa: E402,F401
from game.cmd import 物品 as item_component  # noqa: E402,F401
from game.cmd import 角色 as character_component  # noqa: E402,F401
from game.cmd import 组队 as party_component  # noqa: E402,F401
from game.cmd import 装配 as loadout_component  # noqa: E402,F401
from game.content import CHARACTER_LEVEL_PROGRESSION_ID  # noqa: E402
from game.content.catalog.world import GREEN_CLOUD_PLAIN_ID  # noqa: E402
from game.core.account import ExternalIdentity, IdentityEvidence  # noqa: E402
from game.core.gameplay import HEALTH_CURRENT, HEALTH_MAXIMUM, SPIRIT_CURRENT  # noqa: E402
from game.rules.exploration import ExplorationStatus  # noqa: E402
from game.rules.item import asset_reference  # noqa: E402
from launch import config  # noqa: E402
from launch.adapter.local import LocalEventHandler, dispatch  # noqa: E402


TIMEZONE = ZoneInfo("Asia/Shanghai")
STARTED_AT = datetime(2026, 7, 22, 8, 0, tzinfo=TIMEZONE)
PERSONAS = (
    ("soak-player-a", "长测甲"),
    ("soak-player-b", "长测乙"),
    ("soak-player-c", "长测丙"),
    ("soak-player-d", "长测丁"),
)


def main() -> None:
    stats = asyncio.run(_main())
    print("player soak tests passed")
    print("soak stats:", ", ".join(f"{key}={value}" for key, value in sorted(stats.items())))


async def _main() -> Counter:
    clock = [STARTED_AT]
    for module_name in (
        "game.cmd.休息.service",
        "game.cmd.切磋.service",
        "game.cmd.地图.service",
        "game.cmd.探险.service",
        "game.cmd.构筑试炼.service",
        "game.cmd.物品.service",
        "game.cmd.角色.service",
        "game.cmd.组队.shared",
    ):
        module = import_module(module_name)
        if hasattr(module, "command_time"):
            module.command_time = lambda clock=clock: clock[0]

    with TemporaryDirectory() as directory:
        path = Path(directory) / "player-soak.db"
        services = build_game_services(
            database_path=path,
            identity_secret="player-soak-test-secret",
        )
        services.database.initialize()
        previous = install_game_services(services)
        stats: Counter = Counter()
        try:
            await LocalEventHandler.run()
            characters = {}
            initial_instance_ids = {}
            attempted_equipment = {client_id: set() for client_id, _ in PERSONAS}
            for index, (client_id, name) in enumerate(PERSONAS, start=1):
                created = await _dispatch(
                    client_id,
                    f"创建角色 {name}",
                    f"soak-create-{index}",
                )
                assert "行纪开篇" in _content(created)
                current = services.load_current_character(_evidence(client_id, clock[0]))
                assert current.status == "ok" and current.character is not None
                characters[client_id] = current.character
                overview = services.load_character_overview(current.character).overview
                assert overview is not None
                initial_instance_ids[client_id] = set(overview.inventory.instances)

            for index, (client_id, _) in enumerate(PERSONAS, start=1):
                character = characters[client_id]
                if index % 2 == 0:
                    enabled = await _dispatch(
                        client_id,
                        "自动用药 开启",
                        f"soak-auto-medicine-{index}",
                    )
                    assert "当前状态: _开启_" in _content(enabled)
                overview = services.load_character_overview(character).overview
                assert overview is not None
                view = services.world_view(overview.character_world)
                region_name = view.projector.name(GREEN_CLOUD_PLAIN_ID)
                moved = await _dispatch(
                    client_id,
                    f"前往 {region_name}",
                    f"soak-move-{index}",
                )
                assert "抵达" in _content(moved)

                for session_number in range(1, 6):
                    await _ensure_recovered(
                        services,
                        client_id,
                        character,
                        clock,
                        f"{index}-{session_number}",
                    )
                    started = await _dispatch(
                        client_id,
                        "开始探险",
                        f"soak-start-{index}-{session_number}",
                    )
                    assert "首次结算" in _content(started)
                    for _ in range(8):
                        clock[0] += timedelta(minutes=10)
                        settled = services.exploration.settle_due(
                            character.id,
                            logical_time=clock[0],
                        )
                        for batch in settled.batches:
                            stats["batches"] += 1
                            stats[f"player_{index}_batches"] += 1
                            stats[f"encounter_{batch.plan.encounter_kind.value}"] += 1
                            if batch.victory:
                                stats["victories"] += 1
                            elif batch.draw:
                                stats["draws"] += 1
                            else:
                                stats["defeats"] += 1
                        if settled.state is None or settled.state.status is not ExplorationStatus.RUNNING:
                            if settled.state is not None and settled.state.stop_reason is not None:
                                stats[f"stop_{settled.state.stop_reason.value}"] += 1
                                stats[
                                    f"player_{index}_stop_{settled.state.stop_reason.value}"
                                ] += 1
                            break
                    summary = await _dispatch(
                        client_id,
                        "探险总结",
                        f"soak-summary-{index}-{session_number}",
                    )
                    assert "探险" in _content(summary)
                    state = services.exploration.load(
                        character.id,
                        logical_time=clock[0],
                    ).state
                    if state is not None and state.status is ExplorationStatus.RUNNING:
                        stopped = await _dispatch(
                            client_id,
                            "停止探险",
                            f"soak-stop-{index}-{session_number}",
                        )
                        assert "停止" in _content(stopped)
                    if await _equip_new_drop(
                        services,
                        client_id,
                        character,
                        initial_instance_ids[client_id],
                        attempted_equipment[client_id],
                        f"{index}-{session_number}",
                    ):
                        stats["equipped_drops"] += 1
                    recycled = await _dispatch(
                        client_id,
                        "回收战利品",
                        f"soak-recycle-{index}-{session_number}",
                    )
                    assert "战利品" in _content(recycled)

                snapshot_before = _aggregate_rows(services, character.id)
                mode = ("单体", "群体", "持久", "单体")[index - 1]
                trial = await _dispatch(
                    client_id,
                    f"开始试炼 {mode}",
                    f"soak-trial-{index}",
                )
                assert "查看完整战报" in _content(trial)
                assert _aggregate_rows(services, character.id) == snapshot_before
                await _ensure_recovered(
                    services,
                    client_id,
                    character,
                    clock,
                    f"{index}-social",
                )

            await _spar(services, characters)
            await _party(services, characters)

            all_instance_ids = []
            for client_id, character in characters.items():
                overview = services.load_character_overview(character).overview
                assert overview is not None
                progression = overview.character.progressions[CHARACTER_LEVEL_PROGRESSION_ID]
                assert progression.total_experience >= 0
                assert overview.character.resources[HEALTH_CURRENT] >= 0
                assert overview.character.resources[SPIRIT_CURRENT] >= 0
                all_instance_ids.extend(overview.inventory.instances)
                stats["new_instances"] += len(
                    set(overview.inventory.instances) - initial_instance_ids[client_id]
                )
            assert len(all_instance_ids) == len(set(all_instance_ids))
            assert stats["batches"] >= len(PERSONAS) * 5

            restarted = build_game_services(
                database_path=path,
                identity_secret="player-soak-test-secret",
            )
            restarted.database.initialize()
            for character in characters.values():
                loaded = restarted.characters.load_character(character.id)
                assert loaded is not None
                assert restarted.load_character_overview(loaded).overview is not None
            stats["players"] = len(characters)
            return stats
        finally:
            restore_game_services(previous)


async def _ensure_recovered(services, client_id, character, clock, suffix) -> None:
    overview = services.load_character_overview(character).overview
    assert overview is not None
    maximum = overview.character.core_attributes[HEALTH_MAXIMUM]
    if overview.character.resources[HEALTH_CURRENT] >= maximum:
        return
    started = await _dispatch(client_id, "休息", f"soak-rest-{suffix}")
    assert "已经开始休息" in _content(started)
    clock[0] += timedelta(hours=24)
    ended = await _dispatch(client_id, "结束休息", f"soak-rest-stop-{suffix}")
    assert "恢复" in _content(ended) or "结束" in _content(ended)
    recovered = services.load_character_overview(character).overview
    assert recovered is not None
    assert recovered.character.resources[HEALTH_CURRENT] > 0


async def _equip_new_drop(
    services,
    client_id,
    character,
    initial_ids: set[str],
    attempted_ids: set[str],
    suffix: str,
) -> bool:
    overview = services.load_character_overview(character).overview
    assert overview is not None
    for instance in overview.inventory.instances.values():
        if instance.id in initial_ids or instance.id in attempted_ids:
            continue
        attempted_ids.add(instance.id)
        definition = services.content.catalog.items.require(instance.definition_id)
        if not (
            definition.tags.has("item.weapon")
            or definition.tags.has("item.equipment")
        ):
            continue
        reference = asset_reference(
            overview.inventory,
            instance,
            services.content.catalog.items,
        )
        equipped = await _dispatch(
            client_id,
            f"装备 {reference}",
            f"soak-equip-{suffix}",
        )
        assert "装配" in _content(equipped) or "装备" in _content(equipped)
        return True
    return False


async def _spar(services, characters) -> None:
    left_client, right_client = PERSONAS[0][0], PERSONAS[1][0]
    left_before = services.characters.load_character(characters[left_client].id)
    right_before = services.characters.load_character(characters[right_client].id)
    request = await _dispatch(left_client, f"切磋 {right_client}", "soak-spar-request")
    accept = next(
        action.data for action in request.replies[0].message.actions if action.label == "接受"
    )
    accepted = await _dispatch(right_client, accept, "soak-spar-accept")
    assert "查看完整战报" in _content(accepted)
    assert services.characters.load_character(characters[left_client].id) == left_before
    assert services.characters.load_character(characters[right_client].id) == right_before


async def _party(services, characters) -> None:
    leader, second, third = (value[0] for value in PERSONAS[:3])
    created = await _dispatch(leader, "创建队伍", "soak-party-create")
    assert "你现在是队长" in _content(created)
    for index, member in enumerate((second, third), start=1):
        invited = await _dispatch(
            leader,
            f"邀请组队 {member}",
            f"soak-party-invite-{index}",
        )
        assert "发出队伍邀请" in _content(invited)
        incoming = await _dispatch(member, "组队", f"soak-party-view-{index}")
        accept = next(
            action.data
            for action in incoming.replies[0].message.actions
            if action.label == "接受"
        )
        joined = await _dispatch(member, accept, f"soak-party-accept-{index}")
        assert "已经加入队伍" in _content(joined)
    roster = await _dispatch(leader, "组队", "soak-party-roster")
    assert "人数: _3/3_" in _content(roster)


def _aggregate_rows(services, character_id: str):
    with services.database.unit_of_work(write=False) as uow:
        rows = uow.connection.execute(
            """
            SELECT aggregate_kind, aggregate_id, revision, payload
            FROM aggregate_snapshot
            WHERE aggregate_id = ?
            ORDER BY aggregate_kind
            """,
            (character_id,),
        ).fetchall()
    return tuple(tuple(row) for row in rows)


def _evidence(client_id: str, logical_time: datetime) -> IdentityEvidence:
    return IdentityEvidence(
        f"soak-evidence:{client_id}:{logical_time.isoformat()}",
        ExternalIdentity(
            "platform.local",
            config.project.name,
            "identity.local_user",
            "",
            client_id,
        ),
        (),
        "message.local",
        logical_time,
    )


async def _dispatch(client_id: str, command: str, event_id: str):
    result = await dispatch(
        client_id=client_id,
        raw_message=command,
        sender_name=client_id,
        event_id=event_id,
    )
    assert result.matched and result.matched_count == 1, (command, result)
    assert len(result.replies) == 1, (command, result)
    return result


def _content(result) -> str:
    content = result.replies[0].message.content
    assert content.strip()
    return content


if __name__ == "__main__":
    main()
