"""玩家身份、角色读模型、个人设置和提醒的应用服务。"""

from dataclasses import replace

from game.core.gameplay import (
    CharacterState,
    InscriptionPreference,
    InventoryState,
    LedgerState,
    LoadoutState,
    NotificationStatus,
    WorldState,
)
from game.rules.activity import GLOBAL_ACTIVITY_SCOPE_ID
from game.rules.character import (
    CharacterCreationReceipt,
    CharacterCreationRequest,
    CharacterWorldState,
    CharacterIdentityViolation,
    CharacterSettingsState,
    PRIMARY_LEDGER_ID,
    MULTIVERSE_WORLD_STATE_ID,
    character_creation_context,
)
from .models import (
    CharacterCreationCommandResult,
    CharacterOverview,
    CharacterOverviewResult,
    CurrentCharacterResult,
    GlobalActivityViewsResult,
    NotificationMarkResult,
    PlayerReminderDetails,
    PlayerReminderDetailsResult,
    PlayerReplyState,
    PlayerReplyStateResult,
    PlayerOwnershipError,
    PlayerStorageKinds,
)


class PlayerFeature:
    """只协调玩家入口与个人读模型，不承载具体玩法规则。"""

    def __init__(
        self,
        database,
        accounts,
        characters,
        character_creation,
        snapshots,
        notifications,
        activities,
        global_activities,
        player_activity,
        storage: PlayerStorageKinds,
    ) -> None:
        self.database = database
        self.accounts = accounts
        self.characters = characters
        self.character_creation = character_creation
        self.snapshots = snapshots
        self.notifications = notifications
        self.activities = activities
        self.global_activities = global_activities
        self.player_activity = player_activity
        self.storage = storage

    def create_character(
        self,
        evidence,
        *,
        requested_name: str = "",
        platform_name: str = "",
    ) -> CharacterCreationCommandResult:
        resolution = self.accounts.resolve_identity(evidence)
        if resolution.account is None:
            return CharacterCreationCommandResult("identity_conflict")
        account_id = resolution.account.id
        request = CharacterCreationRequest(
            f"character:create:{evidence.id}",
            account_id,
            requested_name=requested_name,
            platform_name=platform_name,
        )
        try:
            receipt = self.character_creation.create(
                request,
                context=character_creation_context(
                    trace_id=request.transaction_id,
                    logical_time=evidence.logical_time,
                ),
            )
        except CharacterIdentityViolation as exc:
            status = {
                "character.name_required": "name_required",
                "character.name_invalid": "name_invalid",
                "character.account_already_has_character": "existing",
            }.get(exc.code, "rejected")
            return CharacterCreationCommandResult(
                status,
                existing_character=self.characters.load_for_account(account_id),
            )
        if not isinstance(receipt, CharacterCreationReceipt):
            raise TypeError("角色创世服务返回了错误回执类型")
        return CharacterCreationCommandResult("created", receipt=receipt)

    def load_current_character(self, evidence) -> CurrentCharacterResult:
        resolution = self.accounts.resolve_identity(evidence)
        if resolution.account is None:
            return CurrentCharacterResult("identity_conflict")
        character = self.characters.load_for_account(resolution.account.id)
        if character is None:
            return CurrentCharacterResult("not_created")
        with self.database.unit_of_work(write=False) as uow:
            dimension = self.snapshots.require(
                uow,
                self.storage.character_world,
                character.id,
                CharacterWorldState,
            )
        return CurrentCharacterResult("ok", character, dimension)

    def load_character_overview(
        self,
        character: CharacterState,
    ) -> CharacterOverviewResult:
        with self.database.unit_of_work(write=False) as uow:
            stored_character = self.snapshots.require(
                uow,
                self.storage.character,
                character.id,
                CharacterState,
            )
            if stored_character.account_id != character.account_id:
                raise PlayerOwnershipError("角色详情账号归属不一致")
            activity = self.player_activity.load_in_uow(uow, character.id)
            overview = CharacterOverview(
                character=stored_character,
                inventory=self.snapshots.require(
                    uow, self.storage.inventory, character.id, InventoryState
                ),
                loadout=self.snapshots.require(
                    uow, self.storage.loadout, character.id, LoadoutState
                ),
                ledger=self.snapshots.require(
                    uow, self.storage.ledger, PRIMARY_LEDGER_ID, LedgerState
                ),
                world=self.snapshots.require(
                    uow, self.storage.world, MULTIVERSE_WORLD_STATE_ID, WorldState
                ),
                character_world=self.snapshots.require(
                    uow,
                    self.storage.character_world,
                    character.id,
                    CharacterWorldState,
                ),
                settings=self.snapshots.require(
                    uow,
                    self.storage.settings,
                    character.id,
                    CharacterSettingsState,
                ),
                inscription_preference=self.snapshots.load(
                    uow,
                    self.storage.inscription_preference,
                    character.id,
                    InscriptionPreference,
                ),
                activity=activity,
            )
        return CharacterOverviewResult("ok", overview)

    def load_settings(self, character_id: str) -> CharacterSettingsState:
        with self.database.unit_of_work(write=False) as uow:
            return self.snapshots.require(
                uow,
                self.storage.settings,
                str(character_id or "").strip(),
                CharacterSettingsState,
            )

    def load_reply_state(self, evidence) -> PlayerReplyStateResult:
        current = self.load_current_character(evidence)
        if current.status != "ok" or current.character is None:
            return PlayerReplyStateResult(current.status)
        character = current.character
        with self.database.unit_of_work(write=False) as uow:
            settings = self.snapshots.require(
                uow,
                self.storage.settings,
                character.id,
                CharacterSettingsState,
            )
            dimension = self.snapshots.require(
                uow,
                self.storage.character_world,
                character.id,
                CharacterWorldState,
            )
            player_activity = self.player_activity.load_in_uow(uow, character.id)
        selection = self.global_activities.spotlight(
            self.activities.load(GLOBAL_ACTIVITY_SCOPE_ID),
            logical_time=evidence.logical_time,
            limit=2,
        )
        return PlayerReplyStateResult(
            "ok",
            PlayerReplyState(
                character,
                settings,
                dimension,
                player_activity,
                activity_spotlights=selection.activities,
                additional_activity_count=selection.additional_count,
                unread_notification_count=self.notifications.count_unread(
                    character.account_id,
                    logical_time=evidence.logical_time,
                ),
                pending_action_count=len(player_activity.pending_actions),
            ),
        )

    def set_setting(
        self,
        character_id: str,
        field_name: str,
        enabled: bool,
        *,
        logical_time,
    ) -> CharacterSettingsState:
        if not isinstance(enabled, bool):
            raise TypeError("角色设置值必须是 bool")
        normalized_id = str(character_id or "").strip()
        with self.database.unit_of_work() as uow:
            current = self.snapshots.require(
                uow,
                self.storage.settings,
                normalized_id,
                CharacterSettingsState,
            )
            if getattr(current, field_name) is enabled:
                return current
            updated = replace(
                current,
                **{field_name: enabled, "revision": current.revision + 1},
            )
            self.snapshots.update(
                uow,
                self.storage.settings,
                normalized_id,
                current,
                updated,
                logical_time,
            )
            uow.commit()
            return updated

    def mark_notification_read(
        self,
        character: CharacterState,
        notification_id: str,
        expected_revision: int,
        *,
        logical_time,
    ) -> NotificationMarkResult:
        key = str(notification_id or "").strip()
        if not key:
            return NotificationMarkResult("not_found")
        unread = self.notifications.list_unread(
            character.account_id,
            logical_time=logical_time,
            limit=100,
        )
        entry = next((value for value in unread if value.id == key), None)
        if entry is None:
            return NotificationMarkResult("not_found")
        if entry.revision != expected_revision:
            return NotificationMarkResult("stale", entry)
        return NotificationMarkResult(
            "read",
            self.notifications.mark(
                entry.id,
                NotificationStatus.READ,
                expected_revision=expected_revision,
                logical_time=logical_time,
            ),
        )

    def load_reminder_details(
        self,
        character: CharacterState,
        *,
        logical_time,
        notification_limit: int = 20,
    ) -> PlayerReminderDetailsResult:
        with self.database.unit_of_work(write=False) as uow:
            player_activity = self.player_activity.load_in_uow(uow, character.id)
        return PlayerReminderDetailsResult(
            "ok",
            PlayerReminderDetails(
                self.notifications.list_unread(
                    character.account_id,
                    logical_time=logical_time,
                    limit=notification_limit,
                ),
                player_activity.pending_actions,
            ),
        )

    def load_global_activity_views(self, *, logical_time) -> GlobalActivityViewsResult:
        return GlobalActivityViewsResult(
            "ok",
            self.global_activities.active(
                self.activities.load(GLOBAL_ACTIVITY_SCOPE_ID),
                logical_time=logical_time,
            ),
        )


__all__ = ["PlayerFeature"]
