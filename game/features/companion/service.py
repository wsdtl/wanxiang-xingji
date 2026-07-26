"""宠物捕获、人物结交、通用名册、配装与告别联合事务。"""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from math import ceil

from game.content.catalog.item import (
    COMPANION_SANCTUARY_ITEM_COMPONENT_ID,
    CompanionSanctuaryItemComponent,
)
from game.core.gameplay import (
    CharacterState,
    ConsumeStack,
    HEALTH_CURRENT,
    InscriptionPreference,
    InventoryState,
    InventoryTransaction,
    ItemStack,
    COMPANION_EXPERIENCE_ITEM_COMPONENT_ID,
    CompanionExperienceItemComponent,
    LoadoutState,
    RuleContext,
    Ruleset,
    SPIRIT_CURRENT,
    SeededRandomSource,
    WorldState,
)
from game.rules.battle_report import (
    BattleReportDraft,
    BattleReportSummary,
)
from game.rules.character import CharacterWorldState, MULTIVERSE_WORLD_STATE_ID
from game.rules.companion import (
    COMPANION_RULESET_VERSION,
    CompanionEngine,
    CompanionGrowthEngine,
    CompanionKind,
    CompanionRosterState,
    CompanionRuleError,
    CompanionSanctuaryState,
)
from .battle import CompanionSanctuaryBattleSimulator
from .models import (
    CompanionExperienceItemReceipt,
    CompanionExperienceItemResult,
    CompanionOperationReceipt,
    CompanionOperationResult,
    CompanionStorageKinds,
    CompanionView,
)


class CompanionFeature:
    """伙伴领域唯一写入口；命令组件不能直接操作快照。"""

    def __init__(
        self,
        database,
        content,
        world_views,
        snapshots,
        inventory_engine,
        battle_reports,
        engine: CompanionEngine,
        battle: CompanionSanctuaryBattleSimulator,
        player_activity,
        storage: CompanionStorageKinds,
        growth: CompanionGrowthEngine,
    ) -> None:
        self.database = database
        self.content = content
        self.world_views = world_views
        self.snapshots = snapshots
        self.inventory_engine = inventory_engine
        self.battle_reports = battle_reports
        self.engine = engine
        self.battle = battle
        self.player_activity = player_activity
        self.storage = storage
        self.growth = growth

    def use_experience_item(
        self,
        transaction_id: str,
        character_id: str,
        item_asset_id: str,
        companion_reference: str | None,
        *,
        logical_time,
    ) -> CompanionExperienceItemResult:
        fingerprint = _fingerprint(
            "experience_item",
            transaction_id,
            character_id,
            item_asset_id,
            companion_reference or "",
        )
        with self.database.unit_of_work() as uow:
            committed = uow.load_transaction(transaction_id)
            if committed is not None:
                if committed.fingerprint != fingerprint or committed.scope_id != character_id:
                    raise ValueError(f"同一伙伴经验事务 ID 对应不同内容：{transaction_id}")
                receipt = self.snapshots.codec.loads(
                    committed.receipt_payload,
                    CompanionExperienceItemReceipt,
                )
                if (
                    receipt.transaction_id != transaction_id
                    or receipt.actor_id != character_id
                    or receipt.item_asset_id != item_asset_id
                ):
                    raise ValueError("伙伴经验事务表与回执身份不一致")
                roster = self._load_roster(uow, character_id)
                return CompanionExperienceItemResult(
                    "used",
                    receipt,
                    roster.instances.get(receipt.companion_id),
                    replayed=True,
                )
            character = self.snapshots.require(
                uow,
                self.storage.character,
                character_id,
                CharacterState,
            )
            inventory = self.snapshots.require(
                uow,
                self.storage.inventory,
                character_id,
                InventoryState,
            )
            loadout = self.snapshots.require(
                uow,
                self.storage.loadout,
                character_id,
                LoadoutState,
            )
            roster = self._load_roster(uow, character_id)
            item = inventory.stacks.get(item_asset_id)
            if item is None or inventory.owner_of(item.id) != character_id:
                return CompanionExperienceItemResult("item_unknown", failure_message="找不到伙伴经验物品")
            if inventory.available_quantity(item.id) < 1:
                return CompanionExperienceItemResult("item_unavailable", failure_message="伙伴经验物品当前不可使用")
            definition = self.content.catalog.items.require(item.definition_id)
            component = definition.components.get(COMPANION_EXPERIENCE_ITEM_COMPONENT_ID)
            if not isinstance(component, CompanionExperienceItemComponent):
                return CompanionExperienceItemResult("item_invalid", failure_message="物品不是伙伴经验物品")
            companion = (
                roster.by_reference(companion_reference)
                if companion_reference
                else roster.companion_for_preset(loadout.active_preset_id)
            )
            if companion is None:
                return CompanionExperienceItemResult(
                    "companion_unknown",
                    failure_message=(
                        "找不到指定伙伴"
                        if companion_reference
                        else "当前配装没有出战伙伴，请补充伙伴编号"
                    ),
                )
            next_roster, growth = self.growth.grant_experience(
                roster,
                companion.id,
                component.maximum_experience,
                character_level=_character_level(character),
            )
            if growth.accepted == 0:
                return CompanionExperienceItemResult(
                    "level_capped",
                    failure_message="伙伴已经达到人物等级限制，物品没有消耗",
                )
            context = _context(transaction_id, logical_time, "experience_item")
            inventory_outcome = self.inventory_engine.execute(
                InventoryTransaction(
                    f"{transaction_id}:inventory",
                    character_id,
                    "companion.experience_item",
                    (ConsumeStack(item.id, 1),),
                ),
                state=inventory,
                context=context,
            )
            if inventory_outcome.failure or inventory_outcome.value is None:
                return CompanionExperienceItemResult(
                    "inventory_failed",
                    failure_message=(
                        inventory_outcome.failure.message
                        if inventory_outcome.failure
                        else "伙伴经验物品扣除失败"
                    ),
                )
            next_companion = next_roster.instances[companion.id]
            receipt = CompanionExperienceItemReceipt(
                transaction_id,
                character_id,
                item.id,
                definition.id,
                companion.id,
                growth.level_before,
                growth.level_after,
                growth.experience_before,
                growth.experience_after,
                growth.accepted,
            )
            self.snapshots.update(
                uow,
                self.storage.inventory,
                character_id,
                inventory,
                inventory_outcome.value.state,
                logical_time,
            )
            self.snapshots.update(
                uow,
                self.storage.roster,
                character_id,
                roster,
                next_roster,
                logical_time,
            )
            uow.insert_transaction(
                transaction_id,
                fingerprint,
                character_id,
                self.snapshots.codec.dumps(receipt),
                logical_time.isoformat(),
            )
            for sequence, event in enumerate(inventory_outcome.value.events):
                uow.append_fact(
                    transaction_id,
                    sequence,
                    event.kind,
                    self.snapshots.codec.dumps(event),
                    logical_time.isoformat(),
                )
            uow.commit()
            return CompanionExperienceItemResult("used", receipt, next_companion)

    def view(self, character_id: str, *, logical_time) -> CompanionView:
        with self.database.unit_of_work() as uow:
            roster = self._load_roster(uow, character_id)
            sanctuary = self.snapshots.load(
                uow,
                self.storage.sanctuary,
                character_id,
                CompanionSanctuaryState,
            )
            if sanctuary is not None:
                current = self.engine.expire(sanctuary, logical_time=logical_time)
                if current is not sanctuary:
                    self.snapshots.update(
                        uow,
                        self.storage.sanctuary,
                        character_id,
                        sanctuary,
                        current,
                        logical_time,
                    )
                    sanctuary = current
                    uow.commit()
            return CompanionView(roster, sanctuary)

    def gift_person(
        self,
        operation_id: str,
        character_id: str,
        item_asset_id: str,
        quantity: int,
        *,
        logical_time,
    ) -> CompanionOperationResult:
        fingerprint = _fingerprint("gift", character_id, item_asset_id, quantity)
        context = _context(operation_id, logical_time, "gift")
        with self.database.unit_of_work() as uow:
            replay = self._replay(uow, operation_id, fingerprint, character_id)
            if replay is not None:
                return self._replayed_result(uow, replay)
            roster, roster_exists = self._load_roster_entry(uow, character_id)
            person = self._person_here(uow, character_id)
            if person is None:
                return CompanionOperationResult(
                    "person_missing",
                    roster,
                    failure_message="当前位置没有可以赠礼的人物",
                )
            if quantity < 1:
                return CompanionOperationResult(
                    "quantity_invalid",
                    roster,
                    definition_id=str(person.id),
                    failure_message="赠礼数量必须大于零",
                )
            inventory = self.snapshots.require(
                uow,
                self.storage.inventory,
                character_id,
                InventoryState,
            )
            try:
                asset = inventory.asset(item_asset_id)
            except KeyError:
                return CompanionOperationResult(
                    "item_unknown",
                    roster,
                    definition_id=str(person.id),
                    failure_message="找不到要赠送的物品",
                )
            if not isinstance(asset, ItemStack) or inventory.owner_of(asset.id) != character_id:
                return CompanionOperationResult(
                    "item_invalid",
                    roster,
                    definition_id=str(person.id),
                    failure_message="这件物品不能作为礼物",
                )
            unit_value = person.gift_values.get(asset.definition_id)
            if unit_value is None:
                return CompanionOperationResult(
                    "gift_disliked",
                    roster,
                    definition_id=str(person.id),
                    failure_message=f"{person.name} 对这件物品没有兴趣",
                )
            available = inventory.available_quantity(asset.id)
            if available < 1:
                return CompanionOperationResult(
                    "item_unavailable",
                    roster,
                    definition_id=str(person.id),
                    failure_message="这件物品当前不可用",
                )
            previous = roster.person_bonds.get(person.id)
            before = previous.favor if previous is not None else 0
            if before >= person.bond_required:
                return CompanionOperationResult(
                    "bond_ready",
                    roster,
                    definition_id=str(person.id),
                    value_before=before,
                    value_after=before,
                    failure_message="关系已经满足结交要求，不必继续赠礼",
                )
            needed = ceil((person.bond_required - before) / unit_value)
            consumed = min(quantity, available, needed)
            try:
                next_roster, value_before, value_after = self.engine.give_gift(
                    roster,
                    person.id,
                    unit_value * consumed,
                    logical_time=logical_time,
                )
            except CompanionRuleError as exc:
                return CompanionOperationResult(
                    exc.code,
                    roster,
                    definition_id=str(person.id),
                    failure_message=str(exc),
                )
            inventory_outcome = self.inventory_engine.execute(
                InventoryTransaction(
                    f"{operation_id}:inventory",
                    character_id,
                    "companion.person.gift",
                    (ConsumeStack(asset.id, consumed),),
                ),
                state=inventory,
                context=context,
            )
            if inventory_outcome.failure or inventory_outcome.value is None:
                return CompanionOperationResult(
                    "item_consume_failed",
                    roster,
                    definition_id=str(person.id),
                    failure_message=(
                        inventory_outcome.failure.message
                        if inventory_outcome.failure
                        else "赠礼物品扣除失败"
                    ),
                )
            self.snapshots.update(
                uow,
                self.storage.inventory,
                character_id,
                inventory,
                inventory_outcome.value.state,
                logical_time,
            )
            if roster_exists:
                self.snapshots.update(
                    uow,
                    self.storage.roster,
                    character_id,
                    roster,
                    next_roster,
                    logical_time,
                )
            else:
                self.snapshots.insert(
                    uow,
                    self.storage.roster,
                    character_id,
                    next_roster,
                    logical_time,
                )
            receipt = CompanionOperationReceipt(
                operation_id,
                character_id,
                "gift",
                definition_id=str(person.id),
                value_before=value_before,
                value_after=value_after,
                quantity=consumed,
            )
            self._commit_receipt(uow, receipt, fingerprint, logical_time)
            uow.commit()
            return CompanionOperationResult(
                "gifted",
                next_roster,
                definition_id=str(person.id),
                value_before=value_before,
                value_after=value_after,
                quantity=consumed,
            )

    def join_person(
        self,
        operation_id: str,
        character_id: str,
        *,
        logical_time,
    ) -> CompanionOperationResult:
        fingerprint = _fingerprint("join_person", character_id)
        with self.database.unit_of_work() as uow:
            replay = self._replay(uow, operation_id, fingerprint, character_id)
            if replay is not None:
                return self._replayed_result(uow, replay)
            roster, roster_exists = self._load_roster_entry(uow, character_id)
            person = self._person_here(uow, character_id)
            if person is None:
                return CompanionOperationResult(
                    "person_missing",
                    roster,
                    failure_message="当前位置没有可以结交的人物",
                )
            character = self.snapshots.require(
                uow,
                self.storage.character,
                character_id,
                CharacterState,
            )
            try:
                next_roster, companion, restored = self.engine.join_person(
                    roster,
                    person.id,
                    _character_level(character),
                    logical_time=logical_time,
                )
            except CompanionRuleError as exc:
                return CompanionOperationResult(
                    exc.code,
                    roster,
                    definition_id=str(person.id),
                    failure_message=str(exc),
                )
            if roster_exists:
                self.snapshots.update(
                    uow,
                    self.storage.roster,
                    character_id,
                    roster,
                    next_roster,
                    logical_time,
                )
            else:
                self.snapshots.insert(
                    uow,
                    self.storage.roster,
                    character_id,
                    next_roster,
                    logical_time,
                )
            receipt = CompanionOperationReceipt(
                operation_id,
                character_id,
                "join_person",
                companion_id=companion.id,
                definition_id=str(person.id),
                value_after=int(restored),
            )
            self._commit_receipt(uow, receipt, fingerprint, logical_time)
            uow.commit()
            return CompanionOperationResult(
                "rejoined" if restored else "joined",
                next_roster,
                companion=companion,
                definition_id=str(person.id),
            )

    def open_sanctuary(
        self,
        operation_id: str,
        character: CharacterState,
        dimension: CharacterWorldState,
        item_asset_id: str,
        *,
        logical_time,
    ) -> CompanionOperationResult:
        fingerprint = _fingerprint(
            "open",
            character.id,
            dimension.world_id,
            item_asset_id,
        )
        context = _context(operation_id, logical_time, "open")
        with self.database.unit_of_work() as uow:
            replay = self._replay(uow, operation_id, fingerprint, character.id)
            if replay is not None:
                return self._replayed_result(uow, replay)
            roster, roster_exists = self._load_roster_entry(uow, character.id)
            previous = self.snapshots.load(
                uow,
                self.storage.sanctuary,
                character.id,
                CompanionSanctuaryState,
            )
            inventory = self.snapshots.require(
                uow,
                self.storage.inventory,
                character.id,
                InventoryState,
            )
            try:
                item_asset = inventory.asset(item_asset_id)
            except KeyError:
                return CompanionOperationResult(
                    "item_unknown",
                    roster,
                    previous,
                    failure_message="找不到要使用的秘境凭证",
                )
            if inventory.owner_of(item_asset.id) != character.id:
                return CompanionOperationResult(
                    "item_forbidden",
                    roster,
                    previous,
                    failure_message="秘境凭证不属于当前角色",
                )
            definition = self.content.catalog.items.require(item_asset.definition_id)
            component = definition.components.get(COMPANION_SANCTUARY_ITEM_COMPONENT_ID)
            if not isinstance(component, CompanionSanctuaryItemComponent):
                return CompanionOperationResult(
                    "item_invalid",
                    roster,
                    previous,
                    failure_message="这件物品不能开启宠物秘境",
                )
            if inventory.available_quantity(item_asset.id) < component.quantity:
                return CompanionOperationResult(
                    "item_unavailable",
                    roster,
                    previous,
                    failure_message="秘境凭证当前被其他流程占用",
                )
            try:
                sanctuary = self.engine.open_sanctuary(
                    roster,
                    previous,
                    session_id=f"companion-sanctuary:{operation_id}",
                    world_id=dimension.world_id,
                    character_level=_character_level(character),
                    content_version=self.content.catalog.report.content_fingerprint,
                    logical_time=logical_time,
                    random=context.random,
                )
            except (CompanionRuleError, KeyError) as exc:
                return CompanionOperationResult(
                    getattr(exc, "code", "world_unavailable"),
                    roster,
                    previous,
                    failure_message=str(exc),
                )
            inventory_outcome = self.inventory_engine.execute(
                InventoryTransaction(
                    f"{operation_id}:inventory",
                    character.id,
                    "companion.sanctuary.open",
                    (ConsumeStack(item_asset.id, component.quantity),),
                ),
                state=inventory,
                context=context,
            )
            if inventory_outcome.failure or inventory_outcome.value is None:
                return CompanionOperationResult(
                    "item_consume_failed",
                    roster,
                    previous,
                    failure_message=(
                        inventory_outcome.failure.message
                        if inventory_outcome.failure
                        else "秘境凭证扣除失败"
                    ),
                )
            self.snapshots.update(
                uow,
                self.storage.inventory,
                character.id,
                inventory,
                inventory_outcome.value.state,
                logical_time,
            )
            if not roster_exists:
                self.snapshots.insert(
                    uow,
                    self.storage.roster,
                    character.id,
                    roster,
                    logical_time,
                )
            if previous is None:
                self.snapshots.insert(
                    uow,
                    self.storage.sanctuary,
                    character.id,
                    sanctuary,
                    logical_time,
                )
            else:
                self.snapshots.update(
                    uow,
                    self.storage.sanctuary,
                    character.id,
                    previous,
                    sanctuary,
                    logical_time,
                )
            receipt = CompanionOperationReceipt(
                operation_id,
                character.id,
                "open",
                sanctuary.session_id,
            )
            self._commit_receipt(uow, receipt, fingerprint, logical_time)
            uow.commit()
            return CompanionOperationResult("opened", roster, sanctuary)

    def hunt(
        self,
        operation_id: str,
        character_id: str,
        trace_index: int,
        *,
        logical_time,
    ) -> CompanionOperationResult:
        fingerprint = _fingerprint("hunt", character_id, trace_index)
        context = _context(operation_id, logical_time, "hunt")
        with self.database.unit_of_work() as uow:
            replay = self._replay(uow, operation_id, fingerprint, character_id)
            if replay is not None:
                return self._replayed_result(uow, replay)
            roster = self._load_roster(uow, character_id)
            sanctuary = self.snapshots.load(
                uow,
                self.storage.sanctuary,
                character_id,
                CompanionSanctuaryState,
            )
            if sanctuary is None:
                return CompanionOperationResult(
                    "sanctuary_missing",
                    roster,
                    failure_message="当前没有已经开启的宠物秘境",
                )
            if (
                sanctuary.content_version
                != self.content.catalog.report.content_fingerprint
            ):
                return CompanionOperationResult(
                    "content_changed",
                    roster,
                    sanctuary,
                    failure_message="内容已经更新，本次伙伴秘境不能继续，请联系维护者处理",
                )
            dimension = self.snapshots.require(
                uow,
                self.storage.character_world,
                character_id,
                CharacterWorldState,
            )
            if dimension.world_id != sanctuary.world_id:
                return CompanionOperationResult(
                    "wrong_world",
                    roster,
                    sanctuary,
                    failure_message="必须返回开启秘境的世界才能继续追踪",
                )
            activity_block = self.player_activity.block_in_uow(uow, character_id)
            if activity_block is not None:
                return CompanionOperationResult(
                    activity_block.status,
                    roster,
                    sanctuary,
                    activity_block=activity_block,
                )
            character = self.snapshots.require(
                uow,
                self.storage.character,
                character_id,
                CharacterState,
            )
            if character.resources[HEALTH_CURRENT] <= 0:
                return CompanionOperationResult(
                    "health_depleted",
                    roster,
                    sanctuary,
                    failure_message="当前血气已经归零，恢复后才能追踪伙伴",
                )
            inventory = self.snapshots.require(
                uow,
                self.storage.inventory,
                character_id,
                InventoryState,
            )
            loadout = self.snapshots.require(
                uow,
                self.storage.loadout,
                character_id,
                LoadoutState,
            )
            inscription_preference = self.snapshots.load(
                uow,
                self.storage.inscription_preference,
                character_id,
                InscriptionPreference,
            )
            try:
                selected = self.engine.select_trace(
                    sanctuary,
                    trace_index,
                    logical_time=logical_time,
                )
            except CompanionRuleError as exc:
                return CompanionOperationResult(
                    exc.code,
                    roster,
                    sanctuary,
                    failure_message=str(exc),
                )
            target = selected.selected_trace()
            if target is None:
                raise RuntimeError("伙伴追猎缺少已锁定踪迹")
            battle = self.battle.simulate(
                selected.session_id,
                target,
                character=character,
                inventory=inventory,
                loadout=loadout,
                roster=roster,
                context=context,
            )
            resources = dict(character.resources)
            resources[HEALTH_CURRENT] = battle.player_health_after
            resources[SPIRIT_CURRENT] = battle.player_spirit_after
            next_character = character
            if resources != dict(character.resources):
                next_character = replace(
                    character,
                    resources=resources,
                    revision=character.revision + 1,
                )
                self.snapshots.update(
                    uow,
                    self.storage.character,
                    character_id,
                    character,
                    next_character,
                    logical_time,
                )
            companion = None
            if battle.victory:
                next_roster, next_sanctuary, companion = self.engine.capture(
                    roster,
                    selected,
                    logical_time=logical_time,
                )
                self.snapshots.update(
                    uow,
                    self.storage.roster,
                    character_id,
                    roster,
                    next_roster,
                    logical_time,
                )
            else:
                next_roster = roster
                next_sanctuary = self.engine.record_failed_attempt(
                    selected,
                    logical_time=logical_time,
                )
            next_sanctuary = replace(
                next_sanctuary,
                revision=sanctuary.revision + 1,
            )
            self.snapshots.update(
                uow,
                self.storage.sanctuary,
                character_id,
                sanctuary,
                next_sanctuary,
                logical_time,
            )
            report = self.battle_reports.capture_in_uow(
                uow,
                self._battle_report(
                    character,
                    dimension,
                    inventory,
                    roster,
                    loadout,
                    inscription_preference,
                    selected,
                    battle,
                    logical_time,
                ),
            )
            receipt = CompanionOperationReceipt(
                operation_id,
                character_id,
                "hunt",
                selected.session_id,
                companion.id if companion is not None else "",
                report.report_id,
            )
            self._commit_receipt(uow, receipt, fingerprint, logical_time)
            uow.commit()
            return CompanionOperationResult(
                "captured" if companion is not None else "defeated",
                next_roster,
                next_sanctuary,
                companion,
                report,
                battle,
            )

    def bind(
        self,
        operation_id: str,
        character_id: str,
        reference: str,
        *,
        allow_transfer: bool,
        expected_revision: int | None = None,
        logical_time,
    ) -> CompanionOperationResult:
        fingerprint = _fingerprint(
            "bind",
            character_id,
            reference,
            int(allow_transfer),
            expected_revision,
        )
        with self.database.unit_of_work() as uow:
            replay = self._replay(uow, operation_id, fingerprint, character_id)
            if replay is not None:
                return self._replayed_result(uow, replay)
            roster = self._load_roster(uow, character_id)
            if expected_revision is not None and roster.revision != expected_revision:
                return CompanionOperationResult(
                    "stale",
                    roster,
                    failure_message="伙伴名册已经变化，请重新选择出战伙伴",
                )
            companion = roster.by_reference(reference)
            if companion is None:
                return CompanionOperationResult(
                    "companion_unknown",
                    roster,
                    failure_message="找不到这名伙伴",
                )
            loadout = self.snapshots.require(
                uow,
                self.storage.loadout,
                character_id,
                LoadoutState,
            )
            if loadout.active_preset_id is None:
                return CompanionOperationResult(
                    "preset_missing",
                    roster,
                    companion=companion,
                    failure_message="当前没有激活配装",
                )
            previous_preset = roster.preset_for_companion(companion.id)
            if (
                previous_preset is not None
                and previous_preset != loadout.active_preset_id
                and not allow_transfer
            ):
                return CompanionOperationResult(
                    "transfer_required",
                    roster,
                    companion=companion,
                    previous_preset_id=str(previous_preset),
                )
            next_roster = self.engine.bind(
                roster,
                companion.id,
                loadout.active_preset_id,
                allow_transfer=allow_transfer,
            )
            if next_roster is roster:
                return CompanionOperationResult("already_bound", roster, companion=companion)
            self.snapshots.update(
                uow,
                self.storage.roster,
                character_id,
                roster,
                next_roster,
                logical_time,
            )
            receipt = CompanionOperationReceipt(
                operation_id,
                character_id,
                "bind",
                companion_id=companion.id,
            )
            self._commit_receipt(uow, receipt, fingerprint, logical_time)
            uow.commit()
            return CompanionOperationResult(
                "transferred" if previous_preset is not None else "bound",
                next_roster,
                companion=companion,
                previous_preset_id=(str(previous_preset) if previous_preset else None),
            )

    def unbind_current(
        self,
        operation_id: str,
        character_id: str,
        *,
        logical_time,
    ) -> CompanionOperationResult:
        fingerprint = _fingerprint("unbind", character_id)
        with self.database.unit_of_work() as uow:
            replay = self._replay(uow, operation_id, fingerprint, character_id)
            if replay is not None:
                return self._replayed_result(uow, replay)
            roster = self._load_roster(uow, character_id)
            loadout = self.snapshots.require(
                uow,
                self.storage.loadout,
                character_id,
                LoadoutState,
            )
            if loadout.active_preset_id is None:
                return CompanionOperationResult("preset_missing", roster)
            companion = roster.companion_for_preset(loadout.active_preset_id)
            next_roster = self.engine.unbind(roster, loadout.active_preset_id)
            if next_roster is roster:
                return CompanionOperationResult("already_unbound", roster)
            self.snapshots.update(
                uow,
                self.storage.roster,
                character_id,
                roster,
                next_roster,
                logical_time,
            )
            receipt = CompanionOperationReceipt(
                operation_id,
                character_id,
                "unbind",
                companion_id=companion.id if companion is not None else "",
            )
            self._commit_receipt(uow, receipt, fingerprint, logical_time)
            uow.commit()
            return CompanionOperationResult("unbound", next_roster, companion=companion)

    def farewell(
        self,
        operation_id: str,
        character_id: str,
        reference: str,
        expected_revision: int,
        *,
        logical_time,
    ) -> CompanionOperationResult:
        fingerprint = _fingerprint(
            "farewell",
            character_id,
            reference,
            expected_revision,
        )
        with self.database.unit_of_work() as uow:
            replay = self._replay(uow, operation_id, fingerprint, character_id)
            if replay is not None:
                return self._replayed_result(uow, replay)
            roster = self._load_roster(uow, character_id)
            if roster.revision != expected_revision:
                return CompanionOperationResult(
                    "stale",
                    roster,
                    failure_message="伙伴名册已经变化，请重新打开伙伴列表",
                )
            companion = roster.by_reference(reference)
            if companion is None:
                return CompanionOperationResult(
                    "companion_unknown",
                    roster,
                    failure_message="找不到要告别的伙伴",
                )
            next_roster = self.engine.farewell(roster, companion.id)
            self.snapshots.update(
                uow,
                self.storage.roster,
                character_id,
                roster,
                next_roster,
                logical_time,
            )
            receipt = CompanionOperationReceipt(
                operation_id,
                character_id,
                "farewell",
                companion_id=companion.id,
                definition_id=str(companion.definition_id),
                value_after=int(companion.kind is CompanionKind.PERSON),
            )
            self._commit_receipt(uow, receipt, fingerprint, logical_time)
            uow.commit()
            return CompanionOperationResult(
                "person_departed" if companion.kind is CompanionKind.PERSON else "pet_departed",
                next_roster,
                companion=companion,
                definition_id=str(companion.definition_id),
            )

    def abandon(
        self,
        operation_id: str,
        character_id: str,
        expected_revision: int,
        *,
        logical_time,
    ) -> CompanionOperationResult:
        fingerprint = _fingerprint("abandon", character_id, expected_revision)
        with self.database.unit_of_work() as uow:
            replay = self._replay(uow, operation_id, fingerprint, character_id)
            if replay is not None:
                return self._replayed_result(uow, replay)
            roster = self._load_roster(uow, character_id)
            sanctuary = self.snapshots.load(
                uow,
                self.storage.sanctuary,
                character_id,
                CompanionSanctuaryState,
            )
            if sanctuary is None:
                return CompanionOperationResult("sanctuary_missing", roster)
            if sanctuary.revision != expected_revision:
                return CompanionOperationResult("stale", roster, sanctuary)
            next_sanctuary = self.engine.abandon(
                sanctuary,
                logical_time=logical_time,
            )
            if next_sanctuary is sanctuary:
                return CompanionOperationResult("sanctuary_inactive", roster, sanctuary)
            self.snapshots.update(
                uow,
                self.storage.sanctuary,
                character_id,
                sanctuary,
                next_sanctuary,
                logical_time,
            )
            receipt = CompanionOperationReceipt(
                operation_id,
                character_id,
                "abandon",
                sanctuary.session_id,
            )
            self._commit_receipt(uow, receipt, fingerprint, logical_time)
            uow.commit()
            return CompanionOperationResult("abandoned", roster, next_sanctuary)

    def _battle_report(
        self,
        character,
        character_world,
        inventory,
        roster,
        loadout,
        inscription_preference,
        sanctuary,
        battle,
        logical_time,
    ) -> BattleReportDraft:
        target_trace = sanctuary.selected_trace()
        if target_trace is None:
            raise RuntimeError("伙伴战报缺少追踪目标")
        target_species = self.content.companions.species.require(
            target_trace.definition_id
        )
        combatants = [
            self.battle_reports.builder.character(
                character,
                character_world,
                inventory,
                loadout,
                team_id="player",
                team_label="追猎者一方",
                inscription_preference=inscription_preference,
            )
        ]
        own_companion = roster.companion_for_preset(loadout.active_preset_id)
        if own_companion is not None:
            combatants.append(
                self.battle_reports.builder.companion(
                    own_companion,
                    team_id="player",
                    team_label="追猎者一方",
                )
            )
        combatants.append(
            self.battle_reports.builder.companion(
                target_trace,
                team_id="target",
                team_label="秘境目标",
                unit_kind="wild_companion",
                entity_id=battle.target_id,
                label_prefix="野生·",
            )
        )
        view = self.world_views.require(sanctuary.world_id)
        outcome = "追猎成功" if battle.victory else "追猎失败"
        report_id = (
            f"battle-report:companion:{sanctuary.session_id}:"
            f"attempt:{sanctuary.attempt_count + 1}"
        )
        return BattleReportDraft(
            report_id=report_id,
            mode_id="battle.mode.companion_sanctuary",
            content_fingerprint=self.content.catalog.report.content_fingerprint,
            summary=BattleReportSummary(
                f"{view.projector.name('term.companion_sanctuary')}·{target_species.name}",
                outcome,
                (
                    f"战斗行动: {battle.turns}",
                    f"角色余血: {battle.player_health_after:.0f}",
                ),
                "victory" if battle.victory else "defeat",
            ),
            segment=self.battle_reports.builder.segment(
                segment_id=f"{sanctuary.session_id}:{sanctuary.attempt_count + 1}",
                title=f"追踪 {target_species.name}",
                trace=battle.trace,
                combatants=combatants,
                outcome=outcome,
                started_at=logical_time,
                finished_at=logical_time,
            ),
        )

    def _replay(self, uow, transaction_id, fingerprint, actor_id):
        committed = uow.load_transaction(transaction_id)
        if committed is None:
            return None
        if committed.fingerprint != fingerprint or committed.scope_id != actor_id:
            raise ValueError(f"同一伙伴事务 ID 对应不同内容: {transaction_id}")
        return self.snapshots.codec.loads(
            committed.receipt_payload,
            CompanionOperationReceipt,
        )

    def _replayed_result(self, uow, receipt):
        roster = self._load_roster(uow, receipt.actor_id)
        sanctuary = self.snapshots.load(
            uow,
            self.storage.sanctuary,
            receipt.actor_id,
            CompanionSanctuaryState,
        )
        companion = roster.instances.get(receipt.companion_id)
        if companion is None:
            companion = next(
                (
                    value for value in roster.departed_people.values()
                    if value.id == receipt.companion_id
                ),
                None,
            )
        report = (
            self.battle_reports.reference(receipt.battle_report_id)
            if receipt.battle_report_id
            else None
        )
        status = {
            "open": "opened",
            "hunt": "captured" if companion is not None else "defeated",
            "bind": "bound",
            "unbind": "unbound",
            "farewell": "person_departed" if receipt.value_after else "pet_departed",
            "abandon": "abandoned",
            "gift": "gifted",
            "join_person": "rejoined" if receipt.value_after else "joined",
        }[receipt.operation]
        return CompanionOperationResult(
            status,
            roster,
            sanctuary,
            companion,
            report,
            definition_id=receipt.definition_id,
            value_before=receipt.value_before,
            value_after=receipt.value_after,
            quantity=receipt.quantity,
            replayed=True,
        )

    def _commit_receipt(self, uow, receipt, fingerprint, logical_time):
        uow.insert_transaction(
            receipt.transaction_id,
            fingerprint,
            receipt.actor_id,
            self.snapshots.codec.dumps(receipt),
            logical_time.isoformat(),
        )

    def _load_roster(self, uow, character_id: str) -> CompanionRosterState:
        return self._load_roster_entry(uow, character_id)[0]

    def _load_roster_entry(self, uow, character_id: str):
        roster = self.snapshots.load(
            uow,
            self.storage.roster,
            character_id,
            CompanionRosterState,
        )
        return (roster or CompanionRosterState(character_id), roster is not None)

    def _person_here(self, uow, character_id: str):
        dimension = self.snapshots.require(
            uow,
            self.storage.character_world,
            character_id,
            CharacterWorldState,
        )
        world = self.snapshots.require(
            uow,
            self.storage.world,
            MULTIVERSE_WORLD_STATE_ID,
            WorldState,
        )
        presence = next(
            (value for value in world.presences.values() if value.owner_id == character_id),
            None,
        )
        if presence is None:
            return None
        resolved = self.content.worlds.resolve_position(
            dimension.world_id,
            presence.position,
            function_id="location.function.companion_person",
        )
        if resolved is None:
            return None
        try:
            return self.content.companions.people.require(
                resolved.require_content_ref()
            )
        except KeyError:
            return None


def _character_level(character: CharacterState) -> int:
    return next(iter(character.progressions.values())).level


def _context(trace_id: str, logical_time, phase: str) -> RuleContext:
    return RuleContext(
        trace_id,
        COMPANION_RULESET_VERSION,
        Ruleset(
            f"ruleset.companion.{phase}",
        ),
        logical_time,
        SeededRandomSource(trace_id),
    )


def _fingerprint(*values: object) -> str:
    payload = "\0".join(str(value) for value in values)
    return sha256(payload.encode("utf-8")).hexdigest()


__all__ = ["CompanionFeature"]
