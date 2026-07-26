"""角色完整创世、回放、并发与事务回滚测试。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Lock
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.rules.character import (  # noqa: E402
    CHARACTER_WORLD_AGGREGATE,
    CHARACTER_SETTINGS_AGGREGATE,
    CharacterWorldState,
    CharacterCreationWorkflow,
    CharacterCreationRequest,
)
from game.content import (  # noqa: E402
    AUTO_HEALTH_TARGET_RATIO,
    AUTO_HEALTH_TRIGGER_RATIO,
    AUTO_SPIRIT_TARGET_RATIO,
    AUTO_SPIRIT_TRIGGER_RATIO,
    CHARACTER_LEVEL_EXPERIENCE_REQUIREMENTS,
    INITIAL_BACKPACK_CAPACITY,
    INITIAL_CURRENCY_AMOUNT,
    INITIAL_MEDICINE_QUANTITY,
    LOADOUT_PRESET_IDS,
    PLAYABLE_WORLD_IDS,
    PRIMARY_CURRENCY_ID,
    SMALL_HEALTH_MEDICINE_ITEM_ID,
    SMALL_SPIRIT_MEDICINE_ITEM_ID,
)
from game.core.account import AccountEngine, build_qq_identity_evidence  # noqa: E402
from game.core.gameplay import (  # noqa: E402
    HEALTH_CURRENT,
    HEALTH_MAXIMUM,
    SPIRIT_CURRENT,
    SPIRIT_MAXIMUM,
    WEAPON_SLOT_ID,
    CharacterRosterState,
    CharacterState,
    InventoryState,
    LedgerState,
    LoadoutState,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    WorldState,
    weapon_state_from_instance,
)
from game.core.persistence import (  # noqa: E402
    CHARACTER_AGGREGATE,
    CHARACTER_ROSTER_AGGREGATE,
    INVENTORY_AGGREGATE,
    LEDGER_AGGREGATE,
    LOADOUT_AGGREGATE,
    WORLD_AGGREGATE,
    PersistedAccountService,
    PersistedCharacterCreationService,
    SnapshotRepository,
    SqliteDatabase,
    ConcurrencyConflict,
)
from game.rules.character import (  # noqa: E402
    CharacterIdentityViolation,
    CharacterSettingsState,
)
from game.rules.character.creation import (  # noqa: E402
    PRIMARY_LEDGER_ID,
    MULTIVERSE_WORLD_STATE_ID,
)


TIME = datetime(2026, 7, 14, 18, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


class SequentialIds:
    def __init__(self) -> None:
        self.value = 0
        self.lock = Lock()

    def account(self) -> str:
        with self.lock:
            self.value += 1
            return f"account-{self.value}"

    def game(self, kind: str) -> str:
        with self.lock:
            self.value += 1
            return f"{kind}-{self.value}"


def main() -> None:
    _assert_policy_constants()
    _assert_legacy_settings_payload()
    with TemporaryDirectory() as directory:
        path = Path(directory) / "character-creation.db"
        database = SqliteDatabase(path)
        database.initialize()
        ids = SequentialIds()
        account_service = PersistedAccountService(
            database,
            AccountEngine(ids.account),
            "character-creation-test-secret",
        )
        account_a = _account(account_service, "event-a", "user-a")
        account_b = _account(account_service, "event-b", "user-b")
        account_c = _account(account_service, "event-c", "user-c")
        _assert_complete_creation(database, ids, account_a)
        _assert_failed_creation_rolls_back(database, ids, account_b)
        _assert_concurrent_creation(database, account_c)
    print("character creation tests passed")


def _context(seed: int) -> RuleContext:
    return RuleContext(
        f"character-creation-{seed}",
        "rules.v1",
        Ruleset("ruleset.standard"),
        TIME,
        SeededRandomSource(seed),
    )


def _account(service, event_id: str, user_id: str) -> str:
    result = service.resolve_identity(
        build_qq_identity_evidence(
            bot_app_id="bot-app",
            event_id=event_id,
            logical_time=TIME,
            conversation_type="private",
            actor_openid=user_id,
            user_openid=user_id,
        )
    )
    assert result.account is not None
    return result.account.id


def _assert_policy_constants() -> None:
    assert len(CHARACTER_LEVEL_EXPERIENCE_REQUIREMENTS) == 99
    assert sum(CHARACTER_LEVEL_EXPERIENCE_REQUIREMENTS) == 270_305_413
    assert AUTO_HEALTH_TRIGGER_RATIO == 0.25
    assert AUTO_HEALTH_TARGET_RATIO == 0.55
    assert AUTO_SPIRIT_TRIGGER_RATIO == 0.15
    assert AUTO_SPIRIT_TARGET_RATIO == 0.45


def _assert_legacy_settings_payload() -> None:
    """新增个人设置字段必须能由 dataclass 默认值接住旧快照。"""

    workflow = CharacterCreationWorkflow(id_factory=lambda kind: kind)
    service = PersistedCharacterCreationService(
        SqliteDatabase(":memory:"),
        workflow,
    )
    payload = (
        '{"format":"structured-json.v1","value":'
        '{"$fields":{"auto_use_medicine":true,'
        '"character_id":"legacy-character","revision":0},'
        '"$type":"product.character_settings"}}'
    )
    restored = service.snapshots.codec.loads(payload, CharacterSettingsState)
    assert restored == CharacterSettingsState("legacy-character")


def _assert_complete_creation(database, ids: SequentialIds, account_id: str) -> None:
    workflow = CharacterCreationWorkflow(id_factory=ids.game)
    service = PersistedCharacterCreationService(database, workflow)
    request = CharacterCreationRequest(
        "character-create-a",
        account_id,
        platform_name="云舟客",
    )
    receipt = service.create(request, context=_context(1))
    assert not receipt.replayed
    character = receipt.character
    assert receipt.inventory_id == character.id
    assert character.name == "云舟客"
    assert character.resources[HEALTH_CURRENT] == character.core_attributes[HEALTH_MAXIMUM] == 100
    assert character.resources[SPIRIT_CURRENT] == character.core_attributes[SPIRIT_MAXIMUM] == 100
    progression = next(iter(character.progressions.values()))
    assert (progression.level, progression.experience, progression.total_experience) == (1, 0, 0)

    containers = {
        container.kind: container
        for container in receipt.inventory.containers.values()
    }
    assert set(containers) == {
        "container.special",
        "container.inscription",
        "container.armory",
        "container.backpack",
        "container.equipped",
    }
    assert containers["container.special"].required_item_tags.has("storage.special")
    assert containers["container.inscription"].required_item_tags.has("storage.inscription")
    assert containers["container.armory"].required_item_tags.has("item.armament")
    assert containers["container.backpack"].maximum_space == INITIAL_BACKPACK_CAPACITY
    assert containers["container.backpack"].maximum_assets is None
    assert containers["container.equipped"].maximum_assets == 7
    quantities = {
        stack.definition_id: stack.quantity
        for stack in receipt.inventory.stacks.values()
    }
    assert quantities == {
        SMALL_HEALTH_MEDICINE_ITEM_ID: INITIAL_MEDICINE_QUANTITY,
        SMALL_SPIRIT_MEDICINE_ITEM_ID: INITIAL_MEDICINE_QUANTITY,
    }
    weapon_instance = receipt.inventory.instances[receipt.starter_weapon.asset_id]
    assert weapon_state_from_instance(weapon_instance) == receipt.starter_weapon
    assert weapon_instance.container_id == containers["container.equipped"].id
    assert all(
        stack.container_id == containers["container.special"].id
        for stack in receipt.inventory.stacks.values()
    )
    assert set(receipt.inventory.asset_references) == {
        *receipt.inventory.stacks,
        *receipt.inventory.instances,
    }

    assert tuple(receipt.loadout.presets) == LOADOUT_PRESET_IDS
    assert receipt.loadout.active_preset_id == LOADOUT_PRESET_IDS[0]
    assert receipt.loadout.presets[LOADOUT_PRESET_IDS[0]].slots == {
        WEAPON_SLOT_ID: receipt.starter_weapon.asset_id
    }
    assert all(
        not receipt.loadout.presets[preset_id].slots
        for preset_id in LOADOUT_PRESET_IDS[1:]
    )
    wallet = next(
        account
        for account in receipt.ledger.accounts.values()
        if account.owner_id == character.id and account.currency_id == PRIMARY_CURRENCY_ID
    )
    assert wallet.balance == INITIAL_CURRENCY_AMOUNT
    assert receipt.settings == CharacterSettingsState(character.id)
    assert receipt.character_world.character_id == character.id
    assert receipt.character_world.world_id in set(PLAYABLE_WORLD_IDS)
    presence = next(
        value for value in receipt.world.presences.values() if value.owner_id == character.id
    )
    runtime = service.workflow.planner.content.world_runtime
    assert runtime.anchor_at(
        receipt.character_world.world_id,
        presence.position,
    ) == runtime.require_world(receipt.character_world.world_id).spawn_anchor_id

    replay = service.create(request, context=_context(2))
    assert replay.replayed and replay.character == character
    assert replay.character_world == receipt.character_world
    try:
        service.create(
            CharacterCreationRequest("character-create-a-again", account_id, "第二角色"),
            context=_context(3),
        )
        raise AssertionError("一个账号不能创建第二个角色")
    except (CharacterIdentityViolation, ConcurrencyConflict):
        pass

    with database.unit_of_work(write=False) as uow:
        assert service.snapshots.require(
            uow, CHARACTER_AGGREGATE, character.id, CharacterState
        ) == character
        assert service.snapshots.require(
            uow, CHARACTER_ROSTER_AGGREGATE, account_id, CharacterRosterState
        ) == receipt.roster
        assert service.snapshots.require(
            uow, INVENTORY_AGGREGATE, receipt.inventory_id, InventoryState
        ) == receipt.inventory
        assert service.snapshots.require(
            uow, LOADOUT_AGGREGATE, character.id, LoadoutState
        ) == receipt.loadout
        assert service.snapshots.require(
            uow, CHARACTER_SETTINGS_AGGREGATE, character.id, CharacterSettingsState
        ) == receipt.settings
        assert service.snapshots.require(
            uow,
            CHARACTER_WORLD_AGGREGATE,
            character.id,
            CharacterWorldState,
        ) == receipt.character_world
        persisted_ledger = service.snapshots.require(
            uow, LEDGER_AGGREGATE, PRIMARY_LEDGER_ID, LedgerState
        )
        assert persisted_ledger == service.snapshots.compact(receipt.ledger)
        assert uow.connection.execute(
            "SELECT COUNT(*) FROM ledger_transaction WHERE ledger_id = ?",
            (PRIMARY_LEDGER_ID,),
        ).fetchone()[0] == len(receipt.ledger.applied_transactions)
        assert uow.connection.execute(
            "SELECT COUNT(*) FROM ledger_journal_entry WHERE ledger_id = ?",
            (PRIMARY_LEDGER_ID,),
        ).fetchone()[0] == len(receipt.ledger.journal)
        assert service.snapshots.require(
            uow, WORLD_AGGREGATE, MULTIVERSE_WORLD_STATE_ID, WorldState
        ) == receipt.world


class FailingSnapshotRepository(SnapshotRepository):
    def insert(self, uow, aggregate_kind, aggregate_id, value, logical_time) -> None:
        if aggregate_kind == CHARACTER_SETTINGS_AGGREGATE:
            raise RuntimeError("模拟创世中途故障")
        super().insert(uow, aggregate_kind, aggregate_id, value, logical_time)


def _assert_failed_creation_rolls_back(database, ids: SequentialIds, account_id: str) -> None:
    workflow = CharacterCreationWorkflow(id_factory=ids.game)
    healthy = PersistedCharacterCreationService(database, workflow)
    failing = PersistedCharacterCreationService(
        database,
        workflow,
        snapshots=FailingSnapshotRepository(healthy.snapshots.codec),
    )
    try:
        failing.create(
            CharacterCreationRequest("character-create-fail", account_id, "归墟客"),
            context=_context(10),
        )
        raise AssertionError("模拟故障必须终止创世")
    except RuntimeError as exc:
        assert "模拟创世" in str(exc)
    with database.unit_of_work(write=False) as uow:
        assert failing.snapshots.load(
            uow, CHARACTER_ROSTER_AGGREGATE, account_id, CharacterRosterState
        ) is None
        assert uow.load_transaction("character-create-fail") is None


def _assert_concurrent_creation(database, account_id: str) -> None:
    def create(index: int) -> str:
        service = PersistedCharacterCreationService(
            database,
            CharacterCreationWorkflow(),
        )
        try:
            return service.create(
                CharacterCreationRequest(
                    f"character-create-concurrent-{index}",
                    account_id,
                    requested_name=f"并发角色{index}",
                ),
                context=_context(20 + index),
            ).character.id
        except (CharacterIdentityViolation, ConcurrencyConflict):
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(create, range(2)))
    assert results.count("rejected") == 1
    with database.unit_of_work(write=False) as uow:
        repository = PersistedCharacterCreationService(
            database,
            CharacterCreationWorkflow(),
        ).snapshots
        roster = repository.require(
            uow, CHARACTER_ROSTER_AGGREGATE, account_id, CharacterRosterState
        )
        assert len(roster.character_ids) == 1


if __name__ == "__main__":
    main()
