"""Gameplay 领域快照的白名单编解码与类型化聚合仓储。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Iterable, Iterator, TypeVar

from ..account import (
    AccountDirectoryState,
    AccountEvent,
    AccountMutation,
    AccountResolution,
    AccountState,
    AccountStatus,
    AccountStatusTransaction,
    EvidenceRecord,
    ExternalIdentity,
    IdentityBinding,
    IdentityConflict,
    IdentityEvidence,
    UnbindIdentityTransaction,
)
from ..gameplay.activities import (
    ActivityCommand,
    ActivityExecution,
    ActivityInstance,
    ActivityParticipant,
    ActivityRankEntry,
    ActivityState,
    ActivityStatus,
    ActivityTieBreaker,
    CancelActivity,
    CloseActivity,
    CreateActivity,
    FinalizeActivity,
    JoinActivity,
    OpenActivity,
    RecordActivityContribution,
)
from ..gameplay.actions import (
    ActionExecution,
    ActionRecord,
    ActionResult,
    ActionSlotKind,
    ActionSnapshot,
    ActionState,
    ActionStatus,
    ActionTransaction,
    CancelAction,
    ClaimAction,
    CompleteAction,
    InterruptAction,
    StartAction,
)
from ..gameplay.character import (
    CharacterItemUseReceipt,
    CharacterRosterState,
    CharacterState,
    CharacterStatus,
    ProgressionState,
    UnlockProgressionCap,
)
from ..gameplay.draw import (
    DrawCommand,
    DrawExecution,
    DrawGuaranteeDecision,
    DrawGuaranteeEntry,
    DrawGuaranteeSlotDefinition,
    DrawInventoryCommand,
    DrawInventoryExecution,
    DrawInventoryReceipt,
    DrawItemAward,
    DrawPoolDefinition,
    DrawReceipt,
)
from ..gameplay.economy import (
    AppliedLedgerTransaction,
    FundHold,
    JournalEntry,
    LedgerAccount,
    LedgerAccountKind,
    LedgerPosting,
    LedgerState,
)
from ..gameplay.equipment import EquipmentState
from ..gameplay.events import RuleEvent
from ..gameplay.exchange import (
    CancelExchange,
    CommitExchange,
    ExchangeAssetOffer,
    ExchangeCommand,
    ExchangeContract,
    ExchangeExecution,
    ExchangeQuote,
    ExchangeQuoteLine,
    ExchangeState,
    ExchangeStatus,
    ExpireExchange,
    OpenExchange,
    SettleExchange,
)
from ..gameplay.inventory import (
    AssetReservation,
    InventoryState,
    ItemAssetKind,
    ItemContainer,
    ItemInstance,
    ItemStack,
    ItemUseReceipt,
    ProvenanceLot,
    ReservationMode,
    SourceReceipt,
)
from ..gameplay.inscription import (
    AssetInscriptionTarget,
    InscriptionData,
    InscriptionMediumData,
    InscriptionPreference,
    InscriptionReceipt,
    WeaponAbilityInscriptionTarget,
)
from ..gameplay.loadout import (
    ActivateLoadoutPreset,
    DeleteLoadoutPreset,
    EquipAsset,
    LoadoutExecution,
    LoadoutSlotKind,
    LoadoutPreset,
    LoadoutState,
    LoadoutTransaction,
    SaveLoadoutPreset,
    UnequipSlot,
)
from ..gameplay.itemization import (
    GenerationDecision,
    GenerationReceipt,
    ItemRollState,
    ItemizationKind,
    RolledProperty,
)
from ..gameplay.loot import (
    LootAward,
    LootDecision,
    LootEntry,
    LootExecution,
    LootGroup,
    LootGroupMode,
    LootPityDefinition,
    LootRollCommand,
    LootRollReceipt,
    LootState,
    LootTableDefinition,
)
from ..gameplay.phases import ExecutionPhase
from ..gameplay.party import (
    AddPartyMember,
    CreateParty,
    DisbandParty,
    LeaveParty,
    Party,
    PartyAdmissionCommand,
    PartyAdmissionExecution,
    PartyCommand,
    PartyExecution,
    PartyMember,
    PartyState,
    PartyStatus,
    RemovePartyMember,
    SetPartyMemberReady,
    SetPartyMemberSlot,
    TransferPartyLeadership,
)
from ..gameplay.projections import (
    FactRecord,
    NotificationAction,
    NotificationEntry,
    NotificationStatus,
    ProjectionValue,
    RankingCandidate,
    RankingDirection,
    RankingEntry,
    RankingSnapshot,
)
from ..gameplay.rewards import (
    RewardClaimRecord,
    RewardClaimState,
    RewardDisposition,
    RewardLine,
    RewardReceipt,
)
from ..gameplay.social import (
    AddOrganizationContribution,
    AdjustSocialRelation,
    ChangeOrganizationRole,
    CreateOrganization,
    CreateSocialRequest,
    DissolveOrganization,
    JoinOrganization,
    LeaveOrganization,
    Organization,
    OrganizationMember,
    OrganizationStatus,
    RelationOverflowPolicy,
    ResolveSocialRequest,
    SocialCommand,
    SocialExecution,
    SocialRelation,
    SocialRequest,
    SocialRequestStatus,
    SocialState,
    TransferOrganizationLeadership,
)
from ..gameplay.tags import Tag, TagSet
from ..gameplay.weapon import (
    WeaponItemUseReceipt,
    WeaponMaximumLevelRoll,
    WeaponState,
)
from ..gameplay.valuation import ValueVector
from ..gameplay.world import (
    AddPresence,
    AdjustWorldMeter,
    MeterOverflowPolicy,
    MovePresence,
    ReleaseWorldReservation,
    RemovePresence,
    ReserveWorldPosition,
    WorldExecution,
    WorldPosition,
    WorldPresence,
    WorldReservation,
    WorldScopeKind,
    WorldScopeRef,
    WorldState,
    WorldTopologyKind,
    WorldTransaction,
)

from .codec import StructuredJsonCodec
from .errors import CorruptPersistenceData
from .sqlite import SNAPSHOT_CODEC_VERSION, SqliteUnitOfWork


INVENTORY_AGGREGATE = "snapshot.inventory"
LEDGER_AGGREGATE = "snapshot.ledger"
CHARACTER_AGGREGATE = "snapshot.character"
CHARACTER_ROSTER_AGGREGATE = "snapshot.character_roster"
WEAPON_AGGREGATE = "snapshot.weapon"
REWARD_CLAIM_AGGREGATE = "snapshot.reward_claim"
INSCRIPTION_PREFERENCE_AGGREGATE = "snapshot.inscription_preference"
ACTION_AGGREGATE = "snapshot.action"
LOADOUT_AGGREGATE = "snapshot.loadout"
LOOT_AGGREGATE = "snapshot.loot"
WORLD_AGGREGATE = "snapshot.world"
EXCHANGE_AGGREGATE = "snapshot.exchange"
ACTIVITY_AGGREGATE = "snapshot.activity"
SOCIAL_AGGREGATE = "snapshot.social"
PARTY_AGGREGATE = "snapshot.party"

StateT = TypeVar("StateT")


def gameplay_snapshot_codec(
    extra_registrations: Iterable[tuple[str, type[object]]] = (),
) -> StructuredJsonCodec:
    """创建核心快照 codec，并允许组合根在冻结前追加业务聚合类型。"""

    codec = StructuredJsonCodec()
    registrations = (
        ("account.status", AccountStatus),
        ("account.external_identity", ExternalIdentity),
        ("account.identity_evidence", IdentityEvidence),
        ("account.state", AccountState),
        ("account.identity_binding", IdentityBinding),
        ("account.identity_conflict", IdentityConflict),
        ("account.evidence_record", EvidenceRecord),
        ("account.directory_state", AccountDirectoryState),
        ("account.event", AccountEvent),
        ("account.resolution", AccountResolution),
        ("account.status_transaction", AccountStatusTransaction),
        ("account.unbind_transaction", UnbindIdentityTransaction),
        ("account.mutation", AccountMutation),
        ("activity.status", ActivityStatus),
        ("activity.tie_breaker", ActivityTieBreaker),
        ("activity.participant", ActivityParticipant),
        ("activity.rank_entry", ActivityRankEntry),
        ("activity.instance", ActivityInstance),
        ("activity.state", ActivityState),
        ("activity.create", CreateActivity),
        ("activity.open", OpenActivity),
        ("activity.join", JoinActivity),
        ("activity.contribute", RecordActivityContribution),
        ("activity.close", CloseActivity),
        ("activity.finalize", FinalizeActivity),
        ("activity.cancel", CancelActivity),
        ("activity.command", ActivityCommand),
        ("activity.execution", ActivityExecution),
        ("gameplay.tag", Tag),
        ("gameplay.tag_set", TagSet),
        ("action.slot_kind", ActionSlotKind),
        ("action.status", ActionStatus),
        ("action.start", StartAction),
        ("action.complete", CompleteAction),
        ("action.claim", ClaimAction),
        ("action.cancel", CancelAction),
        ("action.interrupt", InterruptAction),
        ("action.transaction", ActionTransaction),
        ("action.snapshot", ActionSnapshot),
        ("action.result", ActionResult),
        ("action.record", ActionRecord),
        ("action.state", ActionState),
        ("action.execution", ActionExecution),
        ("draw.pool_definition", DrawPoolDefinition),
        ("draw.guarantee_entry", DrawGuaranteeEntry),
        ("draw.guarantee_slot_definition", DrawGuaranteeSlotDefinition),
        ("draw.guarantee_decision", DrawGuaranteeDecision),
        ("draw.command", DrawCommand),
        ("draw.receipt", DrawReceipt),
        ("draw.execution", DrawExecution),
        ("draw.inventory_command", DrawInventoryCommand),
        ("draw.item_award", DrawItemAward),
        ("draw.inventory_receipt", DrawInventoryReceipt),
        ("draw.inventory_execution", DrawInventoryExecution),
        ("inventory.asset_kind", ItemAssetKind),
        ("inventory.reservation_mode", ReservationMode),
        ("inventory.source_receipt", SourceReceipt),
        ("inventory.provenance_lot", ProvenanceLot),
        ("inventory.item_stack", ItemStack),
        ("inventory.item_instance", ItemInstance),
        ("inventory.item_container", ItemContainer),
        ("inventory.asset_reservation", AssetReservation),
        ("inventory.state", InventoryState),
        ("inventory.item_use_receipt", ItemUseReceipt),
        ("inscription.asset_target", AssetInscriptionTarget),
        ("inscription.weapon_ability_target", WeaponAbilityInscriptionTarget),
        ("inscription.data", InscriptionData),
        ("inscription.medium_data", InscriptionMediumData),
        ("inscription.preference", InscriptionPreference),
        ("inscription.receipt", InscriptionReceipt),
        ("loadout.slot_kind", LoadoutSlotKind),
        ("loadout.preset", LoadoutPreset),
        ("loadout.equip", EquipAsset),
        ("loadout.unequip", UnequipSlot),
        ("loadout.save_preset", SaveLoadoutPreset),
        ("loadout.delete_preset", DeleteLoadoutPreset),
        ("loadout.activate_preset", ActivateLoadoutPreset),
        ("loadout.transaction", LoadoutTransaction),
        ("loadout.state", LoadoutState),
        ("loadout.execution", LoadoutExecution),
        ("loot.group_mode", LootGroupMode),
        ("loot.entry", LootEntry),
        ("loot.group", LootGroup),
        ("loot.pity_definition", LootPityDefinition),
        ("loot.table_definition", LootTableDefinition),
        ("loot.state", LootState),
        ("loot.command", LootRollCommand),
        ("loot.award", LootAward),
        ("loot.decision", LootDecision),
        ("loot.receipt", LootRollReceipt),
        ("loot.execution", LootExecution),
        ("world.topology_kind", WorldTopologyKind),
        ("world.scope_kind", WorldScopeKind),
        ("world.meter_overflow", MeterOverflowPolicy),
        ("world.position", WorldPosition),
        ("world.scope_ref", WorldScopeRef),
        ("world.presence", WorldPresence),
        ("world.reservation", WorldReservation),
        ("world.state", WorldState),
        ("world.add_presence", AddPresence),
        ("world.move_presence", MovePresence),
        ("world.remove_presence", RemovePresence),
        ("world.reserve_position", ReserveWorldPosition),
        ("world.release_reservation", ReleaseWorldReservation),
        ("world.adjust_meter", AdjustWorldMeter),
        ("world.transaction", WorldTransaction),
        ("world.execution", WorldExecution),
        ("economy.account_kind", LedgerAccountKind),
        ("economy.account", LedgerAccount),
        ("economy.fund_hold", FundHold),
        ("economy.posting", LedgerPosting),
        ("economy.journal_entry", JournalEntry),
        ("economy.applied_transaction", AppliedLedgerTransaction),
        ("economy.state", LedgerState),
        ("character.status", CharacterStatus),
        ("character.progression_state", ProgressionState),
        ("character.roster_state", CharacterRosterState),
        ("character.state", CharacterState),
        ("character.item_use_receipt", CharacterItemUseReceipt),
        ("character.unlock_progression_cap", UnlockProgressionCap),
        ("weapon.state", WeaponState),
        ("weapon.maximum_level_roll", WeaponMaximumLevelRoll),
        ("weapon.item_use_receipt", WeaponItemUseReceipt),
        ("equipment.state", EquipmentState),
        ("valuation.value_vector", ValueVector),
        ("itemization.kind", ItemizationKind),
        ("itemization.rolled_property", RolledProperty),
        ("itemization.generation_decision", GenerationDecision),
        ("itemization.generation_receipt", GenerationReceipt),
        ("itemization.roll_state", ItemRollState),
        ("reward.disposition", RewardDisposition),
        ("reward.line", RewardLine),
        ("reward.receipt", RewardReceipt),
        ("reward.claim_record", RewardClaimRecord),
        ("reward.claim_state", RewardClaimState),
        ("social.organization_status", OrganizationStatus),
        ("social.request_status", SocialRequestStatus),
        ("social.relation_overflow", RelationOverflowPolicy),
        ("social.organization_member", OrganizationMember),
        ("social.organization", Organization),
        ("social.request", SocialRequest),
        ("social.relation", SocialRelation),
        ("social.state", SocialState),
        ("social.create_organization", CreateOrganization),
        ("social.join_organization", JoinOrganization),
        ("social.leave_organization", LeaveOrganization),
        ("social.change_role", ChangeOrganizationRole),
        ("social.transfer_leadership", TransferOrganizationLeadership),
        ("social.add_contribution", AddOrganizationContribution),
        ("social.dissolve_organization", DissolveOrganization),
        ("social.create_request", CreateSocialRequest),
        ("social.resolve_request", ResolveSocialRequest),
        ("social.adjust_relation", AdjustSocialRelation),
        ("social.command", SocialCommand),
        ("social.execution", SocialExecution),
        ("party.status", PartyStatus),
        ("party.member", PartyMember),
        ("party.value", Party),
        ("party.state", PartyState),
        ("party.create", CreateParty),
        ("party.add_member", AddPartyMember),
        ("party.remove_member", RemovePartyMember),
        ("party.leave", LeaveParty),
        ("party.transfer_leadership", TransferPartyLeadership),
        ("party.set_ready", SetPartyMemberReady),
        ("party.set_slot", SetPartyMemberSlot),
        ("party.disband", DisbandParty),
        ("party.command", PartyCommand),
        ("party.execution", PartyExecution),
        ("party.admission_command", PartyAdmissionCommand),
        ("party.admission_execution", PartyAdmissionExecution),
        ("rule.execution_phase", ExecutionPhase),
        ("rule.event", RuleEvent),
        ("projection.fact_record", FactRecord),
        ("projection.value", ProjectionValue),
        ("notification.status", NotificationStatus),
        ("notification.action", NotificationAction),
        ("notification.entry", NotificationEntry),
        ("ranking.direction", RankingDirection),
        ("ranking.candidate", RankingCandidate),
        ("ranking.entry", RankingEntry),
        ("ranking.snapshot", RankingSnapshot),
        ("exchange.status", ExchangeStatus),
        ("exchange.quote_line", ExchangeQuoteLine),
        ("exchange.quote", ExchangeQuote),
        ("exchange.asset_offer", ExchangeAssetOffer),
        ("exchange.contract", ExchangeContract),
        ("exchange.state", ExchangeState),
        ("exchange.open", OpenExchange),
        ("exchange.commit", CommitExchange),
        ("exchange.settle", SettleExchange),
        ("exchange.cancel", CancelExchange),
        ("exchange.expire", ExpireExchange),
        ("exchange.command", ExchangeCommand),
        ("exchange.execution", ExchangeExecution),
    )
    for type_id, value_type in registrations:
        codec.register(type_id, value_type)
    for type_id, value_type in extra_registrations:
        codec.register(type_id, value_type)
    codec.freeze()
    return codec


class SnapshotRepository:
    """只负责类型化快照读写；事务范围由外部工作单元控制。"""

    def __init__(self, codec: StructuredJsonCodec | None = None) -> None:
        self.codec = codec or gameplay_snapshot_codec()

    def load(
        self,
        uow: SqliteUnitOfWork,
        aggregate_kind: str,
        aggregate_id: str,
        expected_type: type[StateT],
    ) -> StateT | None:
        row = uow.load_snapshot(aggregate_kind, aggregate_id)
        if row is None:
            return None
        if row.codec_version != SNAPSHOT_CODEC_VERSION:
            raise CorruptPersistenceData(
                f"快照 codec 版本不匹配：需要 {SNAPSHOT_CODEC_VERSION}，当前 {row.codec_version}"
            )
        value = self.codec.loads(row.payload, expected_type)
        value = self._hydrate_external_collections(
            uow,
            aggregate_kind,
            aggregate_id,
            value,
        )
        revision = getattr(value, "revision", None)
        if revision != row.revision:
            raise CorruptPersistenceData(
                f"快照行 revision 与负载不一致：{aggregate_kind}/{aggregate_id}"
            )
        return value

    def require(
        self,
        uow: SqliteUnitOfWork,
        aggregate_kind: str,
        aggregate_id: str,
        expected_type: type[StateT],
    ) -> StateT:
        value = self.load(uow, aggregate_kind, aggregate_id, expected_type)
        if value is None:
            from .errors import AggregateNotFound

            raise AggregateNotFound(f"缺少聚合快照：{aggregate_kind}/{aggregate_id}")
        return value

    def list(
        self,
        uow: SqliteUnitOfWork,
        aggregate_kind: str,
        expected_type: type[StateT],
        *,
        limit: int = 1_000,
        after_id: str | None = None,
    ) -> tuple[StateT, ...]:
        """解码同类聚合；业务调度只依赖仓储接口，不直接读取 SQL。"""

        values: list[StateT] = []
        for row in uow.list_snapshots(
            aggregate_kind,
            limit=limit,
            after_id=after_id,
        ):
            if row.codec_version != SNAPSHOT_CODEC_VERSION:
                raise CorruptPersistenceData(
                    f"快照 codec 版本不匹配：需要 {SNAPSHOT_CODEC_VERSION}，当前 {row.codec_version}"
                )
            value = self.codec.loads(row.payload, expected_type)
            value = self._hydrate_external_collections(
                uow,
                aggregate_kind,
                row.aggregate_id,
                value,
            )
            if getattr(value, "revision", None) != row.revision:
                raise CorruptPersistenceData(
                    f"快照行 revision 与负载不一致：{aggregate_kind}/{row.aggregate_id}"
                )
            values.append(value)
        return tuple(values)

    def iter_all(
        self,
        uow: SqliteUnitOfWork,
        aggregate_kind: str,
        expected_type: type[StateT],
        *,
        page_size: int = 1_000,
    ) -> Iterator[StateT]:
        """用稳定 aggregate_id 游标遍历全部快照，不把总量误当页大小。"""

        after_id: str | None = None
        while True:
            rows = uow.list_snapshots(
                aggregate_kind,
                limit=page_size,
                after_id=after_id,
            )
            if not rows:
                return
            for row in rows:
                if row.codec_version != SNAPSHOT_CODEC_VERSION:
                    raise CorruptPersistenceData(
                        f"快照 codec 版本不匹配：需要 {SNAPSHOT_CODEC_VERSION}，当前 {row.codec_version}"
                    )
                value = self.codec.loads(row.payload, expected_type)
                value = self._hydrate_external_collections(
                    uow,
                    aggregate_kind,
                    row.aggregate_id,
                    value,
                )
                if getattr(value, "revision", None) != row.revision:
                    raise CorruptPersistenceData(
                        f"快照行 revision 与负载不一致：{aggregate_kind}/{row.aggregate_id}"
                    )
                yield value
            after_id = rows[-1].aggregate_id
            if len(rows) < page_size:
                return

    def insert(
        self,
        uow: SqliteUnitOfWork,
        aggregate_kind: str,
        aggregate_id: str,
        value: object,
        logical_time: datetime,
        *,
        expires_at: datetime | None = None,
    ) -> None:
        _require_aware(logical_time)
        _require_optional_aware(expires_at)
        self._sync_party_memberships(
            uow,
            aggregate_kind,
            aggregate_id,
            None,
            value,
        )
        self._sync_world_entities(
            uow,
            aggregate_kind,
            aggregate_id,
            None,
            value,
            logical_time,
        )
        persisted = self._extract_append_only_history(
            uow,
            aggregate_kind,
            aggregate_id,
            value,
            logical_time,
        )
        revision = _revision_of(value)
        uow.insert_snapshot(
            aggregate_kind,
            aggregate_id,
            revision,
            self.codec.dumps(persisted),
            logical_time.isoformat(),
            expires_at.isoformat() if expires_at is not None else None,
        )

    def update(
        self,
        uow: SqliteUnitOfWork,
        aggregate_kind: str,
        aggregate_id: str,
        previous: object,
        current: object,
        logical_time: datetime,
        *,
        expires_at: datetime | None = None,
    ) -> None:
        _require_aware(logical_time)
        _require_optional_aware(expires_at)
        previous_revision = _revision_of(previous)
        current_revision = _revision_of(current)
        self._sync_party_memberships(
            uow,
            aggregate_kind,
            aggregate_id,
            previous,
            current,
        )
        self._sync_world_entities(
            uow,
            aggregate_kind,
            aggregate_id,
            previous,
            current,
            logical_time,
        )
        persisted = self._extract_append_only_history(
            uow,
            aggregate_kind,
            aggregate_id,
            current,
            logical_time,
        )
        uow.compare_and_swap_snapshot(
            aggregate_kind,
            aggregate_id,
            previous_revision,
            current_revision,
            self.codec.dumps(persisted),
            logical_time.isoformat(),
            expires_at.isoformat() if expires_at is not None else None,
        )

    def delete(
        self,
        uow: SqliteUnitOfWork,
        aggregate_kind: str,
        aggregate_id: str,
        *,
        expected_revision: int | None = None,
    ) -> bool:
        return uow.delete_snapshot(
            aggregate_kind,
            aggregate_id,
            expected_revision=expected_revision,
        )

    def compact(self, value: StateT) -> StateT:
        """返回与磁盘热快照一致的领域值，供提交后的调用方继续使用。"""

        if isinstance(value, LedgerState):
            return replace(value, journal=(), applied_transactions={})  # type: ignore[return-value]
        if isinstance(value, RewardClaimState):
            return replace(value, records={})  # type: ignore[return-value]
        if isinstance(value, WorldState):
            return replace(value, presences={}, reservations={})  # type: ignore[return-value]
        return value

    def _extract_append_only_history(
        self,
        uow: SqliteUnitOfWork,
        aggregate_kind: str,
        aggregate_id: str,
        value: object,
        logical_time: datetime,
    ) -> object:
        if aggregate_kind == LEDGER_AGGREGATE and isinstance(value, LedgerState):
            entries_by_transaction: dict[str, list[JournalEntry]] = {}
            for entry in value.journal:
                entries_by_transaction.setdefault(entry.transaction_id, []).append(entry)
            for transaction_id, record in sorted(value.applied_transactions.items()):
                entries = entries_by_transaction.get(transaction_id, ())
                applied_at = entries[0].logical_time if entries else logical_time
                uow.insert_ledger_transaction(
                    aggregate_id,
                    transaction_id,
                    record.fingerprint,
                    record.resulting_revision,
                    applied_at.isoformat(),
                )
            for entry in value.journal:
                if entry.transaction_id not in value.applied_transactions:
                    raise CorruptPersistenceData(
                        f"账本流水缺少防重事务：{aggregate_id}/{entry.transaction_id}"
                    )
                uow.insert_ledger_journal_entry(
                    aggregate_id,
                    entry.id,
                    entry.transaction_id,
                    str(entry.currency_id),
                    str(entry.reason),
                    entry.actor_id,
                    entry.logical_time.isoformat(),
                    self.codec.dumps(entry),
                )
            return self.compact(value)
        if aggregate_kind == REWARD_CLAIM_AGGREGATE and isinstance(value, RewardClaimState):
            for settlement_id, record in sorted(value.records.items()):
                uow.insert_reward_claim(
                    value.scope_id,
                    settlement_id,
                    record.fingerprint,
                    record.resulting_revision,
                    record.receipt.logical_time.isoformat(),
                )
            return self.compact(value)
        return value

    @staticmethod
    def _sync_party_memberships(
        uow: SqliteUnitOfWork,
        aggregate_kind: str,
        aggregate_id: str,
        previous: object | None,
        current: object,
    ) -> None:
        if aggregate_kind != PARTY_AGGREGATE or not isinstance(current, PartyState):
            return
        if previous is not None and not isinstance(previous, PartyState):
            raise TypeError("队伍快照更新前后类型不一致")

        def active_members(state: PartyState | None):
            if state is None:
                return {}
            return {
                member.subject_id: (party.id, member.joined_at)
                for party in state.parties.values()
                if party.status is PartyStatus.ACTIVE
                for member in party.members.values()
            }

        before = active_members(previous)
        after = active_members(current)
        for subject_id, (party_id, _joined_at) in before.items():
            if subject_id not in after:
                uow.delete_party_membership(subject_id, party_id)
        for subject_id, (party_id, joined_at) in after.items():
            prior = before.get(subject_id)
            if prior is not None:
                if prior[0] != party_id:
                    uow.delete_party_membership(subject_id, prior[0])
                else:
                    continue
            uow.insert_party_membership(
                subject_id,
                party_id,
                aggregate_id,
                joined_at.isoformat(),
            )

    def _hydrate_external_collections(
        self,
        uow: SqliteUnitOfWork,
        aggregate_kind: str,
        aggregate_id: str,
        value: StateT,
    ) -> StateT:
        if aggregate_kind != WORLD_AGGREGATE or not isinstance(value, WorldState):
            return value
        presences = {}
        for row in uow.list_world_presences(aggregate_id):
            presence = self.codec.loads(row.payload, WorldPresence)
            if presence.id != row.presence_id or presence.revision != row.revision:
                raise CorruptPersistenceData(
                    f"世界存在体关系行与负载不一致：{aggregate_id}/{row.presence_id}"
                )
            presences[presence.id] = presence
        reservations = {}
        for row in uow.list_world_reservations(aggregate_id):
            reservation = self.codec.loads(row.payload, WorldReservation)
            if reservation.id != row.reservation_id:
                raise CorruptPersistenceData(
                    f"世界预约关系行与负载不一致：{aggregate_id}/{row.reservation_id}"
                )
            reservations[reservation.id] = reservation
        return replace(  # type: ignore[return-value]
            value,
            presences=presences,
            reservations=reservations,
        )

    def _sync_world_entities(
        self,
        uow: SqliteUnitOfWork,
        aggregate_kind: str,
        aggregate_id: str,
        previous: object | None,
        current: object,
        logical_time: datetime,
    ) -> None:
        if aggregate_kind != WORLD_AGGREGATE or not isinstance(current, WorldState):
            return
        if previous is not None and not isinstance(previous, WorldState):
            raise TypeError("世界快照更新前后类型不一致")
        before_presences = previous.presences if isinstance(previous, WorldState) else {}
        for presence_id, presence in before_presences.items():
            if presence_id not in current.presences:
                uow.delete_world_presence(
                    aggregate_id,
                    presence_id,
                    presence.revision,
                )
        for presence_id, presence in current.presences.items():
            prior = before_presences.get(presence_id)
            if prior is None:
                uow.insert_world_presence(
                    aggregate_id,
                    presence_id,
                    presence.owner_id,
                    presence.revision,
                    self.codec.dumps(presence),
                    logical_time.isoformat(),
                )
            elif prior != presence:
                uow.update_world_presence(
                    aggregate_id,
                    presence_id,
                    prior.revision,
                    presence.revision,
                    presence.owner_id,
                    self.codec.dumps(presence),
                    logical_time.isoformat(),
                )

        before_reservations = previous.reservations if isinstance(previous, WorldState) else {}
        for reservation_id in before_reservations:
            if reservation_id not in current.reservations:
                uow.delete_world_reservation(aggregate_id, reservation_id)
        for reservation_id, reservation in current.reservations.items():
            prior = before_reservations.get(reservation_id)
            if prior != reservation:
                uow.upsert_world_reservation(
                    aggregate_id,
                    reservation_id,
                    reservation.owner_id,
                    reservation.expires_at.isoformat()
                    if reservation.expires_at is not None
                    else None,
                    self.codec.dumps(reservation),
                    logical_time.isoformat(),
                )


def _revision_of(value: object) -> int:
    revision = getattr(value, "revision", None)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise TypeError(f"持久化聚合缺少有效 revision：{type(value).__name__}")
    return revision


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("持久化逻辑时间必须包含时区")


def _require_optional_aware(value: datetime | None) -> None:
    if value is not None:
        _require_aware(value)


__all__ = [
    "ACTIVITY_AGGREGATE",
    "ACTION_AGGREGATE",
    "CHARACTER_AGGREGATE",
    "CHARACTER_ROSTER_AGGREGATE",
    "EXCHANGE_AGGREGATE",
    "INVENTORY_AGGREGATE",
    "INSCRIPTION_PREFERENCE_AGGREGATE",
    "LEDGER_AGGREGATE",
    "LOADOUT_AGGREGATE",
    "LOOT_AGGREGATE",
    "REWARD_CLAIM_AGGREGATE",
    "SOCIAL_AGGREGATE",
    "PARTY_AGGREGATE",
    "SnapshotRepository",
    "WEAPON_AGGREGATE",
    "WORLD_AGGREGATE",
    "gameplay_snapshot_codec",
]
