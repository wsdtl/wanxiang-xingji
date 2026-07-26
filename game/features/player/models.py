"""玩家入口、总览、设置与提醒使用的稳定应用模型。"""

from dataclasses import dataclass, field

from game.core.gameplay import (
    ActionRecord,
    CharacterState,
    InscriptionPreference,
    InventoryState,
    LedgerState,
    LoadoutState,
    NotificationEntry,
    WorldState,
)
from game.rules.activity import GlobalActivityView
from game.rules.character import (
    CharacterCreationReceipt,
    CharacterWorldState,
    CharacterSettingsState,
)
from game.rules.player_activity import (
    PlayerActivityKind,
    PlayerActivityProjection,
)


class PlayerOwnershipError(RuntimeError):
    """跨领域角色读模型发现账号归属不一致。"""


@dataclass(frozen=True)
class PlayerStorageKinds:
    character: str
    inventory: str
    loadout: str
    ledger: str
    world: str
    character_world: str
    settings: str
    inscription_preference: str


@dataclass(frozen=True)
class CharacterCreationCommandResult:
    status: str
    receipt: CharacterCreationReceipt | None = None
    existing_character: CharacterState | None = None


@dataclass(frozen=True)
class CharacterOverview:
    character: CharacterState
    inventory: InventoryState
    loadout: LoadoutState
    ledger: LedgerState
    world: WorldState
    character_world: CharacterWorldState
    settings: CharacterSettingsState
    inscription_preference: InscriptionPreference | None = None
    activity: PlayerActivityProjection = field(
        default_factory=lambda: PlayerActivityProjection(PlayerActivityKind.IDLE)
    )


@dataclass(frozen=True)
class CharacterOverviewResult:
    status: str
    overview: CharacterOverview | None = None


@dataclass(frozen=True)
class CurrentCharacterResult:
    status: str
    character: CharacterState | None = None
    character_world: CharacterWorldState | None = None


@dataclass(frozen=True)
class PlayerReplyState:
    character: CharacterState
    settings: CharacterSettingsState
    character_world: CharacterWorldState
    activity: PlayerActivityProjection = field(
        default_factory=lambda: PlayerActivityProjection(PlayerActivityKind.IDLE)
    )
    activity_spotlights: tuple[GlobalActivityView, ...] = ()
    additional_activity_count: int = 0
    unread_notification_count: int = 0
    pending_action_count: int = 0

    def __post_init__(self) -> None:
        if min(
            self.additional_activity_count,
            self.unread_notification_count,
            self.pending_action_count,
        ) < 0:
            raise ValueError("玩家回复摘要数量不能小于 0")


@dataclass(frozen=True)
class PlayerReplyStateResult:
    status: str
    state: PlayerReplyState | None = None


@dataclass(frozen=True)
class PlayerReminderDetails:
    notifications: tuple[NotificationEntry, ...] = ()
    pending_actions: tuple[ActionRecord, ...] = ()


@dataclass(frozen=True)
class PlayerReminderDetailsResult:
    status: str
    details: PlayerReminderDetails | None = None


@dataclass(frozen=True)
class GlobalActivityViewsResult:
    status: str
    activities: tuple[GlobalActivityView, ...] = ()


@dataclass(frozen=True)
class NotificationMarkResult:
    status: str
    notification: NotificationEntry | None = None


__all__ = [name for name in globals() if not name.startswith("_")]
