"""把角色、资产、经济和世界初态规划成一次完整创世结果。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha256
import json
from typing import Callable
from uuid import uuid4

from game.content import assemble_official_catalog

from game.content.catalog import (
    CHARACTER_PRESENCE_KIND_ID,
    COMMON_QUALITY_ID,
    DEFAULT_CHARACTER_TEMPLATE_ID,
    INITIAL_BACKPACK_CAPACITY,
    INITIAL_CURRENCY_AMOUNT,
    INITIAL_MEDICINE_QUANTITY,
    LOADOUT_PRESET_IDS,
    PRIMARY_CURRENCY_ID,
    SMALL_HEALTH_MEDICINE_ITEM_ID,
    SMALL_SPIRIT_MEDICINE_ITEM_ID,
    STARTER_WEAPON_ID,
    STARTER_WEAPON_ITEM_ID,
)
from game.core.gameplay import (
    EQUIPMENT_SLOT_IDS,
    WEAPON_SLOT_ID,
    IssueFunds,
    ItemAssetKind,
    ItemContainer,
    ItemInstance,
    ItemStack,
    LedgerAccount,
    LedgerAccountKind,
    LedgerEngine,
    LedgerState,
    LedgerTransaction,
    LoadoutPreset,
    LoadoutState,
    LootState,
    OpenLedgerAccount,
    ProvenanceLot,
    RuleContext,
    RewardClaimState,
    Ruleset,
    SeededRandomSource,
    SourceReceipt,
    TagSet,
    WeaponState,
    WorldPresence,
    WorldState,
    WorldTransaction,
    AddPresence,
    CharacterState,
    CharacterRosterState,
    InventoryState,
    weapon_state_data,
)
from game.core.gameplay.content import ContentRuntime

from .identity import (
    CharacterIdentityPolicy,
    CharacterNameSource,
    PreparedCharacterIdentity,
)
from .settings import CharacterSettingsState
from .dimension import (
    CHARACTER_WORLD_AGGREGATE,
    CharacterWorldState,
    assign_initial_world,
)


PRIMARY_LEDGER_ID = "ledger.primary"
MULTIVERSE_WORLD_STATE_ID = "world.multiverse"
PRIMARY_ISSUER_ACCOUNT_ID = "ledger_account.issuer.primary"
CHARACTER_SETTINGS_AGGREGATE = "snapshot.character_settings"
LOOT_AGGREGATE = "snapshot.loot"
REWARD_CLAIM_AGGREGATE = "snapshot.reward_claim"
WEAPON_AGGREGATE = "snapshot.weapon"
CHARACTER_CREATION_PROTOCOL_VERSION = "character_creation.v3"
IdFactory = Callable[[str], str]


def character_creation_context(*, trace_id: str, logical_time: datetime) -> RuleContext:
    """构造可重放的角色创世规则上下文。"""

    return RuleContext(
        trace_id,
        "rules.character_creation_v1",
        Ruleset("ruleset.standard"),
        logical_time,
        SeededRandomSource(trace_id),
    )


class CharacterCreationViolation(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CharacterCreationIds:
    character_id: str
    inventory_id: str
    special_container_id: str
    inscription_container_id: str
    armory_container_id: str
    backpack_container_id: str
    equipped_container_id: str
    health_stack_id: str
    spirit_stack_id: str
    weapon_asset_id: str
    wallet_account_id: str
    presence_id: str

    def __post_init__(self) -> None:
        for field_name, value in self.__dict__.items():
            if not str(value).strip():
                raise ValueError(f"角色创世 ID 不能为空：{field_name}")


@dataclass(frozen=True)
class CharacterCreationPlan:
    character: CharacterState
    name_source: CharacterNameSource
    inventory_id: str
    inventory: InventoryState
    loadout: LoadoutState
    ledger: LedgerState
    world: WorldState
    character_world: CharacterWorldState
    settings: CharacterSettingsState
    starter_weapon: WeaponState


class CharacterCreationPlanner:
    """只规划规则状态；数据库事务、防重和并发由应用层负责。"""

    def __init__(
        self,
        content: ContentRuntime,
        world_ids: tuple[str, ...] | None = None,
    ) -> None:
        self.content = content
        if content.world_runtime is None:
            raise ValueError("角色创世需要真实世界目录")
        candidates = tuple(world_ids or content.world_runtime.world_ids())
        normalized = tuple(content.world_runtime.require_world(value).id for value in candidates)
        if not normalized or len(normalized) != len(set(normalized)):
            raise ValueError("角色创世可降临世界必须存在且不能重复")
        self.world_ids = normalized
        self.ledger_engine = LedgerEngine(content.currencies)

    def build(
        self,
        *,
        transaction_id: str,
        identity: PreparedCharacterIdentity,
        ids: CharacterCreationIds,
        context: RuleContext,
        ledger: LedgerState | None = None,
        world: WorldState | None = None,
    ) -> CharacterCreationPlan:
        character = self.content.characters.create_character(
            character_id=ids.character_id,
            account_id=identity.account_id,
            name=identity.name,
            template_id=DEFAULT_CHARACTER_TEMPLATE_ID,
            created_at=context.logical_time,
        )
        receipt = SourceReceipt(
            f"receipt:{transaction_id}",
            "source.character_creation",
            character.id,
            context.logical_time,
        )
        starter_weapon = self.content.weapons.create_state(
            asset_id=ids.weapon_asset_id,
            definition_id=STARTER_WEAPON_ID,
            quality_id=COMMON_QUALITY_ID,
        )
        inventory = InventoryState(
            containers={
                ids.special_container_id: ItemContainer(
                    ids.special_container_id,
                    "container.special",
                    character.id,
                    required_item_tags=TagSet.of("storage.special"),
                ),
                ids.inscription_container_id: ItemContainer(
                    ids.inscription_container_id,
                    "container.inscription",
                    character.id,
                    accepted_kinds=frozenset({ItemAssetKind.INSTANCE}),
                    required_item_tags=TagSet.of("storage.inscription"),
                ),
                ids.armory_container_id: ItemContainer(
                    ids.armory_container_id,
                    "container.armory",
                    character.id,
                    accepted_kinds=frozenset({ItemAssetKind.INSTANCE}),
                    required_item_tags=TagSet.of("item.armament"),
                ),
                ids.backpack_container_id: ItemContainer(
                    ids.backpack_container_id,
                    "container.backpack",
                    character.id,
                    required_item_tags=TagSet.of("storage.backpack"),
                    maximum_space=INITIAL_BACKPACK_CAPACITY,
                ),
                ids.equipped_container_id: ItemContainer(
                    ids.equipped_container_id,
                    "container.equipped",
                    character.id,
                    accepted_kinds=frozenset({ItemAssetKind.INSTANCE}),
                    required_item_tags=TagSet.of("item.armament"),
                    maximum_assets=1 + len(EQUIPMENT_SLOT_IDS),
                ),
            },
            stacks={
                ids.health_stack_id: ItemStack(
                    ids.health_stack_id,
                    SMALL_HEALTH_MEDICINE_ITEM_ID,
                    ids.special_container_id,
                    (ProvenanceLot(receipt, INITIAL_MEDICINE_QUANTITY),),
                ),
                ids.spirit_stack_id: ItemStack(
                    ids.spirit_stack_id,
                    SMALL_SPIRIT_MEDICINE_ITEM_ID,
                    ids.special_container_id,
                    (ProvenanceLot(receipt, INITIAL_MEDICINE_QUANTITY),),
                ),
            },
            instances={
                ids.weapon_asset_id: ItemInstance(
                    ids.weapon_asset_id,
                    STARTER_WEAPON_ITEM_ID,
                    ids.equipped_container_id,
                    receipt,
                    weapon_state_data(starter_weapon),
                )
            },
        )
        presets = {
            preset_id: LoadoutPreset(
                preset_id,
                {WEAPON_SLOT_ID: ids.weapon_asset_id} if index == 0 else {},
            )
            for index, preset_id in enumerate(LOADOUT_PRESET_IDS)
        }
        loadout = LoadoutState(
            character.id,
            presets[LOADOUT_PRESET_IDS[0]].slots,
            presets=presets,
            active_preset_id=LOADOUT_PRESET_IDS[0],
        )
        next_ledger = self._build_ledger(
            transaction_id,
            character.id,
            ids.wallet_account_id,
            ledger or LedgerState(),
            context,
        )
        character_world = assign_initial_world(
            character.id,
            self.world_ids,
            random=context.random,
            logical_time=context.logical_time,
        )
        next_world = self._build_world(
            transaction_id,
            character.id,
            ids.presence_id,
            world or WorldState(MULTIVERSE_WORLD_STATE_ID),
            context,
            character_world.world_id,
        )
        return CharacterCreationPlan(
            character,
            identity.name_source,
            ids.inventory_id,
            inventory,
            loadout,
            next_ledger,
            next_world,
            character_world,
            CharacterSettingsState(character.id),
            starter_weapon,
        )

    def _build_ledger(
        self,
        transaction_id: str,
        character_id: str,
        wallet_account_id: str,
        state: LedgerState,
        context: RuleContext,
    ) -> LedgerState:
        operations: list[object] = []
        issuer = next(
            (
                account
                for account in state.accounts.values()
                if account.currency_id == PRIMARY_CURRENCY_ID
                and account.kind is LedgerAccountKind.ISSUER
            ),
            None,
        )
        expected_revisions: dict[str, int] = {}
        if issuer is None:
            issuer = LedgerAccount(
                PRIMARY_ISSUER_ACCOUNT_ID,
                "owner.system",
                MULTIVERSE_WORLD_STATE_ID,
                PRIMARY_CURRENCY_ID,
                LedgerAccountKind.ISSUER,
            )
            operations.append(OpenLedgerAccount(issuer))
        else:
            expected_revisions[issuer.id] = issuer.revision
        operations.extend(
            (
                OpenLedgerAccount(
                    LedgerAccount(
                        wallet_account_id,
                        "owner.character",
                        character_id,
                        PRIMARY_CURRENCY_ID,
                    )
                ),
                IssueFunds(issuer.id, wallet_account_id, INITIAL_CURRENCY_AMOUNT),
            )
        )
        outcome = self.ledger_engine.execute(
            LedgerTransaction(
                f"{transaction_id}:ledger",
                character_id,
                "economy.character_creation",
                tuple(operations),
                expected_revisions=expected_revisions,
            ),
            state=state,
            context=context,
        )
        if outcome.failure or outcome.value is None:
            failure = outcome.failure
            raise CharacterCreationViolation(
                failure.code if failure else "character_creation.ledger_failed",
                failure.message if failure else "初始经济状态创建失败",
            )
        return outcome.value.state

    def _build_world(
        self,
        transaction_id: str,
        character_id: str,
        presence_id: str,
        state: WorldState,
        context: RuleContext,
        world_id: str,
    ) -> WorldState:
        outcome = self.content.world_engine.execute(
            WorldTransaction(
                f"{transaction_id}:world",
                character_id,
                state.revision,
                (
                    AddPresence(
                        WorldPresence(
                            presence_id,
                            character_id,
                            CHARACTER_PRESENCE_KIND_ID,
                            self.content.world_runtime.spawn_position(world_id),
                        )
                    ),
                ),
            ),
            state=state,
            context=context,
        )
        if outcome.failure or outcome.value is None:
            failure = outcome.failure
            raise CharacterCreationViolation(
                failure.code if failure else "character_creation.world_failed",
                failure.message if failure else "初始世界位置创建失败",
            )
        return outcome.value.state


@dataclass(frozen=True)
class CharacterCreationRequest:
    transaction_id: str
    account_id: str
    requested_name: str = ""
    platform_name: str = ""

    def __post_init__(self) -> None:
        for field_name in ("transaction_id", "account_id"):
            value = str(getattr(self, field_name) or "").strip()
            if not value:
                raise ValueError(f"角色创世请求缺少 {field_name}")
            object.__setattr__(self, field_name, value)
        object.__setattr__(self, "requested_name", str(self.requested_name or ""))
        object.__setattr__(self, "platform_name", str(self.platform_name or ""))


@dataclass(frozen=True)
class CharacterCreationReceipt:
    transaction_id: str
    account_id: str
    name_source: CharacterNameSource
    character: CharacterState
    roster: CharacterRosterState
    inventory_id: str
    inventory: InventoryState
    loadout: LoadoutState
    ledger: LedgerState
    world: WorldState
    character_world: CharacterWorldState
    settings: CharacterSettingsState
    starter_weapon: WeaponState
    replayed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "name_source", CharacterNameSource(self.name_source))
        if self.character.account_id != self.account_id:
            raise ValueError("角色创世回执的账号与角色不一致")
        if self.character.id not in self.roster.character_ids:
            raise ValueError("角色创世回执的角色目录不包含新角色")
        if not self.inventory_id.strip():
            raise ValueError("角色创世回执缺少 inventory_id")


class CharacterCreationWorkflow:
    """向中立持久化协调器提供本游戏的创世规划和回执协议。"""

    def __init__(
        self,
        planner: CharacterCreationPlanner | None = None,
        *,
        identity_policy: CharacterIdentityPolicy | None = None,
        id_factory: IdFactory | None = None,
    ) -> None:
        self.planner = planner or CharacterCreationPlanner(assemble_official_catalog())
        self.identity_policy = identity_policy or CharacterIdentityPolicy()
        self.id_factory = id_factory or _uuid_id

    def codec_registrations(self) -> tuple[tuple[str, type[object]], ...]:
        return (
            ("product.character_name_source", CharacterNameSource),
            ("product.character_world", CharacterWorldState),
            ("product.character_settings", CharacterSettingsState),
            ("product.character_creation_receipt", CharacterCreationReceipt),
        )

    def transaction_id(self, request: object) -> str:
        return self._request(request).transaction_id

    def account_id(self, request: object) -> str:
        return self._request(request).account_id

    def fingerprint(self, request: object) -> str:
        value = self._request(request)
        payload = json.dumps(
            {
                "protocol": CHARACTER_CREATION_PROTOCOL_VERSION,
                "content": self.planner.content.report.content_fingerprint,
                "world_ids": self.planner.world_ids,
                "account_id": value.account_id,
                "requested_name": value.requested_name,
                "platform_name": value.platform_name,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(payload.encode("utf-8")).hexdigest()

    def receipt_type(self) -> type[object]:
        return CharacterCreationReceipt

    def mark_replayed(self, receipt: object) -> object:
        if not isinstance(receipt, CharacterCreationReceipt):
            raise TypeError("角色创世重放回执类型不正确")
        return replace(receipt, replayed=True)

    def ledger_aggregate_id(self) -> str:
        return PRIMARY_LEDGER_ID

    def world_aggregate_id(self) -> str:
        return MULTIVERSE_WORLD_STATE_ID

    def prepare(
        self,
        request: object,
        *,
        existing_character_ids: tuple[str, ...],
        ledger: LedgerState | None,
        world: WorldState | None,
        context: RuleContext,
    ) -> object:
        value = self._request(request)
        identity = self.identity_policy.prepare_creation(
            account_id=value.account_id,
            requested_name=value.requested_name,
            platform_name=value.platform_name,
            existing_character_ids=existing_character_ids,
        )
        return self.planner.build(
            transaction_id=value.transaction_id,
            identity=identity,
            ids=self._new_ids(),
            context=context,
            ledger=ledger,
            world=world,
        )

    @staticmethod
    def character(prepared: object) -> CharacterState:
        return CharacterCreationWorkflow._plan(prepared).character

    @staticmethod
    def inventory_id(prepared: object) -> str:
        return CharacterCreationWorkflow._plan(prepared).inventory_id

    @staticmethod
    def inventory(prepared: object) -> InventoryState:
        return CharacterCreationWorkflow._plan(prepared).inventory

    @staticmethod
    def loadout(prepared: object) -> LoadoutState:
        return CharacterCreationWorkflow._plan(prepared).loadout

    @staticmethod
    def ledger(prepared: object) -> LedgerState:
        return CharacterCreationWorkflow._plan(prepared).ledger

    @staticmethod
    def world(prepared: object) -> WorldState:
        return CharacterCreationWorkflow._plan(prepared).world

    @staticmethod
    def extra_snapshots(prepared: object) -> tuple[tuple[str, str, object], ...]:
        plan = CharacterCreationWorkflow._plan(prepared)
        return (
            (CHARACTER_WORLD_AGGREGATE, plan.character.id, plan.character_world),
            (CHARACTER_SETTINGS_AGGREGATE, plan.character.id, plan.settings),
            (LOOT_AGGREGATE, plan.character.id, LootState(plan.character.id)),
            (
                REWARD_CLAIM_AGGREGATE,
                plan.character.id,
                RewardClaimState(plan.character.id),
            ),
            (WEAPON_AGGREGATE, plan.starter_weapon.asset_id, plan.starter_weapon),
        )

    def build_receipt(
        self,
        request: object,
        prepared: object,
        roster: CharacterRosterState,
    ) -> object:
        value = self._request(request)
        plan = self._plan(prepared)
        return CharacterCreationReceipt(
            value.transaction_id,
            value.account_id,
            plan.name_source,
            plan.character,
            roster,
            plan.inventory_id,
            plan.inventory,
            plan.loadout,
            plan.ledger,
            plan.world,
            plan.character_world,
            plan.settings,
            plan.starter_weapon,
        )

    def _new_ids(self) -> CharacterCreationIds:
        character_id = self.id_factory("character")
        return CharacterCreationIds(
            character_id,
            character_id,
            self.id_factory("special"),
            self.id_factory("inscription"),
            self.id_factory("armory"),
            self.id_factory("backpack"),
            self.id_factory("equipped"),
            self.id_factory("health_stack"),
            self.id_factory("spirit_stack"),
            self.id_factory("weapon"),
            self.id_factory("wallet"),
            self.id_factory("presence"),
        )

    @staticmethod
    def _request(value: object) -> CharacterCreationRequest:
        if not isinstance(value, CharacterCreationRequest):
            raise TypeError("角色创世请求类型不正确")
        return value

    @staticmethod
    def _plan(value: object) -> CharacterCreationPlan:
        if not isinstance(value, CharacterCreationPlan):
            raise TypeError("角色创世计划类型不正确")
        return value


def _uuid_id(kind: str) -> str:
    return f"{kind}-{uuid4().hex}"


__all__ = [
    "CHARACTER_CREATION_PROTOCOL_VERSION",
    "CHARACTER_SETTINGS_AGGREGATE",
    "CharacterCreationIds",
    "CharacterCreationPlan",
    "CharacterCreationPlanner",
    "CharacterCreationReceipt",
    "CharacterCreationRequest",
    "CharacterCreationViolation",
    "CharacterCreationWorkflow",
    "character_creation_context",
    "PRIMARY_ISSUER_ACCOUNT_ID",
    "PRIMARY_LEDGER_ID",
    "MULTIVERSE_WORLD_STATE_ID",
    "LOOT_AGGREGATE",
    "REWARD_CLAIM_AGGREGATE",
    "WEAPON_AGGREGATE",
]
