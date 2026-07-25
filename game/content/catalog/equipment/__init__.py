"""装备名录的稳定入口；蓝图和属性编译按需从子模块导入。"""

from .definitions import (
    equipment_definition_id,
    equipment_family_id,
    equipment_item_id,
    equipment_set_id,
)
from .properties import (
    EQUIPMENT_GENERATION_PROFILE_ID,
    EQUIPMENT_SET_MARK_CHANCE,
    equipment_property_id,
    equipment_trigger_id,
)


__all__ = [name for name in globals() if not name.startswith("_")]
