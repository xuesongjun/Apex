"""
QMT broker adapter

Phase 7B：
- 连接 xtquant / QMT 客户端
- 查询账户、持仓、订单
- 提交 / 撤销即时订单
- `next_open` 计划单仍先落库，等待到期后由 live_engine 激活
"""
from __future__ import annotations

import importlib
import uuid
from datetime import date, datetime
from typing import Optional

from data.storage.repository import LiveRepository
from trading.broker.base import (
    BaseBroker,
    BrokerAccount,
    BrokerOrder,
    BrokerOrderRequest,
    BrokerPosition,
)


class QmtBroker(BaseBroker):
    def __init__(
        self,
        instance_id: str,
        strategy_key: str,
        stock_codes: list[str],
        initial_capital: float,
        provider_name: str,
        account_id: str,
        userdata_path: str,
        session_id: int,
        account_type: str = "STOCK",
        dynamic_price_type: str = "LATEST_PRICE",
        strategy_name: str = "Apex",
        order_remark_prefix: str = "Apex",
    ):
        if not account_id:
            raise ValueError("QMT 实盘模式必须提供 broker.account_id")
        if not userdata_path:
            raise ValueError("QMT 实盘模式必须提供 broker.qmt.userdata_path")

        self.instance_id = instance_id
        self.strategy_key = strategy_key
        self.stock_codes = stock_codes
        self.initial_capital = initial_capital
        self.provider_name = provider_name
        self.account_id = account_id
        self.userdata_path = userdata_path
        self.session_id = session_id
        self.account_type = account_type
        self.dynamic_price_type = dynamic_price_type
        self.strategy_name = strategy_name
        self.order_remark_prefix = order_remark_prefix

        self._repo = LiveRepository()
        self._xtconstant = None
        self._trader = None
        self._stock_account = None

    @property
    def name(self) -> str:
        return self.provider_name

    def _load_xtquant(self):
        try:
            xttrader = importlib.import_module("xtquant.xttrader")
            xttype = importlib.import_module("xtquant.xttype")
            xtconstant = importlib.import_module("xtquant.xtconstant")
        except Exception as e:
            raise RuntimeError(
                "未检测到 xtquant / QMT Python SDK，请先在真实交易环境中安装并配置。"
            ) from e
        return xttrader, xttype, xtconstant

    def _ensure_ready(self) -> None:
        if self._trader is not None:
            return

        xttrader, xttype, xtconstant = self._load_xtquant()
        self._xtconstant = xtconstant

        trader_cls = getattr(xttrader, "XtQuantTrader")
        callback_cls = getattr(xttrader, "XtQuantTraderCallback", object)
        stock_account_cls = getattr(xttype, "StockAccount")

        class _Callback(callback_cls):
            pass

        self._trader = trader_cls(self.userdata_path, self.session_id)
        if hasattr(self._trader, "register_callback"):
            self._trader.register_callback(_Callback())
        if hasattr(self._trader, "start"):
            self._trader.start()

        connect_result = self._trader.connect()
        if connect_result != 0:
            raise RuntimeError(f"QMT connect 失败，返回码={connect_result}")

        self._stock_account = stock_account_cls(self.account_id, self.account_type)
        subscribe_result = self._trader.subscribe(self._stock_account)
        if subscribe_result != 0:
            raise RuntimeError(f"QMT subscribe 失败，返回码={subscribe_result}")

    def _normalize_code(self, code: str) -> str:
        if "." in code:
            return code
        if code.startswith(("6", "5")):
            return f"{code}.SH"
        if code.startswith(("8", "4")):
            return f"{code}.BJ"
        return f"{code}.SZ"

    def _denormalize_code(self, code: str) -> str:
        return code.split(".", 1)[0]

    def _const(self, name: str, fallback):
        if self._xtconstant is None:
            return fallback
        return getattr(self._xtconstant, name, fallback)

    def _order_type(self, direction: str):
        if direction == "BUY":
            return self._const("STOCK_BUY", 23)
        return self._const("STOCK_SELL", 24)

    def _price_type(self, req_price: float):
        if req_price and req_price > 0:
            return self._const("FIX_PRICE", 11)
        return self._const(self.dynamic_price_type, self._const("LATEST_PRICE", 5))

    def _map_status(self, raw_status, filled_volume: int = 0, req_volume: int = 0) -> str:
        if filled_volume > 0 and req_volume > 0 and filled_volume >= req_volume:
            return "filled"

        cancelled = {
            self._const("ORDER_CANCELED", -10),
            self._const("ORDER_PART_CANCEL", -11),
        }
        rejected = {
            self._const("ORDER_REJECTED", -20),
            self._const("ORDER_JUNK", -21),
        }
        accepted = {
            self._const("ORDER_REPORTED", 50),
            self._const("ORDER_REPORTED_CANCEL", 51),
            self._const("ORDER_PART_SUCC", 55),
            self._const("ORDER_SUCCEEDED", 56),
        }

        if raw_status in cancelled:
            return "cancelled"
        if raw_status in rejected:
            return "rejected"
        if raw_status in accepted:
            return "accepted"
        return "submitted"

    def get_account(self) -> BrokerAccount:
        self._ensure_ready()
        asset = self._trader.query_stock_asset(self._stock_account)
        if asset is None:
            raise RuntimeError("QMT 查询账户失败：返回空对象")

        cash = float(getattr(asset, "cash", 0.0) or 0.0)
        total_equity = float(
            getattr(asset, "total_asset", getattr(asset, "total_equity", cash)) or cash
        )
        return BrokerAccount(
            broker_provider=self.name,
            broker_account_id=self.account_id,
            cash=cash,
            total_equity=total_equity,
            status="ready",
        )

    def get_positions(self) -> list[BrokerPosition]:
        self._ensure_ready()
        rows = self._trader.query_stock_positions(self._stock_account) or []
        positions: list[BrokerPosition] = []
        for row in rows:
            positions.append(
                BrokerPosition(
                    code=self._denormalize_code(str(getattr(row, "stock_code", ""))),
                    volume=int(getattr(row, "volume", 0) or 0),
                    available=int(getattr(row, "can_use_volume", getattr(row, "available", 0)) or 0),
                    cost_price=float(getattr(row, "open_price", getattr(row, "avg_price", 0.0)) or 0.0),
                    current_price=float(getattr(row, "last_price", getattr(row, "market_value", 0.0)) or 0.0),
                )
            )
        return positions

    def submit_order(self, request: BrokerOrderRequest) -> BrokerOrder:
        existing = self._repo.get_live_order(request.order_id)
        if request.execute_at == "next_open":
            broker_order_id = existing.broker_order_id if existing else ""
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
                    "status": "planned",
                    "reason": request.reason,
                })
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
                status="planned",
                reason=request.reason,
            )

        self._ensure_ready()

        broker_order_id = self._trader.order_stock(
            self._stock_account,
            self._normalize_code(request.code),
            self._order_type(request.direction.value),
            int(request.volume),
            self._price_type(request.price),
            float(request.price or 0.0),
            self.strategy_name,
            f"{self.order_remark_prefix}:{request.reason}"[:128],
        )
        if broker_order_id in (-1, None):
            raise RuntimeError("QMT 下单失败，返回空订单号")

        if existing is None:
            self._repo.save_live_order({
                "order_id": request.order_id,
                "instance_id": request.instance_id,
                "strategy_key": request.strategy_key,
                "broker_provider": self.name,
                "broker_order_id": str(broker_order_id),
                "code": request.code,
                "direction": request.direction.value,
                "signal_date": request.signal_date,
                "planned_execute_date": request.planned_execute_date,
                "execute_at": request.execute_at,
                "req_price": request.price,
                "req_volume": request.volume,
                "status": "submitted",
                "reason": request.reason,
            })
        else:
            self._repo.update_live_order(
                order_id=request.order_id,
                status="submitted",
                broker_order_id=str(broker_order_id),
                reason=request.reason or existing.reason or "",
            )

        return BrokerOrder(
            order_id=request.order_id,
            broker_provider=self.name,
            broker_order_id=str(broker_order_id),
            code=request.code,
            direction=request.direction.value,
            signal_date=request.signal_date,
            execute_at=request.execute_at,
            planned_execute_date=request.planned_execute_date,
            req_price=request.price,
            req_volume=request.volume,
            status="submitted",
            reason=request.reason,
        )

    def cancel_order(self, order_id: str) -> BrokerOrder | None:
        self._ensure_ready()
        row = self._repo.get_live_order(order_id)
        if row is None:
            return None

        broker_order_id = row.broker_order_id or ""
        if broker_order_id:
            result = self._trader.cancel_order_stock(self._stock_account, int(broker_order_id))
            if result != 0:
                raise RuntimeError(f"QMT 撤单失败，返回码={result}")

        self._repo.update_live_order(
            order_id=order_id,
            status="cancelled",
            broker_order_id=broker_order_id,
            reason=row.reason or "",
        )
        return BrokerOrder(
            order_id=row.order_id,
            broker_provider=row.broker_provider,
            broker_order_id=broker_order_id,
            code=row.code,
            direction=row.direction,
            signal_date=row.signal_date,
            execute_at=row.execute_at,
            planned_execute_date=row.planned_execute_date,
            req_price=row.req_price or 0.0,
            req_volume=row.req_volume or 0,
            status="cancelled",
            filled_price=row.filled_price or 0.0,
            filled_volume=row.filled_volume or 0,
            commission=row.commission or 0.0,
            reason=row.reason or "",
        )

    def list_orders(self, status: Optional[str] = None) -> list[BrokerOrder]:
        self._ensure_ready()
        rows = self._trader.query_stock_orders(self._stock_account) or []
        orders: list[BrokerOrder] = []
        for row in rows:
            req_volume = int(getattr(row, "order_volume", getattr(row, "volume", 0)) or 0)
            filled_volume = int(getattr(row, "traded_volume", getattr(row, "filled_volume", 0)) or 0)
            mapped_status = self._map_status(getattr(row, "order_status", None), filled_volume, req_volume)
            if status and mapped_status != status:
                continue

            raw_time = getattr(row, "order_time", None)
            if isinstance(raw_time, date):
                signal_date = raw_time
            elif isinstance(raw_time, (int, float)):
                signal_date = datetime.fromtimestamp(raw_time).date()
            elif isinstance(raw_time, str) and raw_time:
                try:
                    signal_date = datetime.fromisoformat(raw_time).date()
                except ValueError:
                    signal_date = date.today()
            else:
                signal_date = date.today()

            orders.append(
                BrokerOrder(
                    order_id=str(getattr(row, "order_remark", getattr(row, "order_id", "")) or ""),
                    broker_provider=self.name,
                    broker_order_id=str(getattr(row, "order_id", "")),
                    code=self._denormalize_code(str(getattr(row, "stock_code", ""))),
                    direction="BUY"
                    if int(getattr(row, "order_type", self._order_type("BUY"))) == self._order_type("BUY")
                    else "SELL",
                    signal_date=signal_date,
                    execute_at="open",
                    planned_execute_date=None,
                    req_price=float(getattr(row, "price", 0.0) or 0.0),
                    req_volume=req_volume,
                    status=mapped_status,
                    filled_price=float(getattr(row, "traded_price", getattr(row, "filled_price", 0.0)) or 0.0),
                    filled_volume=filled_volume,
                    commission=float(getattr(row, "commission", 0.0) or 0.0),
                    reason=str(getattr(row, "status_msg", getattr(row, "order_remark", "")) or ""),
                )
            )
        return orders
