"""VIP666 兑换码从公开命令到原子资产落库的回归测试。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from inspect import signature
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.app import build_game_services, install_game_services, restore_game_services  # noqa: E402
from game.cmd import 兑换码 as redemption_component  # noqa: E402,F401
from game.cmd import 角色 as character_component  # noqa: E402,F401
from game.content import COMMON_QUALITY_ID  # noqa: E402
from game.core.gameplay import (  # noqa: E402
    CharacterState,
    EQUIPMENT_SLOT_IDS,
    InventoryState,
    LedgerAccountKind,
    LedgerState,
    RewardClaimState,
    WeaponState,
    equipment_state_from_instance,
    weapon_state_from_instance,
)
from game.core.persistence import (  # noqa: E402
    CHARACTER_AGGREGATE,
    INVENTORY_AGGREGATE,
    LEDGER_AGGREGATE,
    REWARD_CLAIM_AGGREGATE,
    WEAPON_AGGREGATE,
)
from game.rules.character import PRIMARY_LEDGER_ID  # noqa: E402
from game.cmd.兑换码 import service as redemption_command_service  # noqa: E402
from launch.adapter.local import LocalEventHandler, dispatch  # noqa: E402
from launch.adapter.qq import QqEventHandler  # noqa: E402


TIME = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)


def main() -> None:
    asyncio.run(_main())
    print("redemption code tests passed")


async def _main() -> None:
    assert len(LocalEventHandler.exact_rules["兑换码"]) == 1
    assert len(QqEventHandler.exact_rules["兑换码"]) == 1
    assert "grant_code_secret" not in signature(build_game_services).parameters
    assert "GRANT_CODE_SECRET" not in (ROOT / ".env.example").read_text(encoding="utf-8")

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "redemption-code.db"
        seeded = build_game_services(
            database_path=database_path,
            identity_secret="redemption-identity-secret",
        )
        seeded.database.initialize()
        seeded.redemption_codes.initialize(logical_time=TIME)

        services = build_game_services(
            database_path=database_path,
            identity_secret="redemption-identity-secret",
        )
        services.database.initialize()
        services.redemption_codes.initialize(logical_time=TIME)
        services.redemption_codes.initialize(logical_time=TIME)
        previous = install_game_services(services)
        original_now = redemption_command_service.command_time
        redemption_command_service.command_time = lambda: TIME
        try:
            await LocalEventHandler.run()
            await _dispatch("创建角色 拾界者", "redemption-create")
            character = _character(services)
            before_inventory = _inventory(services, character.id)
            before_ids = set(before_inventory.instances)
            before_balance = _balance(services, character.id)

            missing = await _dispatch("兑换码", "redemption-missing")
            assert "请输入要领取的兑换码" in _content(missing)
            assert not missing.replies[0].message.actions

            completed = await _dispatch("兑换码 vip-666", "redemption-complete")
            message = completed.replies[0].message
            content = _content(completed)
            assert message.kind == "markdown"
            assert "兑换码·领取成功" in content
            assert "5000" in content
            assert "开荒装备" in content
            assert "装配" in content and "武库" in content
            assert not message.actions

            inventory = _inventory(services, character.id)
            new_ids = set(inventory.instances) - before_ids
            assert len(new_ids) == 7
            equipment_slots = set()
            weapon_ids = []
            references = []
            for asset_id in new_ids:
                instance = inventory.instances[asset_id]
                definition = services.content.catalog.items.require(instance.definition_id)
                references.append(inventory.reference_number(asset_id))
                if definition.tags.has("item.weapon"):
                    state = weapon_state_from_instance(instance)
                    assert state.quality_id == COMMON_QUALITY_ID
                    weapon_ids.append(asset_id)
                elif definition.tags.has("item.equipment"):
                    state = equipment_state_from_instance(instance)
                    assert state.quality_id == COMMON_QUALITY_ID
                    equipment_slots.add(
                        services.content.catalog.equipment.require(state.definition_id).slot_id
                    )
                else:
                    raise AssertionError(f"兑换码生成了非武器装备实例：{instance.definition_id}")
            assert len(weapon_ids) == 1
            assert equipment_slots == set(EQUIPMENT_SLOT_IDS)
            assert all(f"W{value}" in content or f"E{value}" in content for value in references)
            assert _balance(services, character.id) == before_balance + 5_000

            with services.database.unit_of_work(write=False) as uow:
                weapon = services.redemption_codes.snapshots.require(
                    uow,
                    WEAPON_AGGREGATE,
                    weapon_ids[0],
                    WeaponState,
                )
                claim = services.redemption_codes.snapshots.require(
                    uow,
                    REWARD_CLAIM_AGGREGATE,
                    character.account_id,
                    RewardClaimState,
                )
                rows = uow.connection.execute("SELECT * FROM grant_credential").fetchall()
            assert weapon.asset_id == weapon_ids[0]
            assert getattr(claim, "revision", 0) == 1
            persisted = "\n".join(str(value) for row in rows for value in row)
            assert "VIP666" not in persisted

            stable_ids = set(_inventory(services, character.id).instances)
            stable_balance = _balance(services, character.id)
            repeated = await _dispatch("兑换码 VIP666", "redemption-repeat")
            assert "已经领取过" in _content(repeated)
            assert set(_inventory(services, character.id).instances) == stable_ids
            assert _balance(services, character.id) == stable_balance

            invalid = await _dispatch("兑换码 NOT-A-CODE", "redemption-invalid")
            assert "兑换码无效" in _content(invalid)
            assert set(_inventory(services, character.id).instances) == stable_ids
            assert _balance(services, character.id) == stable_balance
        finally:
            redemption_command_service.command_time = original_now
            restore_game_services(previous)


async def _dispatch(raw_message: str, event_id: str):
    return await dispatch(
        client_id="redemption-player",
        raw_message=raw_message,
        sender_name="拾界者",
        event_id=event_id,
    )


def _content(result) -> str:
    assert result.matched
    assert len(result.replies) == 1, result
    return result.replies[0].message.content


def _character(services):
    with services.database.unit_of_work(write=False) as uow:
        characters = services.redemption_codes.snapshots.list(
            uow,
            CHARACTER_AGGREGATE,
            CharacterState,
            limit=10,
        )
    assert len(characters) == 1
    return characters[0]


def _inventory(services, character_id: str) -> InventoryState:
    with services.database.unit_of_work(write=False) as uow:
        return services.redemption_codes.snapshots.require(
            uow,
            INVENTORY_AGGREGATE,
            character_id,
            InventoryState,
        )


def _balance(services, character_id: str) -> int:
    with services.database.unit_of_work(write=False) as uow:
        ledger = services.redemption_codes.snapshots.require(
            uow,
            LEDGER_AGGREGATE,
            PRIMARY_LEDGER_ID,
            LedgerState,
        )
    return next(
        value.balance
        for value in ledger.accounts.values()
        if value.kind is LedgerAccountKind.STANDARD
        and value.owner_kind == "owner.character"
        and value.owner_id == character_id
    )


if __name__ == "__main__":
    main()
