"""
QMT broker adapter placeholder

Phase 7A 只提供接口壳，真实联调留到后续阶段。
"""
from __future__ import annotations

from trading.broker.base import BaseBroker, BrokerAccount, BrokerOrder, BrokerOrderRequest, BrokerPosition


class QmtBroker(BaseBroker):
    @property
    def name(self) -> str:
        return "qmt"

    def get_account(self) -> BrokerAccount:
        raise NotImplementedError("Phase 7A 暂未接入真实 QMT 账户查询")

    def get_positions(self) -> list[BrokerPosition]:
        raise NotImplementedError("Phase 7A 暂未接入真实 QMT 持仓查询")

    def submit_order(self, request: BrokerOrderRequest) -> BrokerOrder:
        raise NotImplementedError("Phase 7A 暂未接入真实 QMT 下单")

    def cancel_order(self, order_id: str) -> BrokerOrder | None:
        raise NotImplementedError("Phase 7A 暂未接入真实 QMT 撤单")

    def list_orders(self, status: str | None = None) -> list[BrokerOrder]:
        raise NotImplementedError("Phase 7A 暂未接入真实 QMT 订单查询")
