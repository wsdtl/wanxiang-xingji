"""游戏数据库、内容和服务的启动装配入口。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from game.content import (
    DIMENSIONAL_DISASTER_BATTLE_ROUNDS,
    DEFAULT_WORLD_ID,
    DimensionalDisasterCatalog,
    OfficialContent,
    PLAYABLE_WORLD_DEFINITIONS,
    WORLD_LORE_CATALOG,
    WorldViewCatalog,
    assemble_official_catalog,
    build_dimensional_disaster_catalog,
)
from game.core.account import AccountEngine, ExternalIdentity, IdentityEvidence
from game.core.gameplay import (
    AttributeResolver,
    CharacterEngine,
    CharacterItemUseEngine,
    CharacterProjector,
    CharacterState,
    InventoryEngine,
    InventoryAbilityExecutor,
    InscriptionEngine,
    InscriptionPreference,
    LedgerEngine,
    LoadoutEngine,
    RewardSettlementEngine,
    GameplayExecutor,
    WeaponEngine,
    PartyEngine,
)
from game.core.persistence import (
    ACTIVITY_AGGREGATE,
    ACTION_AGGREGATE,
    BattleReportStore,
    CHARACTER_AGGREGATE,
    ConcurrencyConflict,
    ContentActivationStore,
    INVENTORY_AGGREGATE,
    INSCRIPTION_PREFERENCE_AGGREGATE,
    LEDGER_AGGREGATE,
    LOADOUT_AGGREGATE,
    LOOT_AGGREGATE,
    MessageFlowStore,
    PersistenceError,
    NotificationInboxService,
    ProjectionStore,
    PersistedActivityService,
    PersistedActionService,
    PersistedAccountService,
    PersistedCharacterCreationService,
    PersistedCharacterService,
    PersistedCharacterItemUseService,
    PersistedInscriptionService,
    PersistedItemUseService,
    PersistedInventoryProtectionService,
    PersistedWeaponItemUseService,
    PersistedLoadoutService,
    PersistedRewardSettlementService,
    PersistenceRetentionService,
    PersistedSocialService,
    PersistedPartyAdmissionService,
    PersistedPartyService,
    PARTY_AGGREGATE,
    REWARD_CLAIM_AGGREGATE,
    RewardSettlementStorageKeys,
    SnapshotRepository,
    SqliteDatabase,
    WORLD_AGGREGATE,
    WEAPON_AGGREGATE,
    gameplay_snapshot_codec,
)
from game.rules.character import (
    CHARACTER_WORLD_AGGREGATE,
    CHARACTER_SETTINGS_AGGREGATE,
    CharacterWorldState,
    CharacterCreationPlanner,
    CharacterCreationWorkflow,
    CharacterSettingsState,
    WorldShiftResult,
)
from game.rules.activity import (
    GLOBAL_ACTIVITY_SCOPE_ID,
    GlobalActivityCatalog,
    global_activity_catalog,
)
from game.rules.combat import PlayerCombatProjector
from game.rules.companion import (
    COMPANION_ROSTER_AGGREGATE,
    COMPANION_SANCTUARY_AGGREGATE,
    CompanionCombatProjector,
    CompanionEngine,
    CompanionGrowthEngine,
    PlayerBattleLineupProjector,
)
from game.features.exploration import (
    ExplorationFeature,
    ExplorationStorageKinds,
)
from game.features.world_progress import (
    WorldProgressFeature,
    WorldProgressStorageKinds,
)
from game.features.world_lore import (
    WorldLoreFeature,
)
from game.features.world_travel import (
    WorldTravelFeature,
    WorldTravelStorageKinds,
)
from game.features.dimensional_disaster import (
    DimensionalDisasterFeature,
    DimensionalDisasterStorageKinds,
)
from game.features.data_lifecycle import DataLifecycleFeature, DataLifecycleTask
from game.features.breakthrough import (
    BreakthroughFeature,
    BreakthroughStorageKinds,
)
from game.features.economy import (
    EconomyFeature,
    EconomyStorageKinds,
)
from game.features.draw import (
    DRAW_HISTORY_AGGREGATE,
    DrawFeature,
    DrawStorageKinds,
)
from game.features.lottery import (
    LOTTERY_AGGREGATE,
    LotteryFeature,
    LotteryStorageKinds,
)
from game.features.battle_report import BattleReportBuilder, BattleReportService
from game.features.build_trial import BuildTrialFeature, BuildTrialStorageKinds
from game.features.companion import (
    CompanionFeature,
    CompanionGrowthSettlement,
    CompanionSanctuaryBattleSimulator,
    CompanionStorageKinds,
)
from game.features.rest import RestFeature, RestStorageKinds
from game.features.sparring import SparringFeature, SparringStorageKinds
from game.features.special_items import (
    SpecialItemUseService,
)
from game.features.equipment_blueprint import (
    EquipmentBlueprintFeature,
)
from game.features.exchange import (
    CovenantExchangeFeature,
)
from game.features.dimension_shift import (
    DimensionShiftFeature,
    DimensionShiftStorageKinds,
)
from game.features.player import (
    CharacterCreationCommandResult,
    CharacterOverview,
    CharacterOverviewResult,
    CurrentCharacterResult,
    GlobalActivityViewsResult,
    NotificationMarkResult,
    PlayerFeature,
    PlayerOwnershipError,
    PlayerReminderDetails,
    PlayerReminderDetailsResult,
    PlayerReplyState,
    PlayerReplyStateResult,
    PlayerStorageKinds,
)
from game.features.party import PartyFeature
from game.features.party_battle import (
    PartyBattleFeature,
    PartyBattleStorageKinds,
)
from game.features.catalog import feature_snapshot_codec_registrations
from game.features.party_sparring import (
    PartySparringFeature,
    PartySparringStorageKinds,
)
from game.features.party.service import PARTY_SCOPE_ID
from game.rules.exploration import EXPLORATION_AGGREGATE
from game.rules.world_progress import WORLD_PROGRESS_AGGREGATE
from game.rules.economy import MARKET_AGGREGATE
from game.rules.sparring import SparringBattleSimulator
from game.rules.party_sparring import PartySparringBattleSimulator
from launch import C, OnEvent, config, logger
from launch.adapter import MessageIdentity


@dataclass(frozen=True)
class GameServices:
    """命令层可以使用的完整游戏服务集合。"""

    database: SqliteDatabase
    accounts: PersistedAccountService
    characters: PersistedCharacterService
    character_creation: PersistedCharacterCreationService
    character_projector: CharacterProjector
    player_combat: PlayerCombatProjector
    inscriptions: PersistedInscriptionService
    item_use: PersistedItemUseService
    character_item_use: PersistedCharacterItemUseService
    weapon_item_use: PersistedWeaponItemUseService
    special_item_use: SpecialItemUseService
    equipment_blueprints: EquipmentBlueprintFeature
    covenant_exchange: CovenantExchangeFeature
    inventory_engine: InventoryEngine
    inventory_protection: PersistedInventoryProtectionService
    player: PlayerFeature
    dimension_shift: DimensionShiftFeature
    breakthrough: BreakthroughFeature
    loadouts: PersistedLoadoutService
    notifications: NotificationInboxService
    activities: PersistedActivityService
    actions: PersistedActionService
    global_activities: GlobalActivityCatalog
    battle_reports: BattleReportService
    data_lifecycle: DataLifecycleFeature
    build_trials: BuildTrialFeature
    dimensional_disasters: DimensionalDisasterFeature
    party: PartyFeature
    party_battles: PartyBattleFeature
    party_sparring: PartySparringFeature
    companions: CompanionFeature
    player_lineup: PlayerBattleLineupProjector
    exploration: ExplorationFeature
    world_progress: WorldProgressFeature
    world_lore: WorldLoreFeature
    world_travel: WorldTravelFeature
    rest: RestFeature
    sparring: SparringFeature
    economy: EconomyFeature
    lottery: LotteryFeature
    draw: DrawFeature
    world_views: WorldViewCatalog
    content: OfficialContent

    def world_view(
        self,
        character_world: CharacterWorldState | str,
    ) -> OfficialContent:
        """按角色当前真实世界读取缓存展示投影。"""

        world_id = (
            character_world.world_id
            if isinstance(character_world, CharacterWorldState)
            else character_world
        )
        return self.world_views.require(world_id)

    def create_character(
        self,
        evidence: IdentityEvidence,
        *,
        requested_name: str = "",
        platform_name: str = "",
    ) -> CharacterCreationCommandResult:
        """通过玩家业务创建角色，并统一映射基础设施异常。"""

        try:
            return self.player.create_character(
                evidence,
                requested_name=requested_name,
                platform_name=platform_name,
            )
        except ConcurrencyConflict:
            current = self.player.load_current_character(evidence)
            return CharacterCreationCommandResult(
                "existing",
                existing_character=current.character,
            )
        except PersistenceError as exc:
            logger.opt(colors=True, exception=exc).error(
                C.join(
                    C.fail("角色创世持久化失败"),
                    C.kv("evidence", evidence.id),
                )
            )
            return CharacterCreationCommandResult("failed")

    def load_current_character(
        self,
        evidence: IdentityEvidence,
    ) -> CurrentCharacterResult:
        """通过玩家业务解析当前身份。"""
        try:
            return self.player.load_current_character(evidence)
        except PersistenceError as exc:
            logger.opt(colors=True, exception=exc).error(
                C.join(
                    C.fail("当前角色读取失败"),
                    C.kv("evidence", evidence.id),
                )
            )
            return CurrentCharacterResult("failed")

    def load_character_overview(
        self,
        character: CharacterState,
    ) -> CharacterOverviewResult:
        """通过玩家业务读取角色状态页一致快照。"""
        try:
            return self.player.load_character_overview(character)
        except (PersistenceError, PlayerOwnershipError) as exc:
            logger.opt(colors=True, exception=exc).error(
                C.join(
                    C.fail("角色状态读取失败"),
                    C.kv("character", character.id),
                )
            )
            return CharacterOverviewResult("failed")

    def load_character_settings(self, character_id: str) -> CharacterSettingsState:
        """读取角色个人展示和自动操作设置。"""

        return self.player.load_settings(character_id)

    def load_player_reply_state(
        self,
        evidence: IdentityEvidence,
    ) -> PlayerReplyStateResult:
        """只读加载当前人物头、通知摘要和待领取行动数量。"""

        try:
            return self.player.load_reply_state(evidence)
        except PersistenceError as exc:
            logger.opt(colors=True, exception=exc).error(
                C.join(
                    C.fail("玩家回复状态读取失败"),
                    C.kv("evidence", evidence.id),
                )
            )
            return PlayerReplyStateResult("failed")

    def shift_character_world(
        self,
        character_id: str,
        target_world_id: str,
        *,
        logical_time: datetime,
    ) -> WorldShiftResult:
        """转发到跃迁业务的唯一写入口。"""

        return self.dimension_shift.shift(
            character_id,
            target_world_id,
            logical_time=logical_time,
        )

    def set_mood_header_enabled(
        self,
        character_id: str,
        enabled: bool,
        *,
        logical_time: datetime,
    ) -> CharacterSettingsState:
        """原子更新彩色人物头开关；重复设置相同值不增加版本。"""

        return self.player.set_setting(
            character_id,
            "mood_header_enabled",
            enabled,
            logical_time=logical_time,
        )

    def set_auto_use_medicine(
        self,
        character_id: str,
        enabled: bool,
        *,
        logical_time: datetime,
    ) -> CharacterSettingsState:
        """原子更新探险自动用药开关。"""

        return self.player.set_setting(
            character_id,
            "auto_use_medicine",
            enabled,
            logical_time=logical_time,
        )

    def set_inscription_show_original_name(
        self,
        character_id: str,
        show_original_name: bool,
        *,
        logical_time: datetime,
    ) -> InscriptionPreference:
        """初始化并更新当前角色的铭刻原名展示偏好。"""

        self.inscriptions.initialize_preference(character_id, logical_time=logical_time)
        return self.inscriptions.set_show_original_name(
            character_id,
            show_original_name,
            logical_time=logical_time,
        )

    def load_inscription_preference(
        self,
        character_id: str,
        *,
        logical_time: datetime,
    ) -> InscriptionPreference:
        """读取铭刻偏好；旧角色没有快照时按默认值补齐。"""

        return self.inscriptions.initialize_preference(
            character_id,
            logical_time=logical_time,
        )

    def mark_notification_read(
        self,
        character: CharacterState,
        notification_id: str,
        expected_revision: int,
        *,
        logical_time: datetime,
    ) -> NotificationMarkResult:
        """只允许当前角色标记自己账号的有效未读通知。"""

        try:
            return self.player.mark_notification_read(
                character,
                notification_id,
                expected_revision=expected_revision,
                logical_time=logical_time,
            )
        except ConcurrencyConflict:
            return NotificationMarkResult("stale")

    def load_player_reminder_details(
        self,
        character: CharacterState,
        *,
        logical_time: datetime,
        notification_limit: int = 20,
    ) -> PlayerReminderDetailsResult:
        """只读加载未读通知和待领取行动，不改变任何状态。"""

        try:
            return self.player.load_reminder_details(
                character,
                logical_time=logical_time,
                notification_limit=notification_limit,
            )
        except PersistenceError as exc:
            logger.opt(colors=True, exception=exc).error(
                C.join(
                    C.fail("玩家提醒明细读取失败"),
                    C.kv("character", character.id),
                )
            )
            return PlayerReminderDetailsResult("failed")

    def load_global_activity_views(
        self,
        *,
        logical_time: datetime,
    ) -> GlobalActivityViewsResult:
        """只读列出当前开放且已经注册的全部全服活动。"""

        try:
            return self.player.load_global_activity_views(logical_time=logical_time)
        except PersistenceError as exc:
            logger.opt(colors=True, exception=exc).error(
                C.join(C.fail("全服活动读取失败"), C.kv("scope", GLOBAL_ACTIVITY_SCOPE_ID))
            )
            return GlobalActivityViewsResult("failed")


def message_identity_evidence(
    identity: MessageIdentity,
    *,
    logical_time: datetime,
) -> IdentityEvidence:
    """把驱动器公共身份事实转换成账号底座凭据。"""

    def convert(claim) -> ExternalIdentity:
        return ExternalIdentity(*claim.key)

    return IdentityEvidence(
        id=identity.evidence_id,
        primary=convert(identity.primary),
        aliases=tuple(convert(claim) for claim in identity.aliases),
        source_kind=identity.source_kind,
        logical_time=logical_time,
    )


_services: GameServices | None = None
_services_overridden = False
_message_flow_store: MessageFlowStore | None = None
_message_flow_store_overridden = False


@dataclass(frozen=True)
class _ContentAssembly:
    world_views: WorldViewCatalog
    content: OfficialContent
    disasters: DimensionalDisasterCatalog
    global_activities: GlobalActivityCatalog
    workflow: CharacterCreationWorkflow
    snapshots: SnapshotRepository


@dataclass(frozen=True)
class _FoundationAssembly:
    inventory_engine: InventoryEngine
    inventory_protection: PersistedInventoryProtectionService
    character_projector: CharacterProjector
    player_combat: PlayerCombatProjector
    companion_engine: CompanionEngine
    companion_growth: CompanionGrowthEngine
    companion_growth_settlement: CompanionGrowthSettlement
    companion_combat: CompanionCombatProjector
    player_lineup: PlayerBattleLineupProjector
    item_use: PersistedItemUseService
    character_item_use: PersistedCharacterItemUseService
    weapon_item_use: PersistedWeaponItemUseService
    special_item_use: SpecialItemUseService
    equipment_blueprints: EquipmentBlueprintFeature
    covenant_exchange: CovenantExchangeFeature
    actions: PersistedActionService
    inscriptions: PersistedInscriptionService
    loadouts: PersistedLoadoutService
    ledger_engine: LedgerEngine
    reward_settlement: PersistedRewardSettlementService


def _assemble_content(world_id: str) -> _ContentAssembly:
    catalog = assemble_official_catalog()
    world_views = WorldViewCatalog(catalog, PLAYABLE_WORLD_DEFINITIONS)
    content = world_views.require(world_id)
    disasters = build_dimensional_disaster_catalog()
    disasters.validate(catalog, world_views.world_ids())
    for warning in disasters.audit().warnings:
        logger.opt(colors=True).warning(C.warn(warning))

    registered_global_activities = GlobalActivityCatalog()
    for registration in global_activity_catalog.registrations():
        registered_global_activities.register(registration)
    for view in world_views.latest_views():
        registered_global_activities.validate(
            content.catalog.activities,
            view.projector,
        )

    workflow = CharacterCreationWorkflow(
        CharacterCreationPlanner(
            content.catalog,
            world_views.world_ids(),
        )
    )
    snapshots = SnapshotRepository(
        gameplay_snapshot_codec(
            (
                *workflow.codec_registrations(),
                *feature_snapshot_codec_registrations(),
            )
        )
    )
    return _ContentAssembly(
        world_views,
        content,
        disasters,
        registered_global_activities,
        workflow,
        snapshots,
    )


def _assemble_foundation(
    database: SqliteDatabase,
    content: OfficialContent,
    snapshots: SnapshotRepository,
) -> _FoundationAssembly:
    inventory_engine = InventoryEngine(content.catalog.items)
    inventory_protection = PersistedInventoryProtectionService(
        database,
        inventory_engine,
        snapshots,
    )
    character_projector = CharacterProjector(
        content.catalog.characters,
        AttributeResolver(content.catalog.attributes),
        content.catalog.resources,
        ability_ids=frozenset(content.catalog.abilities.ids()),
        trigger_ids=frozenset(content.catalog.triggers.ids()),
        interceptor_ids=frozenset(content.catalog.interceptors.ids()),
        target_constraint_ids=frozenset(content.catalog.target_constraints.ids()),
    )
    player_combat = PlayerCombatProjector(content.catalog, character_projector)
    companion_engine = CompanionEngine(content.companions)
    companion_growth = CompanionGrowthEngine(content.companions)
    companion_growth_settlement = CompanionGrowthSettlement(
        snapshots,
        COMPANION_ROSTER_AGGREGATE,
        companion_growth,
    )
    companion_combat = CompanionCombatProjector(
        content.catalog,
        content.companions,
    )
    player_lineup = PlayerBattleLineupProjector(
        content.catalog,
        player_combat,
        companion_combat,
    )
    item_use = PersistedItemUseService(
        database,
        CharacterItemUseEngine(
            InventoryAbilityExecutor(
                content.catalog.items,
                inventory_engine,
                GameplayExecutor(
                    content.catalog.ability_engine,
                    content.catalog.trigger_engine,
                ),
            ),
            CharacterEngine(content.catalog.characters),
            character_projector,
        ),
        snapshots,
    )
    character_item_use = PersistedCharacterItemUseService(
        database,
        content.catalog.items,
        inventory_engine,
        CharacterEngine(content.catalog.characters),
        snapshots,
    )
    weapon_engine = WeaponEngine(content.catalog.weapons)
    weapon_item_use = PersistedWeaponItemUseService(
        database,
        content.catalog.items,
        inventory_engine,
        weapon_engine,
        snapshots,
    )
    special_item_use = SpecialItemUseService(
        database,
        content.catalog.items,
        inventory_engine,
        snapshots,
        INVENTORY_AGGREGATE,
    )
    equipment_blueprints = EquipmentBlueprintFeature(
        database,
        content.catalog,
        snapshots,
        inventory_engine,
        INVENTORY_AGGREGATE,
    )
    covenant_exchange = CovenantExchangeFeature(
        database,
        content.catalog,
        snapshots,
        inventory_engine,
        INVENTORY_AGGREGATE,
    )
    actions = PersistedActionService(
        database,
        content.catalog.action_engine,
        snapshots,
    )
    inscriptions = PersistedInscriptionService(
        database,
        InscriptionEngine(
            content.catalog.items,
            content.catalog.weapons,
            content.catalog.equipment,
        ),
        snapshots,
    )
    loadouts = PersistedLoadoutService(
        database,
        LoadoutEngine(
            content.catalog.equipment.slots,
            content.catalog.items,
            inventory_engine,
        ),
        snapshots,
    )
    ledger_engine = LedgerEngine(content.catalog.currencies)
    reward_engine = RewardSettlementEngine(
        inventory=inventory_engine,
        ledger=ledger_engine,
        character=CharacterEngine(content.catalog.characters),
        weapon=weapon_engine,
    )
    reward_settlement = PersistedRewardSettlementService(
        database,
        reward_engine,
        snapshots,
    )
    return _FoundationAssembly(
        inventory_engine,
        inventory_protection,
        character_projector,
        player_combat,
        companion_engine,
        companion_growth,
        companion_growth_settlement,
        companion_combat,
        player_lineup,
        item_use,
        character_item_use,
        weapon_item_use,
        special_item_use,
        equipment_blueprints,
        covenant_exchange,
        actions,
        inscriptions,
        loadouts,
        ledger_engine,
        reward_settlement,
    )


def build_game_services(
    *,
    database_path: Path | str | None = None,
    busy_timeout_ms: int | None = None,
    identity_secret: str | None = None,
    world_id: str = DEFAULT_WORLD_ID,
) -> GameServices:
    """组装一次完整服务集合；数据库初始化由生命周期显式执行。"""

    secret = str(
        identity_secret
        if identity_secret is not None
        else config.get("ACCOUNT_IDENTITY_SECRET", "")
    ).strip()
    if len(secret.encode("utf-8")) < 16:
        raise ValueError("ACCOUNT_IDENTITY_SECRET 至少需要 16 字节")
    database = SqliteDatabase(
        database_path or config.database.path,
        busy_timeout_ms=(
            busy_timeout_ms
            if busy_timeout_ms is not None
            else config.database.busy_timeout_ms
        ),
    )
    content_assembly = _assemble_content(world_id)
    world_views = content_assembly.world_views
    content = content_assembly.content
    disaster_catalog = content_assembly.disasters
    registered_global_activities = content_assembly.global_activities
    workflow = content_assembly.workflow
    snapshots = content_assembly.snapshots
    foundation = _assemble_foundation(database, content, snapshots)
    inventory_engine = foundation.inventory_engine
    inventory_protection = foundation.inventory_protection
    character_projector = foundation.character_projector
    player_combat = foundation.player_combat
    companion_engine = foundation.companion_engine
    companion_growth = foundation.companion_growth
    companion_growth_settlement = foundation.companion_growth_settlement
    companion_combat = foundation.companion_combat
    player_lineup = foundation.player_lineup
    item_use_service = foundation.item_use
    character_item_use_service = foundation.character_item_use
    weapon_item_use_service = foundation.weapon_item_use
    special_item_use_service = foundation.special_item_use
    equipment_blueprints = foundation.equipment_blueprints
    covenant_exchange = foundation.covenant_exchange
    action_service = foundation.actions
    inscription_service = foundation.inscriptions
    loadout_service = foundation.loadouts
    ledger_engine = foundation.ledger_engine
    reward_settlement = foundation.reward_settlement
    world_progress = WorldProgressFeature(
        database,
        content,
        world_views,
        snapshots,
        reward_settlement,
        ProjectionStore(database, snapshots),
        WorldProgressStorageKinds(
            progress=WORLD_PROGRESS_AGGREGATE,
            inventory=INVENTORY_AGGREGATE,
            ledger=LEDGER_AGGREGATE,
            reward_claim=REWARD_CLAIM_AGGREGATE,
        ),
        RewardSettlementStorageKeys,
    )
    world_lore = WorldLoreFeature(
        database,
        WORLD_LORE_CATALOG,
        snapshots,
        world_progress.view,
        world_views.world_ids(),
    )
    battle_report_builder = BattleReportBuilder(content, world_views)
    battle_reports = BattleReportService(
        database,
        BattleReportStore(database),
        battle_report_builder,
    )
    persistence_retention = PersistenceRetentionService(database)
    data_lifecycle = DataLifecycleFeature(
        (
            DataLifecycleTask(
                "data.battle_reports",
                lambda logical_time: battle_reports.cleanup(logical_time=logical_time),
            ),
            DataLifecycleTask(
                "data.persistence",
                lambda logical_time: persistence_retention.cleanup(logical_time=logical_time),
            ),
        )
    )
    build_trials = BuildTrialFeature(
        database,
        content,
        world_views,
        snapshots,
        battle_reports,
        player_lineup,
        BuildTrialStorageKinds(
            character=CHARACTER_AGGREGATE,
            character_world=CHARACTER_WORLD_AGGREGATE,
            inventory=INVENTORY_AGGREGATE,
            loadout=LOADOUT_AGGREGATE,
            companion_roster=COMPANION_ROSTER_AGGREGATE,
            inscription_preference=INSCRIPTION_PREFERENCE_AGGREGATE,
        ),
    )
    companions = CompanionFeature(
        database,
        content,
        world_views,
        snapshots,
        inventory_engine,
        battle_reports,
        companion_engine,
        CompanionSanctuaryBattleSimulator(
            content.catalog,
            player_lineup,
            companion_combat,
        ),
        CompanionStorageKinds(
            action=ACTION_AGGREGATE,
            character=CHARACTER_AGGREGATE,
            character_world=CHARACTER_WORLD_AGGREGATE,
            exploration=EXPLORATION_AGGREGATE,
            inventory=INVENTORY_AGGREGATE,
            loadout=LOADOUT_AGGREGATE,
            roster=COMPANION_ROSTER_AGGREGATE,
            sanctuary=COMPANION_SANCTUARY_AGGREGATE,
            world=WORLD_AGGREGATE,
            inscription_preference=INSCRIPTION_PREFERENCE_AGGREGATE,
        ),
        companion_growth,
    )
    world_travel = WorldTravelFeature(
        database,
        content,
        snapshots,
        WorldTravelStorageKinds(
            action=ACTION_AGGREGATE,
            exploration=EXPLORATION_AGGREGATE,
            world=WORLD_AGGREGATE,
            character_world=CHARACTER_WORLD_AGGREGATE,
        ),
    )
    exploration = ExplorationFeature(
        database,
        content,
        world_views,
        snapshots,
        reward_settlement,
        inventory_engine,
        player_lineup,
        battle_reports,
        ExplorationStorageKinds(
            ACTION_AGGREGATE,
            CHARACTER_AGGREGATE,
            INVENTORY_AGGREGATE,
            LOADOUT_AGGREGATE,
            COMPANION_ROSTER_AGGREGATE,
            LOOT_AGGREGATE,
            REWARD_CLAIM_AGGREGATE,
            WEAPON_AGGREGATE,
            WORLD_AGGREGATE,
            CHARACTER_WORLD_AGGREGATE,
            INSCRIPTION_PREFERENCE_AGGREGATE,
        ),
        RewardSettlementStorageKeys,
        companion_growth_settlement,
        world_progress,
    )
    dimensional_disasters = DimensionalDisasterFeature(
        database,
        content,
        world_views,
        disaster_catalog,
        world_views.world_ids(),
        snapshots,
        reward_settlement,
        player_lineup,
        battle_reports,
        DimensionalDisasterStorageKinds(
            ACTION_AGGREGATE,
            ACTIVITY_AGGREGATE,
            CHARACTER_AGGREGATE,
            CHARACTER_WORLD_AGGREGATE,
            EXPLORATION_AGGREGATE,
            INVENTORY_AGGREGATE,
            LOADOUT_AGGREGATE,
            COMPANION_ROSTER_AGGREGATE,
            REWARD_CLAIM_AGGREGATE,
            INSCRIPTION_PREFERENCE_AGGREGATE,
        ),
        RewardSettlementStorageKeys,
        companion_growth_settlement,
        maximum_battle_rounds=DIMENSIONAL_DISASTER_BATTLE_ROUNDS,
        timezone=config.project.timezone,
    )
    economy = EconomyFeature(
        database,
        content.catalog,
        snapshots,
        inventory_engine,
        ledger_engine,
        EconomyStorageKinds(
            INVENTORY_AGGREGATE,
            LOADOUT_AGGREGATE,
            LEDGER_AGGREGATE,
            MARKET_AGGREGATE,
        ),
        market_item_policies=content.market_item_policies,
    )
    lottery = LotteryFeature(
        database,
        snapshots,
        ledger_engine,
        storage=LotteryStorageKinds(
            LOTTERY_AGGREGATE,
            LEDGER_AGGREGATE,
        ),
        timezone=config.project.timezone,
    )
    draw = DrawFeature(
        database,
        content,
        snapshots,
        inventory_engine,
        reward_settlement,
        DrawStorageKinds(
            DRAW_HISTORY_AGGREGATE,
            INVENTORY_AGGREGATE,
            LEDGER_AGGREGATE,
            LOOT_AGGREGATE,
            REWARD_CLAIM_AGGREGATE,
        ),
        RewardSettlementStorageKeys,
    )
    rest = RestFeature(
        database,
        content.catalog,
        snapshots,
        action_service,
        CharacterEngine(content.catalog.characters),
        character_projector,
        RestStorageKinds(
            ACTION_AGGREGATE,
            CHARACTER_AGGREGATE,
            INVENTORY_AGGREGATE,
            LOADOUT_AGGREGATE,
            EXPLORATION_AGGREGATE,
        ),
    )
    accounts = PersistedAccountService(
        database,
        AccountEngine(lambda: f"account-{uuid4().hex}"),
        secret,
    )
    characters = PersistedCharacterService(database)
    character_creation_service = PersistedCharacterCreationService(
        database,
        workflow,
        snapshots=snapshots,
    )
    notifications = NotificationInboxService(database)
    activities = PersistedActivityService(database, content.catalog.activity_engine)
    player = PlayerFeature(
        database,
        accounts,
        characters,
        character_creation_service,
        snapshots,
        notifications,
        activities,
        registered_global_activities,
        PlayerStorageKinds(
            character=CHARACTER_AGGREGATE,
            inventory=INVENTORY_AGGREGATE,
            loadout=LOADOUT_AGGREGATE,
            ledger=LEDGER_AGGREGATE,
            world=WORLD_AGGREGATE,
            character_world=CHARACTER_WORLD_AGGREGATE,
            action=ACTION_AGGREGATE,
            settings=CHARACTER_SETTINGS_AGGREGATE,
            inscription_preference=INSCRIPTION_PREFERENCE_AGGREGATE,
        ),
    )
    dimension_shift = DimensionShiftFeature(
        database,
        content,
        world_views,
        snapshots,
        inventory_engine,
        DimensionShiftStorageKinds(
            character_world=CHARACTER_WORLD_AGGREGATE,
            world=WORLD_AGGREGATE,
            action=ACTION_AGGREGATE,
            exploration=EXPLORATION_AGGREGATE,
            inventory=INVENTORY_AGGREGATE,
        ),
    )
    breakthrough = BreakthroughFeature(
        database,
        content,
        snapshots,
        inventory_engine,
        CharacterEngine(content.catalog.characters),
        BreakthroughStorageKinds(
            character=CHARACTER_AGGREGATE,
            inventory=INVENTORY_AGGREGATE,
        ),
    )
    social = PersistedSocialService(database, content.catalog.social_engine, snapshots)
    party_engine = PartyEngine(content.catalog.parties)
    party_persistence = PersistedPartyService(database, party_engine, snapshots)
    party_admissions = PersistedPartyAdmissionService(
        database,
        content.catalog.social_engine,
        party_engine,
        snapshots,
    )
    party = PartyFeature(
        party_persistence,
        party_admissions,
        social,
        content.catalog.parties,
    )
    party_battles = PartyBattleFeature(
        database,
        content,
        world_views,
        snapshots,
        reward_settlement,
        battle_reports,
        player_lineup,
        PartyBattleStorageKinds(
            party=PARTY_AGGREGATE,
            character=CHARACTER_AGGREGATE,
            inventory=INVENTORY_AGGREGATE,
            loadout=LOADOUT_AGGREGATE,
            companion_roster=COMPANION_ROSTER_AGGREGATE,
            action=ACTION_AGGREGATE,
            exploration=EXPLORATION_AGGREGATE,
            reward_claim=REWARD_CLAIM_AGGREGATE,
            weapon=WEAPON_AGGREGATE,
            character_world=CHARACTER_WORLD_AGGREGATE,
            inscription_preference=INSCRIPTION_PREFERENCE_AGGREGATE,
        ),
        RewardSettlementStorageKeys,
        companion_growth_settlement,
        party_scope_id=PARTY_SCOPE_ID,
        timezone=config.project.timezone,
    )
    party_sparring = PartySparringFeature(
        database,
        content,
        world_views,
        snapshots,
        social,
        battle_reports,
        PartySparringBattleSimulator(content.catalog, player_lineup),
        PartySparringStorageKinds(
            party=PARTY_AGGREGATE,
            character=CHARACTER_AGGREGATE,
            inventory=INVENTORY_AGGREGATE,
            loadout=LOADOUT_AGGREGATE,
            companion_roster=COMPANION_ROSTER_AGGREGATE,
            character_world=CHARACTER_WORLD_AGGREGATE,
            inscription_preference=INSCRIPTION_PREFERENCE_AGGREGATE,
        ),
        party_scope_id=PARTY_SCOPE_ID,
    )
    sparring = SparringFeature(
        database,
        content,
        world_views,
        snapshots,
        social,
        battle_reports,
        SparringBattleSimulator(content.catalog, player_lineup),
        SparringStorageKinds(
            character=CHARACTER_AGGREGATE,
            character_world=CHARACTER_WORLD_AGGREGATE,
            inventory=INVENTORY_AGGREGATE,
            loadout=LOADOUT_AGGREGATE,
            companion_roster=COMPANION_ROSTER_AGGREGATE,
            inscription_preference=INSCRIPTION_PREFERENCE_AGGREGATE,
        ),
    )
    return GameServices(
        database=database,
        accounts=accounts,
        characters=characters,
        character_creation=character_creation_service,
        character_projector=character_projector,
        player_combat=player_combat,
        inscriptions=inscription_service,
        item_use=item_use_service,
        character_item_use=character_item_use_service,
        weapon_item_use=weapon_item_use_service,
        special_item_use=special_item_use_service,
        equipment_blueprints=equipment_blueprints,
        covenant_exchange=covenant_exchange,
        inventory_engine=inventory_engine,
        inventory_protection=inventory_protection,
        player=player,
        dimension_shift=dimension_shift,
        breakthrough=breakthrough,
        loadouts=loadout_service,
        notifications=notifications,
        activities=activities,
        actions=action_service,
        global_activities=registered_global_activities,
        battle_reports=battle_reports,
        data_lifecycle=data_lifecycle,
        build_trials=build_trials,
        dimensional_disasters=dimensional_disasters,
        party=party,
        party_battles=party_battles,
        party_sparring=party_sparring,
        companions=companions,
        player_lineup=player_lineup,
        exploration=exploration,
        world_progress=world_progress,
        world_lore=world_lore,
        world_travel=world_travel,
        rest=rest,
        sparring=sparring,
        economy=economy,
        lottery=lottery,
        draw=draw,
        world_views=world_views,
        content=content,
    )


def current_game_services() -> GameServices:
    """返回当前服务集合；首次使用时按配置延迟组装。"""

    global _services
    if _services is None:
        _services = build_game_services()
    return _services


def current_message_flow_store() -> MessageFlowStore:
    """返回 Web 游戏台独立短期消息仓储。"""

    global _message_flow_store
    expected_path = config.database.message_console_path
    if _message_flow_store is None or (
        not _message_flow_store_overridden
        and (
            _message_flow_store.path != expected_path
            or _message_flow_store.busy_timeout_ms != config.database.busy_timeout_ms
        )
    ):
        _message_flow_store = MessageFlowStore(
            expected_path,
            busy_timeout_ms=config.database.busy_timeout_ms,
        )
    return _message_flow_store


def install_message_flow_store(store: MessageFlowStore | None) -> MessageFlowStore | None:
    """为测试或受控工具替换独立消息仓储。"""

    global _message_flow_store, _message_flow_store_overridden
    previous = _message_flow_store
    _message_flow_store = store
    _message_flow_store_overridden = store is not None
    return previous


def install_game_services(services: GameServices) -> GameServices | None:
    """测试和受控工具临时替换服务集合，并返回旧值。"""

    global _services, _services_overridden
    previous = _services
    _services = services
    _services_overridden = True
    return previous


def restore_game_services(previous: GameServices | None) -> None:
    """恢复测试前的服务集合。"""

    global _services, _services_overridden
    _services = previous
    _services_overridden = False


@OnEvent.connect(priority=200)
def initialize_game_services() -> None:
    """在服务接收消息前校验并初始化当前 SQLite 数据库。"""

    global _services
    if (
        not _services_overridden
        and _services is not None
        and _services.database.path != config.database.path
    ):
        _services = None
    services = current_game_services()
    services.database.initialize()
    logical_time = datetime.now(ZoneInfo(config.project.timezone))
    ContentActivationStore(services.database).verify_or_initialize(
        services.content.catalog.report,
        logical_time=logical_time,
    )
    services.activities.initialize(
        GLOBAL_ACTIVITY_SCOPE_ID,
        logical_time=logical_time,
    )
    services.economy.initialize(
        logical_time=logical_time,
    )
    services.lottery.initialize(
        logical_time=logical_time,
    )
    services.dimensional_disasters.maintain(
        logical_time=logical_time
    )


__all__ = [
    "CharacterCreationCommandResult",
    "CharacterOverview",
    "CharacterOverviewResult",
    "CurrentCharacterResult",
    "GameServices",
    "GlobalActivityViewsResult",
    "PlayerReplyState",
    "PlayerReplyStateResult",
    "PlayerReminderDetails",
    "PlayerReminderDetailsResult",
    "build_game_services",
    "current_game_services",
    "current_message_flow_store",
    "initialize_game_services",
    "install_game_services",
    "install_message_flow_store",
    "message_identity_evidence",
    "restore_game_services",
]
