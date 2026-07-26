"""只保存角色个人选择，不重复保存全服恢复参数。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CharacterSettingsState:
    """只保存玩家选择；所有人相同的阈值不重复写入存档。"""

    character_id: str
    auto_use_medicine: bool = True
    auto_rest: bool = True
    mood_header_enabled: bool = False
    revision: int = 0

    def __post_init__(self) -> None:
        if not self.character_id.strip():
            raise ValueError("CharacterSettingsState 缺少 character_id")
        if not isinstance(self.auto_use_medicine, bool):
            raise TypeError("auto_use_medicine 必须是布尔值")
        if not isinstance(self.auto_rest, bool):
            raise TypeError("auto_rest 必须是布尔值")
        if not isinstance(self.mood_header_enabled, bool):
            raise TypeError("mood_header_enabled 必须是布尔值")
        if self.revision < 0:
            raise ValueError("CharacterSettingsState.revision 不能小于 0")


__all__ = [
    "CharacterSettingsState",
]
