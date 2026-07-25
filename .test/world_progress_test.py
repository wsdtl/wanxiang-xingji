"""世界行纪累计、奖励、排名重建和命令展示验收。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.app import build_game_services, install_game_services, restore_game_services  # noqa: E402
from game.content import (  # noqa: E402
    DIMENSION_SHIFT_ITEM_ID,
    DRAW_TICKET_ITEM_ID,
    MAGIC_WORLD_ID,
    STELLAR_RING_WORLD_ID,
    TAIXUAN_WORLD_ID,
)
from game.content.catalog.world import GREEN_CLOUD_PLAIN_ID  # noqa: E402
from game.core.gameplay import InventoryState, LedgerAccountKind, LedgerState  # noqa: E402
from game.core.persistence import (  # noqa: E402
    CHARACTER_AGGREGATE,
    FactJournalService,
    INVENTORY_AGGREGATE,
    LEDGER_AGGREGATE,
    ProjectionStore,
)
from game.features.exploration import ExplorationVictoryFact  # noqa: E402
from game.features.world_progress.service import (  # noqa: E402
    WORLD_PROGRESS_FACT_KIND,
    WORLD_PROGRESS_PARTITION_ID,
    WORLD_PROGRESS_PROJECTOR_ID,
)
from game.rules.character import PRIMARY_LEDGER_ID  # noqa: E402
from game.rules.world_progress import (  # noqa: E402
    WORLD_PROGRESS_AGGREGATE,
    WorldProgressState,
    world_progress_state_id,
)
from game.cmd import 行纪 as progress_component  # noqa: E402,F401
from game.cmd import 角色 as character_component  # noqa: E402,F401
from launch.adapter.local import LocalEventHandler, dispatch  # noqa: E402


TIMEZONE = ZoneInfo("Asia/Shanghai")
STARTED_AT = datetime(2026, 7, 21, 16, 0, tzinfo=TIMEZONE)
CLIENT_ID = "world-progress-player"


def main() -> None:
    asyncio.run(_main())
    print("world progress tests passed")


async def _main() -> None:
    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "world-progress.db",
            identity_secret="world-progress-secret",
        )
        services.database.initialize()
        previous = install_game_services(services)
        try:
            await LocalEventHandler.run()
            await _dispatch("创建角色 行纪者", "progress-create")
            character = _created_character(services)
            initial_balance = _balance(services, character.id)

            last_fact = None
            for index in range(25):
                last_fact = _fact(
                    character.id,
                    character.name,
                    TAIXUAN_WORLD_ID,
                    "normal",
                    index,
                )
                with services.database.unit_of_work() as uow:
                    _publish_fact(uow, services, last_fact)
                    result = services.world_progress.observe_victory_in_uow(uow, last_fact)
                    uow.commit()
                assert result.added_points == 1
            assert result.reached_milestones == (25,)
            assert result.reward_amount == 25
            assert _balance(services, character.id) == initial_balance + 25

            with services.database.unit_of_work() as uow:
                replayed = services.world_progress.observe_victory_in_uow(uow, last_fact)
                uow.commit()
            assert replayed.status == "replayed"
            assert _balance(services, character.id) == initial_balance + 25

            magic_fact = _fact(
                character.id,
                character.name,
                MAGIC_WORLD_ID,
                "elite",
                100,
            )
            with services.database.unit_of_work() as uow:
                _publish_fact(uow, services, magic_fact)
                magic = services.world_progress.observe_victory_in_uow(uow, magic_fact)
                uow.commit()
            assert magic.added_points == 2
            taixuan = services.world_progress.view(character.id, TAIXUAN_WORLD_ID)
            magic_view = services.world_progress.view(character.id, MAGIC_WORLD_ID)
            assert taixuan.require_region("exploration.region.r1").points == 25
            assert magic_view.require_region("exploration.region.r1").points == 2

            facts = FactJournalService(services.database).list(
                kinds=(WORLD_PROGRESS_FACT_KIND,),
                limit=100,
            )
            assert len(facts) == 26
            global_rank = services.world_progress.ranking_view(
                character.id,
                world_id=None,
                logical_time=STARTED_AT + timedelta(hours=1),
            )
            assert global_rank.entries[0].points == 27
            world_rank = services.world_progress.ranking_view(
                character.id,
                world_id=TAIXUAN_WORLD_ID,
                logical_time=STARTED_AT + timedelta(hours=1),
            )
            assert world_rank.entries[0].points == 25

            store = ProjectionStore(services.database)
            checkpoint = store.checkpoint(
                WORLD_PROGRESS_PROJECTOR_ID,
                WORLD_PROGRESS_PARTITION_ID,
            )
            assert checkpoint is not None
            store.reset(
                WORLD_PROGRESS_PROJECTOR_ID,
                WORLD_PROGRESS_PARTITION_ID,
                expected_revision=checkpoint[1],
                logical_time=STARTED_AT + timedelta(hours=2),
            )
            assert not store.records(WORLD_PROGRESS_PROJECTOR_ID, WORLD_PROGRESS_PARTITION_ID)
            assert services.world_progress.rebuild_ranking_projection(
                logical_time=STARTED_AT + timedelta(hours=3)
            ) == 1
            rebuilt = services.world_progress.ranking_view(
                character.id,
                world_id=None,
                logical_time=STARTED_AT + timedelta(hours=3),
            )
            assert rebuilt.entries[0].points == 27

            world_name = services.world_views.require(TAIXUAN_WORLD_ID).skin.name
            location_name = services.world_views.require(TAIXUAN_WORLD_ID).projector.name(
                GREEN_CLOUD_PLAIN_ID
            )
            overview_reply = await _dispatch("行纪", "progress-view")
            assert world_name in _content(overview_reply)
            assert "总进度" in _content(overview_reply)
            assert "完成全部区域后获得" in _content(overview_reply)
            detail_reply = await _dispatch(f"行纪 {location_name}", "progress-detail")
            assert "25/100" in _content(detail_reply) and "胜利" in _content(detail_reply)
            assert "25 灵石" in _content(detail_reply)
            assert "流光签 x1" in _content(detail_reply)
            rank_reply = await _dispatch("行纪排行", "progress-rank")
            assert "诸界行纪排行" in _content(rank_reply)
            world_rank_reply = await _dispatch(
                f"行纪排行 {world_name}",
                "progress-world-rank",
            )
            assert f"{world_name}行纪排行" in _content(world_rank_reply)

            await _assert_world_completion_rewards(services, character)
        finally:
            restore_game_services(previous)


async def _assert_world_completion_rewards(services, character) -> None:
    bindings = services.content.worlds.bindings_for_world(
        STELLAR_RING_WORLD_ID,
        function_id="location.function.exploration",
    )
    region_ids = tuple(value.content_ref for value in bindings)
    assert len(region_ids) == 13
    final_region_id = region_ids[-1]
    completed_at = STARTED_AT + timedelta(days=3)
    with services.database.unit_of_work() as uow:
        for region_id in region_ids[:-1]:
            state = WorldProgressState(
                character.id,
                character.name,
                STELLAR_RING_WORLD_ID,
                region_id,
                points=100,
                victories=20,
                claimed_milestones=(25, 50, 75, 100),
                started_at=completed_at,
                reached_at=completed_at,
                completed_at=completed_at,
                revision=1,
            )
            services.world_progress.snapshots.insert(
                uow,
                WORLD_PROGRESS_AGGREGATE,
                world_progress_state_id(character.id, STELLAR_RING_WORLD_ID, region_id),
                state,
                completed_at,
            )
        state = WorldProgressState(
            character.id,
            character.name,
            STELLAR_RING_WORLD_ID,
            final_region_id,
            points=95,
            victories=19,
            claimed_milestones=(25, 50, 75),
            started_at=completed_at,
            reached_at=completed_at,
            revision=1,
        )
        services.world_progress.snapshots.insert(
            uow,
            WORLD_PROGRESS_AGGREGATE,
            world_progress_state_id(character.id, STELLAR_RING_WORLD_ID, final_region_id),
            state,
            completed_at,
        )
        uow.commit()

    before_balance = _balance(services, character.id)
    before_inventory = _inventory(services, character.id)
    fact = _fact(
        character.id,
        character.name,
        STELLAR_RING_WORLD_ID,
        "boss",
        900,
        region_id=final_region_id,
    )
    with services.database.unit_of_work() as uow:
        _publish_fact(uow, services, fact)
        result = services.world_progress.observe_victory_in_uow(uow, fact)
        uow.commit()
    assert result.reached_milestones == (100,)
    assert result.reward_amount == 200
    assert result.reward_items == (
        (DRAW_TICKET_ITEM_ID, 1),
        (DIMENSION_SHIFT_ITEM_ID, 1),
    )
    assert result.world_completed is True
    assert _balance(services, character.id) == before_balance + 200
    after_inventory = _inventory(services, character.id)
    assert _stack_quantity(after_inventory, DRAW_TICKET_ITEM_ID) == (
        _stack_quantity(before_inventory, DRAW_TICKET_ITEM_ID) + 1
    )
    assert _stack_quantity(after_inventory, DIMENSION_SHIFT_ITEM_ID) == (
        _stack_quantity(before_inventory, DIMENSION_SHIFT_ITEM_ID) + 1
    )

    with services.database.unit_of_work() as uow:
        replayed = services.world_progress.observe_victory_in_uow(uow, fact)
        uow.commit()
    assert replayed.status == "replayed"
    assert _balance(services, character.id) == before_balance + 200
    assert _stack_quantity(_inventory(services, character.id), DRAW_TICKET_ITEM_ID) == (
        _stack_quantity(before_inventory, DRAW_TICKET_ITEM_ID) + 1
    )
    stellar_name = services.world_views.require(STELLAR_RING_WORLD_ID).skin.name
    reply = await _dispatch(f"行纪 {stellar_name}", "progress-stellar-complete")
    reply_content = _content(reply)
    assert "世界圆满" in reply_content and "已获得" in reply_content
    assert "界门相位核 x1" in reply_content
    assert "&#91;完成&#93;" in reply_content
    assert "\\[完成\\]" not in reply_content
    _assert_world_completion_backfill(services, character)


def _assert_world_completion_backfill(services, character) -> None:
    bindings = services.content.worlds.bindings_for_world(
        MAGIC_WORLD_ID,
        function_id="location.function.exploration",
    )
    region_ids = tuple(value.content_ref for value in bindings)
    completed_at = STARTED_AT + timedelta(days=4)
    with services.database.unit_of_work() as uow:
        for region_id in region_ids:
            aggregate_id = world_progress_state_id(
                character.id,
                MAGIC_WORLD_ID,
                region_id,
            )
            previous = services.world_progress.snapshots.load(
                uow,
                WORLD_PROGRESS_AGGREGATE,
                aggregate_id,
                WorldProgressState,
            )
            state = WorldProgressState(
                character.id,
                character.name,
                MAGIC_WORLD_ID,
                region_id,
                points=100,
                victories=20,
                claimed_milestones=(25, 50, 75, 100),
                started_at=completed_at,
                reached_at=completed_at,
                completed_at=completed_at,
                revision=previous.revision + 1 if previous else 1,
            )
            if previous is None:
                services.world_progress.snapshots.insert(
                    uow,
                    WORLD_PROGRESS_AGGREGATE,
                    aggregate_id,
                    state,
                    completed_at,
                )
            else:
                services.world_progress.snapshots.update(
                    uow,
                    WORLD_PROGRESS_AGGREGATE,
                    aggregate_id,
                    previous,
                    state,
                    completed_at,
                )
        uow.commit()

    before = _stack_quantity(_inventory(services, character.id), DIMENSION_SHIFT_ITEM_ID)
    pending = services.world_progress.view(character.id, MAGIC_WORLD_ID)
    assert pending.completed_regions == len(region_ids)
    assert pending.world_completion_reward_claimed is False
    for index, expected_items in ((901, ((DIMENSION_SHIFT_ITEM_ID, 1),)), (902, ())):
        fact = _fact(
            character.id,
            character.name,
            MAGIC_WORLD_ID,
            "boss",
            index,
            region_id=region_ids[0],
        )
        with services.database.unit_of_work() as uow:
            _publish_fact(uow, services, fact)
            result = services.world_progress.observe_victory_in_uow(uow, fact)
            uow.commit()
        assert result.status == "completed"
        assert result.reward_items == expected_items
    claimed = services.world_progress.view(character.id, MAGIC_WORLD_ID)
    assert claimed.world_completion_reward_claimed is True
    assert _stack_quantity(_inventory(services, character.id), DIMENSION_SHIFT_ITEM_ID) == before + 1


def _fact(character_id, character_name, world_id, kind, index, *, region_id=None):
    return ExplorationVictoryFact(
        f"test-victory-{world_id}-{index}",
        character_id,
        character_name,
        world_id,
        region_id or "exploration.region.r1",
        kind,
        STARTED_AT + timedelta(minutes=index * 10),
    )


def _publish_fact(uow, services, fact) -> None:
    payload = services.character_creation.snapshots.codec.dumps(fact)
    transaction_id = f"test-exploration-victory:{fact.event_id}"
    timestamp = fact.resolved_at.isoformat()
    uow.insert_transaction(
        transaction_id,
        sha256(payload.encode("utf-8")).hexdigest(),
        fact.character_id,
        payload,
        timestamp,
    )
    uow.append_fact(
        transaction_id,
        0,
        WORLD_PROGRESS_FACT_KIND,
        payload,
        timestamp,
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


def _balance(services, character_id: str) -> int:
    with services.database.unit_of_work(write=False) as uow:
        ledger = services.character_creation.snapshots.require(
            uow,
            LEDGER_AGGREGATE,
            PRIMARY_LEDGER_ID,
            LedgerState,
        )
    return next(
        account.balance
        for account in ledger.accounts.values()
        if account.kind is LedgerAccountKind.STANDARD
        and account.owner_id == character_id
    )


def _inventory(services, character_id: str) -> InventoryState:
    with services.database.unit_of_work(write=False) as uow:
        return services.world_progress.snapshots.require(
            uow,
            INVENTORY_AGGREGATE,
            character_id,
            InventoryState,
        )


def _stack_quantity(inventory: InventoryState, definition_id: str) -> int:
    return sum(
        value.quantity
        for value in inventory.stacks.values()
        if value.definition_id == definition_id
    )


async def _dispatch(command: str, event_id: str):
    return await dispatch(
        client_id=CLIENT_ID,
        raw_message=command,
        sender_name="行纪者",
        event_id=event_id,
    )


def _content(result) -> str:
    assert result.matched and result.matched_count == 1, result
    assert 1 <= len(result.replies) <= 2, result
    if len(result.replies) == 2:
        assert "世界篇章" in result.replies[1].message.content
    return result.replies[0].message.content


if __name__ == "__main__":
    main()
