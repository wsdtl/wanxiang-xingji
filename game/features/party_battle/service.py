"""组队挑战选择、准备、战斗、原子结算与战报协调。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from hashlib import sha256
from zoneinfo import ZoneInfo

from game.content.catalog import CHARACTER_LEVEL_PROGRESSION_ID, CHARACTER_MAXIMUM_LEVEL
from game.content.catalog.enemy import PARTY_BOSS_ENCOUNTER_ID, PARTY_BOSS_LOOT_TABLE_ID
from game.content.catalog.social import (
    PARTY_BATTLE_DAY_RESET_HOUR,
    PARTY_BATTLE_MINIMUM_MEMBERS,
)
from game.features.errors import StalePreparationError
from game.core.gameplay import (
    HEALTH_CURRENT,
    SPIRIT_CURRENT,
    ActionSlotKind,
    ActionState,
    CharacterState,
    InscriptionPreference,
    InventoryState,
    LoadoutState,
    LootRollCommand,
    LootState,
    PartyState,
    PartyStatus,
    RewardClaimState,
    RewardExpectations,
    RewardSettlement,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    WeaponState,
)
from game.rules.battle_report import (
    BattleReportDraft,
    BattleReportSummary,
)
from game.rules.character import CharacterWorldState, PRIMARY_LEDGER_ID
from game.rules.companion import CompanionRosterState
from game.rules.encounter import EnemyEncounterGenerator
from game.rules.exploration import ExplorationState, ExplorationStatus

from .battle import PartyBattleSimulator
from .models import (
    PARTY_BATTLE_CHALLENGE_AGGREGATE,
    PARTY_BATTLE_DAILY_AGGREGATE,
    PARTY_BATTLE_DAILY_WINS,
    PARTY_BATTLE_RULE_VERSION,
    PARTY_BATTLE_SOURCE_KIND,
    PartyBattleChallengeState,
    PartyBattleDailyState,
    PartyBattleOperationReceipt,
    PartyBattleResult,
    PartyBattleSelectionResult,
)
from .rewards import PartyBattleRewardFactory


@dataclass(frozen=True)
class PartyBattleStorageKinds:
    party: str
    character: str
    inventory: str
    loadout: str
    companion_roster: str
    action: str
    exploration: str
    reward_claim: str
    weapon: str
    character_world: str
    inscription_preference: str


@dataclass(frozen=True)
class _PartyMemberInputs:
    character: CharacterState
    inventory: InventoryState
    loadout: LoadoutState
    roster: CompanionRosterState
    action: ActionState | None
    exploration: ExplorationState | None
    character_world: CharacterWorldState
    inscription_preference: InscriptionPreference | None
    loadout_fingerprint: str


@dataclass(frozen=True)
class _PreparedPartyChallenge:
    party: object
    challenge: PartyBattleChallengeState
    members: tuple[_PartyMemberInputs, ...]
    battle: object
    enemy_name: str
    context: RuleContext
    report: object


_STALE_CHALLENGE = object()


class PartyBattleFeature:
    """组队挑战唯一写入口；跨玩家状态始终在同一事务中提交。"""

    def __init__(
        self,
        database,
        content,
        world_views,
        snapshots,
        rewards,
        battle_reports,
        player_lineup,
        storage: PartyBattleStorageKinds,
        reward_keys_factory,
        companion_growth,
        *,
        party_scope_id: str,
        timezone: str,
    ) -> None:
        self.database = database
        self.content = content
        self.world_views = world_views
        self.snapshots = snapshots
        self.rewards = rewards
        self.battle_reports = battle_reports
        self.storage = storage
        self.reward_keys_factory = reward_keys_factory
        self.companion_growth = companion_growth
        self.party_scope_id = party_scope_id
        self.timezone = ZoneInfo(timezone)
        self.encounters = EnemyEncounterGenerator(
            content.catalog.enemies,
            content_version=content.catalog.report.content_fingerprint,
        )
        self.battles = PartyBattleSimulator(content.catalog, player_lineup)
        self.reward_factory = PartyBattleRewardFactory(content)

    def view(self, party_id: str) -> PartyBattleSelectionResult:
        normalized = _identity(party_id, "队伍")
        with self.database.unit_of_work(write=False) as uow:
            challenge = self.snapshots.load(
                uow,
                PARTY_BATTLE_CHALLENGE_AGGREGATE,
                normalized,
                PartyBattleChallengeState,
            )
        return PartyBattleSelectionResult(
            "selected" if challenge is not None and challenge.status == "selected" else "completed" if challenge is not None else "empty",
            challenge,
        )

    def select(
        self,
        operation_id: str,
        party_id: str,
        actor_id: str,
        level: int,
        *,
        logical_time: datetime,
    ) -> PartyBattleSelectionResult:
        _aware(logical_time)
        operation_id = _identity(operation_id, "操作")
        party_id = _identity(party_id, "队伍")
        actor_id = _identity(actor_id, "角色")
        if not 1 <= int(level) <= CHARACTER_MAXIMUM_LEVEL:
            return PartyBattleSelectionResult(
                "invalid_level",
                failure_message=f"挑战等级必须位于 1 到 {CHARACTER_MAXIMUM_LEVEL}",
            )
        fingerprint = _operation_fingerprint("select", party_id, actor_id, str(level))
        context = _context(operation_id, logical_time)
        with self.database.unit_of_work() as uow:
            replay = self._replay(uow, operation_id, fingerprint, party_id)
            if replay is not None:
                challenge = self._load_challenge(uow, party_id)
                return PartyBattleSelectionResult("replayed", challenge)
            party = self._party(uow, party_id)
            failure = self._leader_failure(party, actor_id)
            if failure:
                return PartyBattleSelectionResult("unavailable", failure_message=failure)
            if len(party.members) < PARTY_BATTLE_MINIMUM_MEMBERS:
                return PartyBattleSelectionResult(
                    "too_few_members",
                    failure_message=f"组队挑战至少需要{PARTY_BATTLE_MINIMUM_MEMBERS}名玩家",
                )
            previous = self._load_challenge(uow, party_id)
            if previous is not None and previous.status == "selected":
                return PartyBattleSelectionResult("already_selected", previous, "当前首领尚未击破")

            source_id = context.random.choice(self.content.party_bosses.source_ids())
            source = self.content.party_bosses.require(source_id)
            session_id = f"party-battle:{sha256(operation_id.encode('utf-8')).hexdigest()[:24]}"
            encounter = self.encounters.generate(
                PARTY_BOSS_ENCOUNTER_ID,
                level=int(level),
                generation_seed=session_id,
                random=context.random,
                instance_id=f"encounter:{session_id}",
                allowed_enemy_ids=source.enemy_ids,
                behavior_weights=(
                    self.content.enemy_behavior_profiles.require(source_id).behavior_weights
                ),
            )
            challenge = PartyBattleChallengeState(
                party.id,
                session_id,
                actor_id,
                source_id,
                int(level),
                encounter,
                {key: value.slot for key, value in party.members.items()},
                selected_at=logical_time,
                revision=0 if previous is None else previous.revision + 1,
            )
            self._clear_party_ready(uow, party, logical_time)
            self._save_challenge(uow, previous, challenge, logical_time)
            self._record_receipt(
                uow,
                PartyBattleOperationReceipt(operation_id, actor_id, "select", "selected"),
                fingerprint,
                party_id,
                logical_time,
            )
            uow.commit()
            return PartyBattleSelectionResult("selected", challenge)

    def set_ready(
        self,
        operation_id: str,
        party_id: str,
        actor_id: str,
        ready: bool,
        *,
        logical_time: datetime,
    ) -> PartyBattleSelectionResult:
        _aware(logical_time)
        operation_id = _identity(operation_id, "操作")
        party_id = _identity(party_id, "队伍")
        actor_id = _identity(actor_id, "角色")
        fingerprint = _operation_fingerprint("ready", party_id, actor_id, str(bool(ready)))
        with self.database.unit_of_work() as uow:
            replay = self._replay(uow, operation_id, fingerprint, party_id)
            if replay is not None:
                return PartyBattleSelectionResult("replayed", self._load_challenge(uow, party_id))
            party = self._party(uow, party_id)
            if party is None or actor_id not in party.members:
                return PartyBattleSelectionResult("not_member", failure_message="当前角色不在这支队伍中")
            challenge = self._load_challenge(uow, party_id)
            if challenge is None or challenge.status != "selected":
                return PartyBattleSelectionResult(
                    "no_challenge",
                    challenge,
                    "当前没有已锁定的组队挑战",
                )
            if dict(challenge.member_slots) != {
                key: value.slot for key, value in party.members.items()
            }:
                return PartyBattleSelectionResult("party_changed", challenge, "队伍成员已经变化，请由队长重新选择挑战")
            values = dict(challenge.ready_fingerprints)
            if ready:
                values[actor_id] = self._loadout_fingerprint(uow, actor_id)
            else:
                values.pop(actor_id, None)
            next_challenge = replace(
                challenge,
                ready_fingerprints=values,
                revision=challenge.revision + 1,
            )
            self._set_party_ready(uow, party, actor_id, ready, logical_time)
            self.snapshots.update(
                uow,
                PARTY_BATTLE_CHALLENGE_AGGREGATE,
                party_id,
                challenge,
                next_challenge,
                logical_time,
            )
            status = "ready" if ready else "unready"
            self._record_receipt(
                uow,
                PartyBattleOperationReceipt(operation_id, actor_id, status, status),
                fingerprint,
                party_id,
                logical_time,
            )
            uow.commit()
            return PartyBattleSelectionResult(status, next_challenge)

    def challenge(
        self,
        operation_id: str,
        party_id: str,
        actor_id: str,
        *,
        logical_time: datetime,
    ) -> PartyBattleResult:
        _aware(logical_time)
        operation_id = _identity(operation_id, "操作")
        party_id = _identity(party_id, "队伍")
        actor_id = _identity(actor_id, "角色")
        fingerprint = _operation_fingerprint("challenge", party_id, actor_id)
        for _ in range(2):
            prepared = self._prepare_challenge(
                operation_id,
                party_id,
                actor_id,
                fingerprint,
                logical_time,
            )
            if isinstance(prepared, PartyBattleResult):
                return prepared
            result = self._commit_challenge(
                operation_id,
                party_id,
                actor_id,
                fingerprint,
                logical_time,
                prepared,
            )
            if result is not _STALE_CHALLENGE:
                return result
        raise StalePreparationError("组队挑战准备结果连续过期，请重新发起")

    def _prepare_challenge(
        self,
        operation_id: str,
        party_id: str,
        actor_id: str,
        fingerprint: str,
        logical_time: datetime,
    ) -> _PreparedPartyChallenge | PartyBattleResult:
        with self.database.unit_of_work(write=False) as uow:
            replay = self._replay(uow, operation_id, fingerprint, party_id)
            if replay is not None:
                return self._replayed_result(uow, party_id, replay)
            party = self._party(uow, party_id)
            failure = self._leader_failure(party, actor_id)
            if failure:
                return PartyBattleResult("unavailable", failure_message=failure)
            challenge = self._load_challenge(uow, party_id)
            if challenge is None or challenge.status != "selected":
                return PartyBattleResult("no_challenge", challenge, failure_message="当前没有可挑战的组队首领")
            if dict(challenge.member_slots) != {
                key: value.slot for key, value in party.members.items()
            }:
                return PartyBattleResult("party_changed", challenge, failure_message="队伍成员已经变化，请重新选择挑战")
            if set(challenge.ready_fingerprints) != set(party.members):
                return PartyBattleResult("not_ready", challenge, failure_message="仍有队员没有准备")

            members = []
            for member in sorted(party.members.values(), key=lambda value: value.slot):
                character_id = member.subject_id
                inputs = self._load_member_inputs(uow, character_id)
                occupied = self._occupied_inputs(inputs)
                if occupied:
                    return PartyBattleResult("member_busy", challenge, failure_message=f"{occupied}正在进行其他主要行动")
                if inputs.character.resources[HEALTH_CURRENT] <= 0:
                    return PartyBattleResult("health_depleted", challenge, failure_message=f"{inputs.character.name}的血气已经归零")
                if inputs.loadout_fingerprint != challenge.ready_fingerprints[character_id]:
                    return PartyBattleResult("loadout_changed", challenge, failure_message=f"{inputs.character.name}准备后的状态或配装已经变化")
                members.append(inputs)

        context = _context(operation_id, logical_time)
        member_inputs = tuple(members)
        battle = self.battles.simulate(
            [value.character for value in member_inputs],
            [
                (value.inventory, value.loadout, value.roster)
                for value in member_inputs
            ],
            challenge,
            context=context,
        )
        enemy = challenge.encounter.enemies[0]
        enemy_name = self.world_views.require(
            challenge.source_world_id
        ).enemy_projector.enemy(enemy).name
        report_id = self._report_id(challenge)
        report = self.battle_reports.prepare_capture(
            self._battle_report(
                challenge,
                member_inputs,
                battle,
                enemy_name,
                report_id,
                logical_time,
            )
        )
        return _PreparedPartyChallenge(
            party,
            challenge,
            member_inputs,
            battle,
            enemy_name,
            context,
            report,
        )

    def _commit_challenge(
        self,
        operation_id: str,
        party_id: str,
        actor_id: str,
        fingerprint: str,
        logical_time: datetime,
        prepared: _PreparedPartyChallenge,
    ):
        challenge = prepared.challenge
        battle = prepared.battle
        enemy_name = prepared.enemy_name
        context = prepared.context
        with self.database.unit_of_work() as uow:
            replay = self._replay(uow, operation_id, fingerprint, party_id)
            if replay is not None:
                return self._replayed_result(uow, party_id, replay)
            party = self._party(uow, party_id)
            current_challenge = self._load_challenge(uow, party_id)
            if party != prepared.party or current_challenge != challenge:
                return _STALE_CHALLENGE
            current_members = tuple(
                self._load_member_inputs(uow, value.character.id)
                for value in prepared.members
            )
            if current_members != prepared.members:
                return _STALE_CHALLENGE

            reward_summaries: dict[str, tuple[str, ...]] = {}
            if battle.victory:
                enemy = challenge.encounter.enemies[0]
                quote = self.content.catalog.enemy_threat.reward_quote(enemy)
                for member in current_members:
                    character = member.character
                    inventory = member.inventory
                    loadout = member.loadout
                    roster = member.roster
                    daily = self._daily_state(uow, character.id, logical_time)
                    if daily.reward_wins >= PARTY_BATTLE_DAILY_WINS:
                        reward_summaries[character.id] = ("助战完成，本次没有奖励",)
                        continue
                    loot = self.content.catalog.loot_engine.roll(
                        LootRollCommand(
                            f"{operation_id}:loot:{character.id}",
                            character.id,
                            PARTY_BOSS_LOOT_TABLE_ID,
                            0,
                        ),
                        state=LootState(character.id),
                        context=context,
                    )
                    if loot.failure or loot.value is None:
                        raise RuntimeError(loot.failure.message if loot.failure else "组队首领掉落失败")
                    first_clear = enemy.definition_id not in daily.first_clear_ids
                    reward_build = self.reward_factory.build(
                        loot.value.receipt.awards,
                        session_id=f"{challenge.session_id}:attempt:{challenge.attempt_count + 1}",
                        character=character,
                        inventory=inventory,
                        loadout=loadout,
                        enemy_definition_id=str(enemy.definition_id),
                        character_experience=quote.character_experience,
                        weapon_experience=quote.weapon_experience,
                        first_clear=first_clear,
                        context=context,
                    )
                    weapon_revisions = self._weapon_revisions(uow, loadout)
                    claim = self.snapshots.require(
                        uow,
                        self.storage.reward_claim,
                        character.id,
                        RewardClaimState,
                    )
                    settlement = RewardSettlement(
                        f"reward:{operation_id}:{character.id}",
                        character.id,
                        character.id,
                        PARTY_BATTLE_SOURCE_KIND,
                        f"{challenge.session_id}:{challenge.attempt_count + 1}",
                        reward_build.rewards,
                        RewardExpectations(
                            claim.revision,
                            inventory_revision=inventory.revision,
                            character_revisions={character.id: character.revision},
                            weapon_revisions=weapon_revisions,
                        ),
                    )
                    reward_outcome = self.rewards.settle_in_uow(
                        uow,
                        settlement,
                        self.reward_keys_factory(
                            character.id,
                            PRIMARY_LEDGER_ID,
                            (character.id,),
                            tuple(weapon_revisions),
                        ),
                        context=context,
                    )
                    if reward_outcome.failure:
                        raise RuntimeError(reward_outcome.failure.message)
                    active_companion = roster.companion_for_preset(loadout.active_preset_id)
                    companion_amount = (
                        self.companion_growth.engine.party_boss_experience(enemy.level)
                        if active_companion is not None
                        else 0
                    )
                    companion_growth = self.companion_growth.grant_in_uow(
                        uow,
                        character.id,
                        active_companion.id if active_companion is not None else None,
                        companion_amount,
                        character_level=character.progressions[
                            CHARACTER_LEVEL_PROGRESSION_ID
                        ].level,
                        logical_time=logical_time,
                    )
                    companion_experience = (
                        companion_growth.accepted if companion_growth is not None else 0
                    )
                    next_daily = PartyBattleDailyState(
                        character.id,
                        daily.business_day,
                        daily.reward_wins + 1,
                        daily.first_clear_ids | {enemy.definition_id},
                        daily.revision + 1,
                    )
                    self._save_daily(uow, daily, next_daily, logical_time)
                    reward_summaries[character.id] = (
                        f"角色经验 +{quote.character_experience}",
                        f"武器经验 +{quote.weapon_experience}" if loadout.weapon_asset_id else "未装备武器，无武器经验",
                        f"伙伴经验 +{companion_experience}" if active_companion is not None else "未配置伙伴，无伙伴经验",
                        *(
                            f"{value.kind}:{value.definition_id} x{value.quantity}"
                            for value in reward_build.references
                        ),
                    )

            for member in current_members:
                character = member.character
                current = self.snapshots.require(
                    uow,
                    self.storage.character,
                    character.id,
                    CharacterState,
                )
                health, spirit = battle.player_resources[character.id]
                resources = dict(current.resources)
                resources[HEALTH_CURRENT] = health
                resources[SPIRIT_CURRENT] = spirit
                if resources != dict(current.resources):
                    self.snapshots.update(
                        uow,
                        self.storage.character,
                        character.id,
                        current,
                        replace(current, resources=resources, revision=current.revision + 1),
                        logical_time,
                    )

            report = self.battle_reports.capture_prepared_in_uow(
                uow,
                prepared.report,
            )
            next_challenge = replace(
                challenge,
                ready_fingerprints={},
                status="completed" if battle.victory else "selected",
                attempt_count=challenge.attempt_count + 1,
                report_id=report.report_id,
                revision=challenge.revision + 1,
            )
            self.snapshots.update(
                uow,
                PARTY_BATTLE_CHALLENGE_AGGREGATE,
                party_id,
                challenge,
                next_challenge,
                logical_time,
            )
            self._clear_party_ready(uow, party, logical_time)
            status = "victory" if battle.victory else "draw" if battle.draw else "defeated"
            receipt = PartyBattleOperationReceipt(
                operation_id,
                actor_id,
                "challenge",
                status,
                report.report_id,
                report.share_id,
                battle.victory,
                battle.draw,
                battle.turns,
                enemy_name,
                reward_summaries,
            )
            self._record_receipt(uow, receipt, fingerprint, party_id, logical_time)
            uow.commit()
            return PartyBattleResult(
                status,
                next_challenge,
                report.report_id,
                report.share_id,
                battle.victory,
                battle.draw,
                battle.turns,
                enemy_name,
                reward_summaries,
            )

    def _battle_report(
        self,
        challenge,
        members,
        battle,
        enemy_name,
        report_id,
        logical_time,
    ):
        combatants = []
        for inputs in members:
            member = inputs.character
            inventory = inputs.inventory
            loadout = inputs.loadout
            roster = inputs.roster
            combatants.append(
                self.battle_reports.builder.character(
                    member,
                    inputs.character_world,
                    inventory,
                    loadout,
                    team_id="team.party",
                    team_label="行者队伍",
                    inscription_preference=inputs.inscription_preference,
                )
            )
            lineup = battle.lineups[member.id]
            if lineup.companion is not None:
                instance = lineup.companion
                companion = roster.instances[instance.companion_id]
                combatants.append(
                    self.battle_reports.builder.companion(
                        companion,
                        team_id="team.party",
                        team_label="行者队伍",
                    )
                )
        enemy = challenge.encounter.enemies[0]
        combatants.append(
            self.battle_reports.builder.enemy(
                enemy,
                challenge.source_world_id,
                enemy_name,
                team_id="team.enemy",
                team_label="组队首领",
            )
        )
        outcome = "组队胜利" if battle.victory else "战斗平局" if battle.draw else "组队战败"
        return BattleReportDraft(
            report_id=report_id,
            mode_id="battle.mode.party_battle",
            content_fingerprint=self.content.catalog.report.content_fingerprint,
            summary=BattleReportSummary(
                f"组队挑战·{enemy_name}",
                outcome,
                (f"挑战等级: {challenge.level}", f"参战玩家: {len(members)}", f"战斗行动: {battle.turns}"),
                "victory" if battle.victory else "neutral" if battle.draw else "defeat",
            ),
            segment=self.battle_reports.builder.segment(
                segment_id=f"{challenge.session_id}:attempt:{challenge.attempt_count + 1}",
                title=enemy_name,
                trace=battle.trace,
                combatants=combatants,
                outcome=outcome,
                started_at=logical_time,
                finished_at=logical_time,
            ),
        )

    def _load_member_inputs(self, uow, character_id: str) -> _PartyMemberInputs:
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
        roster = self.snapshots.load(
            uow,
            self.storage.companion_roster,
            character_id,
            CompanionRosterState,
        ) or CompanionRosterState(character_id)
        return _PartyMemberInputs(
            character,
            inventory,
            loadout,
            roster,
            self.snapshots.load(
                uow,
                self.storage.action,
                character_id,
                ActionState,
            ),
            self.snapshots.load(
                uow,
                self.storage.exploration,
                character_id,
                ExplorationState,
            ),
            self.snapshots.require(
                uow,
                self.storage.character_world,
                character_id,
                CharacterWorldState,
            ),
            self.snapshots.load(
                uow,
                self.storage.inscription_preference,
                character_id,
                InscriptionPreference,
            ),
            self._loadout_fingerprint(uow, character_id),
        )

    def _loadout_fingerprint(self, uow, character_id: str) -> str:
        character = self.snapshots.require(uow, self.storage.character, character_id, CharacterState)
        inventory = self.snapshots.require(uow, self.storage.inventory, character_id, InventoryState)
        loadout = self.snapshots.require(uow, self.storage.loadout, character_id, LoadoutState)
        roster = self.snapshots.load(
            uow,
            self.storage.companion_roster,
            character_id,
            CompanionRosterState,
        ) or CompanionRosterState(character_id)
        weapon_revisions = self._weapon_revisions(uow, loadout)
        payload = "\0".join(
            (
                character.id,
                str(character.revision),
                repr(sorted(character.resources.items())),
                str(inventory.revision),
                str(loadout.revision),
                repr(sorted((str(key), value) for key, value in loadout.slots.items())),
                str(roster.revision),
                str(roster.bindings.get(loadout.active_preset_id, "")),
                repr(sorted(weapon_revisions.items())),
            )
        )
        return sha256(payload.encode("utf-8")).hexdigest()

    def _weapon_revisions(self, uow, loadout: LoadoutState) -> dict[str, int]:
        if loadout.weapon_asset_id is None:
            return {}
        weapon = self.snapshots.require(
            uow,
            self.storage.weapon,
            loadout.weapon_asset_id,
            WeaponState,
        )
        return {weapon.asset_id: weapon.revision}

    @staticmethod
    def _occupied_inputs(inputs: _PartyMemberInputs) -> str:
        if inputs.action is not None and inputs.action.running(ActionSlotKind.MAIN):
            return "队员"
        if (
            inputs.exploration is not None
            and inputs.exploration.status is ExplorationStatus.RUNNING
        ):
            return "队员"
        return ""

    def _party(self, uow, party_id: str):
        state = self.snapshots.require(
            uow,
            self.storage.party,
            self.party_scope_id,
            PartyState,
        )
        party = state.parties.get(party_id)
        return party if party is not None and party.status is PartyStatus.ACTIVE else None

    def _clear_party_ready(self, uow, party, logical_time: datetime) -> None:
        state = self.snapshots.require(
            uow,
            self.storage.party,
            self.party_scope_id,
            PartyState,
        )
        current = state.parties.get(party.id)
        if current is None or not any(value.ready for value in current.members.values()):
            return
        members = {
            key: replace(value, ready=False) if value.ready else value
            for key, value in current.members.items()
        }
        parties = dict(state.parties)
        parties[current.id] = replace(current, members=members)
        self.snapshots.update(
            uow,
            self.storage.party,
            self.party_scope_id,
            state,
            PartyState(state.scope_id, parties, state.revision + 1),
            logical_time,
        )

    def _set_party_ready(
        self,
        uow,
        party,
        actor_id: str,
        ready: bool,
        logical_time: datetime,
    ) -> None:
        """把队伍准备状态与挑战指纹放在同一个工作单元提交。"""

        state = self.snapshots.require(
            uow,
            self.storage.party,
            self.party_scope_id,
            PartyState,
        )
        current = state.parties.get(party.id)
        if current is None or current.status is not PartyStatus.ACTIVE:
            raise RuntimeError("准备提交时队伍已经失效")
        member = current.members.get(actor_id)
        if member is None:
            raise RuntimeError("准备提交时角色已经离队")
        if member.ready is bool(ready):
            return
        members = dict(current.members)
        members[actor_id] = replace(member, ready=bool(ready))
        parties = dict(state.parties)
        parties[current.id] = replace(current, members=members)
        self.snapshots.update(
            uow,
            self.storage.party,
            self.party_scope_id,
            state,
            PartyState(state.scope_id, parties, state.revision + 1),
            logical_time,
        )

    @staticmethod
    def _leader_failure(party, actor_id: str) -> str:
        if party is None:
            return "当前队伍不存在或已经解散"
        if actor_id not in party.members:
            return "当前角色不在这支队伍中"
        if party.leader_id != actor_id:
            return "只有队长可以选择或发起组队挑战"
        return ""

    def _daily_state(self, uow, character_id: str, logical_time: datetime) -> PartyBattleDailyState:
        business_day = self._business_day(logical_time)
        current = self.snapshots.load(
            uow,
            PARTY_BATTLE_DAILY_AGGREGATE,
            character_id,
            PartyBattleDailyState,
        )
        if current is None:
            return PartyBattleDailyState(character_id, business_day)
        if current.business_day == business_day:
            return current
        return PartyBattleDailyState(character_id, business_day, revision=current.revision)

    def _save_daily(self, uow, previous, current, logical_time):
        stored = self.snapshots.load(
            uow,
            PARTY_BATTLE_DAILY_AGGREGATE,
            current.character_id,
            PartyBattleDailyState,
        )
        if stored is None:
            self.snapshots.insert(
                uow,
                PARTY_BATTLE_DAILY_AGGREGATE,
                current.character_id,
                replace(current, revision=0),
                logical_time,
            )
            return
        self.snapshots.update(
            uow,
            PARTY_BATTLE_DAILY_AGGREGATE,
            current.character_id,
            stored,
            current,
            logical_time,
        )

    def _business_day(self, logical_time: datetime) -> str:
        local = logical_time.astimezone(self.timezone) - timedelta(
            hours=PARTY_BATTLE_DAY_RESET_HOUR
        )
        return local.date().isoformat()

    def _load_challenge(self, uow, party_id: str):
        return self.snapshots.load(
            uow,
            PARTY_BATTLE_CHALLENGE_AGGREGATE,
            party_id,
            PartyBattleChallengeState,
        )

    def _save_challenge(self, uow, previous, current, logical_time):
        if previous is None:
            self.snapshots.insert(
                uow,
                PARTY_BATTLE_CHALLENGE_AGGREGATE,
                current.party_id,
                current,
                logical_time,
            )
        else:
            self.snapshots.update(
                uow,
                PARTY_BATTLE_CHALLENGE_AGGREGATE,
                current.party_id,
                previous,
                current,
                logical_time,
            )

    def _report_id(self, challenge: PartyBattleChallengeState) -> str:
        return f"battle-report:party:{challenge.session_id}:attempt:{challenge.attempt_count + 1}"

    def _replay(self, uow, operation_id, fingerprint, party_id):
        committed = uow.load_transaction(operation_id)
        if committed is None:
            return None
        if committed.fingerprint != fingerprint or committed.scope_id != party_id:
            raise ValueError("同一组队挑战操作 ID 对应了不同请求")
        return self.snapshots.codec.loads(
            committed.receipt_payload,
            PartyBattleOperationReceipt,
        )

    def _record_receipt(self, uow, receipt, fingerprint, party_id, logical_time):
        uow.insert_transaction(
            receipt.operation_id,
            fingerprint,
            party_id,
            self.snapshots.codec.dumps(receipt),
            logical_time.isoformat(),
        )

    def _replayed_result(self, uow, party_id, receipt):
        return PartyBattleResult(
            "replayed",
            self._load_challenge(uow, party_id),
            receipt.report_id,
            receipt.share_id,
            receipt.victory,
            receipt.draw,
            receipt.turns,
            receipt.enemy_name,
            receipt.reward_summaries,
        )


def _context(trace_id: str, logical_time: datetime) -> RuleContext:
    return RuleContext(
        trace_id,
        PARTY_BATTLE_RULE_VERSION,
        Ruleset("ruleset.party_battle"),
        logical_time,
        SeededRandomSource(trace_id),
    )


def _operation_fingerprint(action: str, party_id: str, actor_id: str, detail: str = "") -> str:
    return sha256("\0".join((action, party_id, actor_id, detail)).encode("utf-8")).hexdigest()


def _identity(value: str, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"组队挑战缺少{label}身份")
    return normalized


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("组队挑战逻辑时间必须包含时区")


__all__ = ["PartyBattleFeature", "PartyBattleStorageKinds"]
