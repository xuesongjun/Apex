"""
Dry-run broker

不接真实券商，只负责把统一订单请求落库并返回标准订单结果。
"""
from __future__ import annotations

import json
import uuid

from data.storage.repository import LiveRepository
from trading.broker.base import (
    BaseBroker,
    BrokerAccount,
    BrokerOrder,
    BrokerOrderRequest,
    BrokerPosition,
)


class DryRunBroker(BaseBroker):
    def __init__(
        self,
        instance_id: str,
        strategy_key: str,
        stock_codes: list[str],
        initial_capital: float,
        broker_account_id: str = "",
    ):
        self.instance_id = instance_id
        self.strategy_key = strategy_key
        self.stock_codes = stock_codes
        self.initial_capital = initial_capital
        self.broker_account_id = broker_account_id or "DRYRUN"
        self._repo = LiveRepository()
        self._ensure_account()

    @property
    def name(self) -> str:
        return "dry_run"

    def _ensure_account(self) -> None:
        account = self._repo.get_live_account(self.instance_id)
        if account is None:
            self._repo.create_live_account(
                instance_id=self.instance_id,
                strategy_key=self.strategy_key,
                broker_provider=self.name,
                broker_account_id=self.broker_account_id,
                initial_capital=self.initial_capital,
                stock_codes=self.stock_codes,
                cash=self.initial_capital,
                total_equity=self.initial_capital,
            )

    def get_account(self) -> BrokerAccount:
        self._ensure_account()
        row = self._repo.get_live_account(self.instance_id)
        return BrokerAccount(
            broker_provider=self.name,
            broker_account_id=row.broker_account_id or self.broker_account_id,
            cash=row.cash or 0.0,
            total_equity=row.total_equity or 0.0,
            status=row.status or "active",
        )

    def get_positions(self) -> list[BrokerPosition]:
        rows = self._repo.get_live_positions(self.instance_id)
        return [
            BrokerPosition(
                code=row.code,
                volume=row.volume or 0,
                available=row.available or 0,
                cost_price=row.cost_price or 0.0,
                current_price=row.current_price or 0.0,
            )
            for row in rows
        ]

    def submit_order(self, request: BrokerOrderRequest) -> BrokerOrder:
        existing = self._repo.get_live_order(request.order_id)
        broker_order_id = f"DRY-{uuid.uuid4().hex[:12].upper()}"
        status = "planned" if request.execute_at == "next_open" else "submitted"

        if existing is None:
            self._repo.save_live_order({
                "order_id": request.order_id,
                "instance_id": request.instance_id,
                "strategy_key": request.strategy_key,
                "broker_provider": self.name,
                "broker_order_id": broker_order_id,
                "code": request.code,
                "direction": request.direction.value,
                "signal_date": request.signal_date,
                "planned_execute_date": request.planned_execute_date,
                "execute_at": request.execute_at,
                "req_price": request.price,
                "req_volume": request.volume,
                "status": status,
                "reason": request.reason,
            })
        else:
            self._repo.update_live_order(
                order_id=request.order_id,
                status=status,
                broker_order_id=existing.broker_order_id or broker_order_id,
                filled_price=existing.filled_price or 0.0,
                filled_volume=existing.filled_volume or 0,
                commission=existing.commission or 0.0,
                reason=request.reason or existing.reason or "",
            )
            broker_order_id = existing.broker_order_id or broker_order_id

        return BrokerOrder(
            order_id=request.order_id,
            broker_provider=self.name,
            broker_order_id=broker_order_id,
            code=request.code,
            direction=request.direction.value,
            signal_date=request.signal_date,
            execute_at=request.execute_at,
            planned_execute_date=request.planned_execute_date,
            req_price=request.price,
            req_volume=request.volume,
            status=status,
            reason=request.reason,
        )

    def cancel_order(self, order_id: str) -> BrokerOrder | None:
        rows = self._repo.get_live_orders(self.instance_id)
        target = next((row for row in rows if row.order_id == order_id), None)
        if target is None:
            return None

        self._repo.update_live_order(
            order_id=order_id,
            status="cancelled",
            broker_order_id=target.broker_order_id or "",
            reason=target.reason or "",
        )
        return BrokerOrder(
            order_id=target.order_id,
            broker_provider=target.broker_provider,
            broker_order_id=target.broker_order_id or "",
            code=target.code,
            direction=target.direction,
            signal_date=target.signal_date,
            execute_at=target.execute_at,
            planned_execute_date=target.planned_execute_date,
            req_price=target.req_price or 0.0,
            req_volume=target.req_volume or 0,
            status="cancelled",
            filled_price=target.filled_price or 0.0,
            filled_volume=target.filled_volume or 0,
            commission=target.commission or 0.0,
            reason=target.reason or "",
        )

    def list_orders(self, status: str | None = None) -> list[BrokerOrder]:
        rows = self._repo.get_live_orders(self.instance_id, status=status)
        return [
            BrokerOrder(
                order_id=row.order_id,
                broker_provider=row.broker_provider,
                broker_order_id=row.broker_order_id or "",
                code=row.code,
                direction=row.direction,
                signal_date=row.signal_date,
                execute_at=row.execute_at,
                planned_execute_date=row.planned_execute_date,
                req_price=row.req_price or 0.0,
                req_volume=row.req_volume or 0,
                status=row.status,
                filled_price=row.filled_price or 0.0,
                filled_volume=row.filled_volume or 0,
                commission=row.commission or 0.0,
                reason=row.reason or "",
            )
            for row in rows
        ]
