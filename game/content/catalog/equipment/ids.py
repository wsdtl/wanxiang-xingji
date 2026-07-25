"""装备机制使用的稳定 ID。"""


def equipment_trigger_id(key: str, tier: int) -> str:
    return f"trigger.equipment.{key}.tier_{tier}"


__all__ = ["equipment_trigger_id"]
