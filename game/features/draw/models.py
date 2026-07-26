"""抽奖玩法对命令层公开的稳定结果与持久状态。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Mapping

from game.core.gameplay import DrawReceipt


DRAW_HISTORY_LIMIT = 50


@dataclass(frozen=True)
class DrawHistoryRecord:
    operation_id: str
    receipt: DrawReceipt
    created_at: datetime
    tickets_spent: int | None = None
    currency_spent: int | None = None

    def __post_init__(self) -> None:
        if not self.operation_id.strip():
            raise ValueError("抽奖记录缺少操作身份")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("抽奖记录时间必须包含时区")
        if (self.tickets_spent is None) != (self.currency_spent is None):
            raise ValueError("抽奖记录支付信息不完整")
        if self.tickets_spent is None:
            return
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in (self.tickets_spent, self.currency_spent)
        ):
            raise ValueError("抽奖记录支付数量必须是非负整数")
        if self.tickets_spent > self.receipt.rolls:
            raise ValueError("抽奖记录消耗的抽奖签超过抽取次数")


@dataclass(frozen=True)
class DrawHistoryState:
    owner_id: str
    records: tuple[DrawHistoryRecord, ...] = ()
    revision: int = 0

    def __post_init__(self) -> None:
        records = tuple(self.records)
        if not self.owner_id.strip() or self.revision < 0:
            raise ValueError("抽奖历史所有者或 revision 无效")
        ids = tuple(value.operation_id for value in records)
        if len(ids) != len(set(ids)):
            raise ValueError("抽奖历史包含重复操作")
        if len(records) > DRAW_HISTORY_LIMIT:
            raise ValueError("抽奖历史超过保留上限")
        object.__setattr__(self, "records", records)

    def find(self, operation_id: str) -> DrawHistoryRecord | None:
        return next(
            (value for value in self.records if value.operation_id == operation_id),
            None,
        )


@dataclass(frozen=True)
class DrawOperationResult:
    status: str
    record: DrawHistoryRecord | None = None
    ticket_count: int = 0
    pity_count: int = 0
    failure_message: str = ""
    guarantee_counts: Mapping[str, int] = field(default_factory=dict)
    currency_available: int = 0
    currency_required: int = 0

    def __post_init__(self) -> None:
        counts = {str(key): int(value) for key, value in self.guarantee_counts.items()}
        if any(value < 0 for value in counts.values()):
            raise ValueError("抽奖保底计数不能小于 0")
        if self.ticket_count < 0 or self.currency_available < 0 or self.currency_required < 0:
            raise ValueError("抽奖资源数量不能小于 0")
        object.__setattr__(self, "guarantee_counts", MappingProxyType(counts))


@dataclass(frozen=True)
class DrawPoolView:
    ticket_count: int
    pity_count: int
    records: tuple[DrawHistoryRecord, ...] = ()
    guarantee_counts: Mapping[str, int] = field(default_factory=dict)
    currency_balance: int = 0

    def __post_init__(self) -> None:
        counts = {str(key): int(value) for key, value in self.guarantee_counts.items()}
        if any(value < 0 for value in counts.values()):
            raise ValueError("抽奖保底计数不能小于 0")
        if self.ticket_count < 0 or self.currency_balance < 0:
            raise ValueError("抽奖资源数量不能小于 0")
        object.__setattr__(self, "records", tuple(self.records))
        object.__setattr__(self, "guarantee_counts", MappingProxyType(counts))


@dataclass(frozen=True)
class DrawStorageKinds:
    history: str
    inventory: str
    ledger: str
    loot: str
    reward_claim: str


__all__ = [
    "DRAW_HISTORY_LIMIT",
    "DrawHistoryRecord",
    "DrawHistoryState",
    "DrawOperationResult",
    "DrawPoolView",
    "DrawStorageKinds",
]
