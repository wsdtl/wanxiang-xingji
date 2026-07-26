"""协议和具体玩法无关的持久化联合事务基础设施。"""

PERSISTENCE_FOUNDATION_VERSION = "persistence.foundation.v10"

from .codec import StructuredJsonCodec
from .actions import (
    PersistedActionClaimExecution,
    PersistedActionExecution,
    PersistedActionService,
)
from .activities import PersistedActivityExecution, PersistedActivityService
from .accounts import PersistedAccountService
from .characters import (
    CharacterCreationWorkflow,
    PersistedCharacterCreationService,
    PersistedCharacterRegistration,
    PersistedCharacterService,
)
from .character_items import PersistedCharacterItemUseService
from .battle_reports import (
    BattleReportHeaderRow,
    BattleReportStore,
    PublicBattleReportRow,
)
from .content import ContentActivation, ContentActivationStore
from .cycles import (
    CycleCursor,
    CycleWorkItem,
    CycleWorkStatus,
    PersistentCycleService,
    cycle_transaction_id,
)
from .inscriptions import PersistedInscriptionService
from .item_use import PersistedItemUseService
from .inventory_protection import (
    InventoryProtectionExecution,
    PersistedInventoryProtectionService,
)
from .weapon_items import PersistedWeaponItemUseService
from .loadouts import PersistedLoadoutExecution, PersistedLoadoutService
from .loot import PersistedLootExecution, PersistedLootService
from .message_flows import MessageFlowRow, MessageFlowStore
from .parties import (
    PersistedPartyAdmissionExecution,
    PersistedPartyAdmissionService,
    PersistedPartyExecution,
    PersistedPartyService,
)
from .world import PersistedWorldExecution, PersistedWorldService
from .social import PersistedSocialExecution, PersistedSocialService
from .projections import (
    FactJournalService,
    NotificationInboxService,
    ProjectionStore,
    RankingSnapshotStore,
)
from .retention import (
    FACT_RETENTION,
    PUBLISHED_DELIVERY_RETENTION,
    READ_NOTIFICATION_RETENTION,
    RETENTION_BATCH_SIZE,
    UNREAD_NOTIFICATION_RETENTION,
    PersistenceRetentionService,
    RetentionReceipt,
)
from .exchange import PersistedExchangeExecution, PersistedExchangeService
from .grants import PersistedGrantService
from .errors import (
    AggregateNotFound,
    ConcurrencyConflict,
    ContentActivationMismatch,
    CorruptPersistenceData,
    PersistenceError,
    SchemaVersionError,
    TransactionMismatch,
)
from .rewards import (
    PendingRuleEvent,
    PersistedRewardSettlementService,
    RewardSettlementStorageKeys,
)
from .snapshots import (
    ACTION_AGGREGATE,
    ACTIVITY_AGGREGATE,
    CHARACTER_AGGREGATE,
    CHARACTER_ROSTER_AGGREGATE,
    EXCHANGE_AGGREGATE,
    INVENTORY_AGGREGATE,
    INSCRIPTION_PREFERENCE_AGGREGATE,
    LEDGER_AGGREGATE,
    LOADOUT_AGGREGATE,
    LOOT_AGGREGATE,
    PARTY_AGGREGATE,
    REWARD_CLAIM_AGGREGATE,
    SOCIAL_AGGREGATE,
    WEAPON_AGGREGATE,
    WORLD_AGGREGATE,
    SnapshotRepository,
    gameplay_snapshot_codec,
)
from .sqlite import (
    AggregateSnapshotRow,
    CommittedTransactionRow,
    ContentActivationRow,
    CycleCursorRow,
    CycleWorkItemRow,
    OutboxEventRow,
    PERSISTENCE_SCHEMA_VERSION,
    SNAPSHOT_CODEC_VERSION,
    SqliteDatabase,
    SqliteUnitOfWork,
)

__all__ = [
    "ACTION_AGGREGATE",
    "ACTIVITY_AGGREGATE",
    "AggregateNotFound",
    "AggregateSnapshotRow",
    "BattleReportHeaderRow",
    "BattleReportStore",
    "CHARACTER_AGGREGATE",
    "CHARACTER_ROSTER_AGGREGATE",
    "CharacterCreationWorkflow",
    "EXCHANGE_AGGREGATE",
    "FactJournalService",
    "FACT_RETENTION",
    "CommittedTransactionRow",
    "ConcurrencyConflict",
    "ContentActivation",
    "ContentActivationMismatch",
    "ContentActivationRow",
    "ContentActivationStore",
    "CycleCursor",
    "CycleCursorRow",
    "CycleWorkItem",
    "CycleWorkItemRow",
    "CycleWorkStatus",
    "CorruptPersistenceData",
    "INVENTORY_AGGREGATE",
    "INSCRIPTION_PREFERENCE_AGGREGATE",
    "LEDGER_AGGREGATE",
    "LOADOUT_AGGREGATE",
    "LOOT_AGGREGATE",
    "MessageFlowRow",
    "MessageFlowStore",
    "PARTY_AGGREGATE",
    "NotificationInboxService",
    "OutboxEventRow",
    "PERSISTENCE_FOUNDATION_VERSION",
    "PERSISTENCE_SCHEMA_VERSION",
    "ProjectionStore",
    "PersistenceRetentionService",
    "PUBLISHED_DELIVERY_RETENTION",
    "PublicBattleReportRow",
    "PendingRuleEvent",
    "PersistedAccountService",
    "PersistedCharacterRegistration",
    "PersistedCharacterCreationService",
    "PersistedCharacterService",
    "PersistedCharacterItemUseService",
    "PersistedActionClaimExecution",
    "PersistedActionExecution",
    "PersistedActionService",
    "PersistedActivityExecution",
    "PersistedActivityService",
    "PersistedExchangeExecution",
    "PersistedExchangeService",
    "PersistentCycleService",
    "PersistedRewardSettlementService",
    "PersistedGrantService",
    "PersistedInscriptionService",
    "PersistedItemUseService",
    "InventoryProtectionExecution",
    "PersistedInventoryProtectionService",
    "PersistedWeaponItemUseService",
    "PersistedLoadoutExecution",
    "PersistedLoadoutService",
    "PersistedLootExecution",
    "PersistedLootService",
    "PersistedPartyAdmissionExecution",
    "PersistedPartyAdmissionService",
    "PersistedPartyExecution",
    "PersistedPartyService",
    "PersistedSocialExecution",
    "PersistedSocialService",
    "PersistedWorldExecution",
    "PersistedWorldService",
    "PersistenceError",
    "REWARD_CLAIM_AGGREGATE",
    "SOCIAL_AGGREGATE",
    "RewardSettlementStorageKeys",
    "READ_NOTIFICATION_RETENTION",
    "RETENTION_BATCH_SIZE",
    "RetentionReceipt",
    "RankingSnapshotStore",
    "SNAPSHOT_CODEC_VERSION",
    "SchemaVersionError",
    "SnapshotRepository",
    "SqliteDatabase",
    "SqliteUnitOfWork",
    "UNREAD_NOTIFICATION_RETENTION",
    "StructuredJsonCodec",
    "TransactionMismatch",
    "WEAPON_AGGREGATE",
    "WORLD_AGGREGATE",
    "gameplay_snapshot_codec",
    "cycle_transaction_id",
]
