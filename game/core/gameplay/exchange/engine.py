"""交换契约生命周期、库存预约和资金冻结的纯规则编排。"""

from __future__ import annotations

from dataclasses import replace

from ..context import RuleContext
from ..economy import (
    CaptureFundHold,
    FundAllocation,
    LedgerEngine,
    LedgerState,
    LedgerTransaction,
    PlaceFundHold,
    ReleaseFundHold,
)
from ..errors import RuleOutcome, RuleViolation
from ..events import RuleEvent
from ..inventory import (
    InventoryEngine,
    InventoryState,
    InventoryTransaction,
    ItemStack,
    MoveAsset,
    ReleaseReservation,
    ReservationMode,
    ReserveAsset,
    SplitStack,
)
from .models import (
    CancelExchange,
    CommitExchange,
    ExchangeCommand,
    ExchangeContract,
    ExchangeExecution,
    ExchangeState,
    ExchangeStatus,
    ExpireExchange,
    OpenExchange,
    SettleExchange,
)


class ExchangeEngine:
    def __init__(self, inventory: InventoryEngine, ledger: LedgerEngine) -> None:
        self.inventory = inventory
        self.ledger = ledger

    def execute(
        self,
        command: ExchangeCommand,
        *,
        exchange: ExchangeState,
        inventory_state: InventoryState,
        ledger_state: LedgerState,
        context: RuleContext,
    ) -> RuleOutcome[ExchangeExecution]:
        checkpoint = context.random.checkpoint()
        try:
            if exchange.revision != command.expected_revision:
                self._fail(
                    "exchange.revision_conflict",
                    "交换状态版本与命令预期不一致",
                    {"expected": command.expected_revision, "actual": exchange.revision},
                )
            contracts = dict(exchange.contracts)
            operation = command.operation
            if isinstance(operation, OpenExchange):
                contract, inventory_state, ledger_state, events = self._open(
                    command, operation, contracts, inventory_state, ledger_state, context
                )
            elif isinstance(operation, CommitExchange):
                contract, inventory_state, ledger_state, events = self._commit(
                    command, operation, contracts, inventory_state, ledger_state, context
                )
            elif isinstance(operation, SettleExchange):
                contract, inventory_state, ledger_state, events = self._settle(
                    command, operation, contracts, inventory_state, ledger_state, context
                )
            elif isinstance(operation, CancelExchange):
                contract, inventory_state, ledger_state, events = self._close(
                    command,
                    operation.contract_id,
                    contracts,
                    inventory_state,
                    ledger_state,
                    context,
                    expired=False,
                )
            elif isinstance(operation, ExpireExchange):
                contract, inventory_state, ledger_state, events = self._close(
                    command,
                    operation.contract_id,
                    contracts,
                    inventory_state,
                    ledger_state,
                    context,
                    expired=True,
                )
            else:
                raise TypeError(f"未知交换操作：{type(operation).__name__}")
            contracts[contract.id] = contract
            next_exchange = ExchangeState(exchange.scope_id, contracts, exchange.revision + 1)
            return RuleOutcome.success(
                ExchangeExecution(
                    command.id,
                    next_exchange,
                    inventory_state,
                    ledger_state,
                    contract,
                    tuple(events),
                )
            )
        except RuleViolation as exc:
            context.random.restore(checkpoint)
            return RuleOutcome.failed(exc.failure)

    def _open(self, command, operation, contracts, inventory, ledger, context):
        contract = operation.contract
        if contract.id in contracts:
            self._fail("exchange.contract_exists", "交换契约已经存在")
        if contract.creator_id != command.actor_id or contract.status is not ExchangeStatus.OPEN:
            self._fail("exchange.creator_mismatch", "只有创建者可以开启初始契约")
        if contract.opened_at != context.logical_time or context.logical_time >= contract.expires_at:
            self._fail("exchange.invalid_window", "交换契约时间窗口无效")
        operations = []
        for offer in contract.asset_offers:
            try:
                asset = inventory.stacks.get(offer.source_asset_id) or inventory.instances[
                    offer.source_asset_id
                ]
            except KeyError:
                self._fail("exchange.asset_unknown", "交换资产不存在", {"asset_id": offer.source_asset_id})
            if inventory.owner_of(asset.id) != contract.creator_id:
                self._fail("exchange.asset_owner_mismatch", "交换资产不属于契约创建者")
            if isinstance(asset, ItemStack):
                if offer.quantity > asset.quantity:
                    self._fail("exchange.asset_quantity", "交换资产数量不足")
                if offer.quantity < asset.quantity:
                    if offer.transfer_asset_id == asset.id:
                        self._fail("exchange.transfer_asset_conflict", "部分物资必须提供新的转移资产 ID")
                    operations.append(SplitStack(asset.id, offer.transfer_asset_id, offer.quantity))
                elif offer.transfer_asset_id != asset.id:
                    self._fail("exchange.transfer_asset_mismatch", "整堆物资转移 ID 必须保持不变")
            elif offer.quantity != 1 or offer.transfer_asset_id != asset.id:
                self._fail("exchange.instance_quantity", "独立实例只能整体交换")
            operations.append(
                ReserveAsset(
                    offer.reservation_id,
                    offer.transfer_asset_id,
                    ReservationMode.ESCROWED,
                    contract.kind_id,
                    contract.id,
                    offer.quantity,
                    None,
                )
            )
        outcome = self.inventory.execute(
            InventoryTransaction(
                f"{command.id}:inventory",
                command.actor_id,
                "inventory.exchange_open",
                tuple(operations),
            ),
            state=inventory,
            context=context,
        )
        if outcome.failure:
            raise RuleViolation(
                outcome.failure.code, outcome.failure.message, outcome.failure.details
            )
        assert outcome.value is not None
        event = self._event(context, command, contract, "exchange.contract.opened", {})
        return contract, outcome.value.state, ledger, (*outcome.value.events, event)

    def _commit(self, command, operation, contracts, inventory, ledger, context):
        contract = self._contract(contracts, operation.contract_id)
        if contract.status is not ExchangeStatus.OPEN:
            self._fail("exchange.not_open", "只有开放契约可以接受")
        if context.logical_time >= contract.expires_at:
            self._fail("exchange.expired", "交换契约已经过期")
        if command.actor_id != operation.buyer_id:
            self._fail("exchange.buyer_mismatch", "行为人与买方身份不一致")
        if contract.allowed_counterparty_id and contract.allowed_counterparty_id != operation.buyer_id:
            self._fail("exchange.counterparty_rejected", "当前主体不是指定交易对手")
        if operation.buyer_id == contract.creator_id:
            self._fail("exchange.self_trade", "不能与自己完成交换")
        if operation.quote_id != contract.quote.id or operation.quote_version != contract.quote.version:
            self._fail("exchange.quote_stale", "交换报价已经变化")
        if set(operation.destinations) != {offer.id for offer in contract.asset_offers}:
            self._fail("exchange.destination_mismatch", "交换目标容器与资产承诺不匹配")
        payer = ledger.accounts.get(operation.payer_account_id)
        if payer is None or payer.currency_id != contract.quote.currency_id:
            self._fail("exchange.payer_invalid", "付款账户不存在或币种不匹配")
        if payer.owner_id != operation.buyer_id:
            self._fail("exchange.payer_owner_mismatch", "付款账户不属于买方")
        for container_id in operation.destinations.values():
            container = inventory.containers.get(container_id)
            if container is None or container.owner_id != operation.buyer_id:
                self._fail("exchange.destination_owner_mismatch", "目标容器不存在或不属于买方")
        hold_id = f"exchange-hold:{contract.id}"
        ledger_outcome = self.ledger.execute(
            LedgerTransaction(
                f"{command.id}:ledger",
                operation.buyer_id,
                "economy.exchange_commit",
                (
                    PlaceFundHold(
                        hold_id,
                        payer.id,
                        contract.quote.total_amount,
                        contract.kind_id,
                        contract.id,
                        None,
                    ),
                ),
                {payer.id: payer.revision},
            ),
            state=ledger,
            context=context,
        )
        if ledger_outcome.failure:
            raise RuleViolation(
                ledger_outcome.failure.code,
                ledger_outcome.failure.message,
                ledger_outcome.failure.details,
            )
        assert ledger_outcome.value is not None
        contract = replace(
            contract,
            status=ExchangeStatus.COMMITTED,
            buyer_id=operation.buyer_id,
            payer_account_id=payer.id,
            fund_hold_id=hold_id,
            destinations=operation.destinations,
            revision=contract.revision + 1,
        )
        event = self._event(context, command, contract, "exchange.contract.committed", {
            "buyer_id": operation.buyer_id,
            "quote_id": contract.quote.id,
            "quote_version": contract.quote.version,
        })
        return contract, inventory, ledger_outcome.value.state, (*ledger_outcome.value.events, event)

    def _settle(self, command, operation, contracts, inventory, ledger, context):
        contract = self._contract(contracts, operation.contract_id)
        if contract.status is not ExchangeStatus.COMMITTED:
            self._fail("exchange.not_committed", "只有已承诺契约可以成交")
        if command.actor_id not in {contract.creator_id, contract.buyer_id}:
            self._fail("exchange.party_required", "只有契约参与方可以请求成交")
        inventory_operations = tuple(
            MoveAsset(
                offer.transfer_asset_id,
                contract.destinations[offer.id],
                offer.reservation_id,
            )
            for offer in contract.asset_offers
        )
        inventory_outcome = self.inventory.execute(
            InventoryTransaction(
                f"{command.id}:inventory",
                command.actor_id,
                "inventory.exchange_settle",
                inventory_operations,
            ),
            state=inventory,
            context=context,
        )
        if inventory_outcome.failure:
            raise RuleViolation(
                inventory_outcome.failure.code,
                inventory_outcome.failure.message,
                inventory_outcome.failure.details,
            )
        payer = ledger.accounts[contract.payer_account_id]
        involved_account_ids = {
            payer.id,
            *(line.destination_account_id for line in contract.quote.allocations),
        }
        ledger_outcome = self.ledger.execute(
            LedgerTransaction(
                f"{command.id}:ledger",
                command.actor_id,
                "economy.exchange_settle",
                (
                    CaptureFundHold(
                        contract.fund_hold_id,
                        tuple(
                            FundAllocation(line.destination_account_id, line.amount)
                            for line in contract.quote.allocations
                        ),
                    ),
                ),
                {
                    account_id: ledger.accounts[account_id].revision
                    for account_id in involved_account_ids
                },
            ),
            state=ledger,
            context=context,
        )
        if ledger_outcome.failure:
            raise RuleViolation(
                ledger_outcome.failure.code,
                ledger_outcome.failure.message,
                ledger_outcome.failure.details,
            )
        assert inventory_outcome.value is not None and ledger_outcome.value is not None
        contract = replace(contract, status=ExchangeStatus.SETTLED, revision=contract.revision + 1)
        event = self._event(context, command, contract, "exchange.contract.settled", {
            "buyer_id": contract.buyer_id,
            "total_amount": contract.quote.total_amount,
        })
        return (
            contract,
            inventory_outcome.value.state,
            ledger_outcome.value.state,
            (*inventory_outcome.value.events, *ledger_outcome.value.events, event),
        )

    def _close(self, command, contract_id, contracts, inventory, ledger, context, *, expired):
        contract = self._contract(contracts, contract_id)
        if contract.status not in {ExchangeStatus.OPEN, ExchangeStatus.COMMITTED}:
            self._fail("exchange.not_closable", "交换契约已经终结")
        if expired:
            if context.logical_time < contract.expires_at:
                self._fail("exchange.not_expired", "交换契约尚未到期")
        elif command.actor_id not in {contract.creator_id, contract.buyer_id}:
            self._fail("exchange.party_required", "只有契约参与方可以取消")
        inventory_outcome = self.inventory.execute(
            InventoryTransaction(
                f"{command.id}:inventory",
                command.actor_id,
                "inventory.exchange_close",
                tuple(
                    ReleaseReservation(offer.reservation_id)
                    for offer in contract.asset_offers
                ),
            ),
            state=inventory,
            context=context,
        )
        if inventory_outcome.failure:
            raise RuleViolation(
                inventory_outcome.failure.code,
                inventory_outcome.failure.message,
                inventory_outcome.failure.details,
            )
        assert inventory_outcome.value is not None
        events = list(inventory_outcome.value.events)
        if contract.status is ExchangeStatus.COMMITTED:
            payer = ledger.accounts[contract.payer_account_id]
            ledger_outcome = self.ledger.execute(
                LedgerTransaction(
                    f"{command.id}:ledger",
                    command.actor_id,
                    "economy.exchange_close",
                    (ReleaseFundHold(contract.fund_hold_id),),
                    {payer.id: payer.revision},
                ),
                state=ledger,
                context=context,
            )
            if ledger_outcome.failure:
                raise RuleViolation(
                    ledger_outcome.failure.code,
                    ledger_outcome.failure.message,
                    ledger_outcome.failure.details,
                )
            assert ledger_outcome.value is not None
            ledger = ledger_outcome.value.state
            events.extend(ledger_outcome.value.events)
        status = ExchangeStatus.EXPIRED if expired else ExchangeStatus.CANCELLED
        contract = replace(
            contract,
            status=status,
            buyer_id=None,
            payer_account_id=None,
            fund_hold_id=None,
            destinations={},
            revision=contract.revision + 1,
        )
        events.append(self._event(context, command, contract, f"exchange.contract.{status.value}", {}))
        return contract, inventory_outcome.value.state, ledger, tuple(events)

    @staticmethod
    def _contract(contracts, contract_id: str) -> ExchangeContract:
        contract = contracts.get(contract_id)
        if contract is None:
            ExchangeEngine._fail("exchange.contract_unknown", "找不到交换契约")
        return contract

    @staticmethod
    def _event(context, command, contract, kind, values) -> RuleEvent:
        return RuleEvent.from_context(
            context,
            kind=kind,
            source_id=command.actor_id,
            target_id=contract.id,
            subject_id=contract.kind_id,
            values={"command_id": command.id, "contract_id": contract.id, **values},
        )

    @staticmethod
    def _fail(code: str, message: str, details: dict[str, object] | None = None) -> None:
        raise RuleViolation(code, message, details or {})


__all__ = ["ExchangeEngine"]
