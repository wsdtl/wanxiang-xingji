"""账号单角色目录与角色快照原子登记测试。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.account import AccountEngine, build_qq_identity_evidence  # noqa: E402
from game.core.gameplay import (  # noqa: E402
    COMBAT_ATTACK,
    COMBAT_DEFENSE,
    COMBAT_SPEED,
    HEALTH_MAXIMUM,
    SPIRIT_MAXIMUM,
    CharacterCatalog,
    CharacterTemplateDefinition,
)
from game.core.persistence import (  # noqa: E402
    ConcurrencyConflict,
    PersistedAccountService,
    PersistedCharacterService,
    SqliteDatabase,
)


TIME = datetime(2026, 7, 14, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


class AccountIds:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> str:
        self.value += 1
        return f"account-{self.value}"


def main() -> None:
    with TemporaryDirectory() as directory:
        database = SqliteDatabase(Path(directory) / "character.db")
        database.initialize()
        accounts = PersistedAccountService(
            database,
            AccountEngine(AccountIds()),
            "character-registration-secret",
        )
        account_a = _account(accounts, "event-a", "user-a")
        account_b = _account(accounts, "event-b", "user-b")
        account_c = _account(accounts, "event-c", "user-c")
        catalog = _catalog()

        service = PersistedCharacterService(database)
        character_a = _character(catalog, "character-a", account_a, "同名角色")
        registered = service.register(
            character_a,
            transaction_id="register-a",
            logical_time=TIME,
        )
        assert not registered.replayed
        assert registered.roster.character_ids == ("character-a",)
        assert service.character_ids_for(account_a) == ("character-a",)
        assert service.load_for_account(account_a) == character_a

        replayed = service.register(
            character_a,
            transaction_id="register-a",
            logical_time=TIME,
        )
        assert replayed.replayed and replayed.character == character_a

        try:
            service.register(
                _character(catalog, "character-a-2", account_a, "第二角色"),
                transaction_id="register-a-2",
                logical_time=TIME,
            )
            raise AssertionError("一个账号不能登记第二个角色")
        except ConcurrencyConflict:
            pass
        assert service.load_character("character-a-2") is None

        # 名称当前不要求全服唯一，不同账号可以使用相同名称。
        character_b = _character(catalog, "character-b", account_b, "同名角色")
        service.register(character_b, transaction_id="register-b", logical_time=TIME)
        assert service.load_for_account(account_b) == character_b

        _assert_concurrent_single_character(database, catalog, account_c)
        restarted = PersistedCharacterService(SqliteDatabase(database.path))
        assert restarted.load_for_account(account_a) == character_a

    print("character registration tests passed")


def _assert_concurrent_single_character(database, catalog, account_id: str) -> None:
    candidates = (
        _character(catalog, "character-c-1", account_id, "并发甲"),
        _character(catalog, "character-c-2", account_id, "并发乙"),
    )

    def register(index: int) -> str:
        service = PersistedCharacterService(database)
        try:
            result = service.register(
                candidates[index],
                transaction_id=f"register-c-{index}",
                logical_time=TIME,
            )
            return result.character.id
        except ConcurrencyConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(register, range(2)))
    assert results.count("conflict") == 1
    assert len(PersistedCharacterService(database).character_ids_for(account_id)) == 1


def _account(service, event_id: str, user_id: str) -> str:
    resolution = service.resolve_identity(
        build_qq_identity_evidence(
            bot_app_id="bot-app",
            event_id=event_id,
            logical_time=TIME,
            conversation_type="private",
            actor_openid=user_id,
            user_openid=user_id,
        )
    )
    assert resolution.account is not None
    return resolution.account.id


def _catalog() -> CharacterCatalog:
    catalog = CharacterCatalog()
    catalog.templates.register(
        CharacterTemplateDefinition(
            "character_template.registration_test",
            {
                HEALTH_MAXIMUM: 100,
                SPIRIT_MAXIMUM: 50,
                COMBAT_ATTACK: 10,
                COMBAT_DEFENSE: 5,
                COMBAT_SPEED: 5,
            },
        )
    )
    catalog.finalize()
    return catalog


def _character(catalog, character_id: str, account_id: str, name: str):
    return catalog.create_character(
        character_id=character_id,
        account_id=account_id,
        name=name,
        template_id="character_template.registration_test",
        created_at=TIME,
    )


if __name__ == "__main__":
    main()
