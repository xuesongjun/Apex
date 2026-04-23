"""
实盘/准实盘执行引擎骨架

Phase 7A 目标：
- 统一策略信号 -> broker 订单请求
- 通过 broker adapter 执行
- 把账户/持仓/订单状态持久化
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Optional

from loguru import logger

from backtest.rules import TradingRules
from data.storage.repository import LiveRepository, StockRepository
from notification import Notifier
from strategy.base import BarData, BaseStrategy, Direction, Position, Signal
from trading.broker import BaseBroker, BrokerOrderRequest, BrokerPosition

_LOOKBACK_DAYS = 120


class LiveEngine:
    def __init__(
        self,
        strategy: BaseStrategy,
        stock_codes: list[str],
        broker: BaseBroker,
        instance_id: str,
        strategy_key: Optional[str] = None,
        notifier: Optional[Notifier] = None,
        run_date: Optional[date] = None,
    ):
        self.strategy = strategy
        self.strategy_key = strategy_key or strategy.name
        self.stock_codes = stock_codes
        self.broker = broker
        self.instance_id = instance_id
        self.notifier = notifier
        self.run_date = run_date or date.today()

        self._repo = StockRepository()
        self._live_repo = LiveRepository()

    def run_daily(self) -> dict:
        run_date = self.run_date

        if not self._repo.is_trade_date(run_date):
            logger.info(f"{run_date} 不是交易日，跳过实盘基座运行")
            return {}

        logger.info(
            f"=== 实盘基座运行 [{self.strategy.name}] {run_date} "
            f"| broker={self.broker.name} | instance={self.instance_id} ==="
        )

        bar_map = self._load_bars(run_date)
        if not bar_map:
            logger.warning(f"{run_date} 所有标的均无行情数据，跳过")
            return {}

        activation_result = self._submit_due_planned_orders(run_date, bar_map)

        broker_account = self.broker.get_account()
        broker_positions = self.broker.get_positions()
        self._sync_live_snapshot(broker_account, broker_positions)

        self._rebuild_bar_history(run_date)
        self.strategy._sync_account(
            self._to_strategy_positions(broker_positions),
            broker_account.cash,
            broker_account.total_equity,
        )

        signals: list[Signal] = []
        for code in self.stock_codes:
            bar = bar_map.get(code)
            if bar is None:
                continue
            self.strategy._update_bar(bar)
            signals.extend(self.strategy.on_bar(bar))

        requests = self._build_order_requests(
            signals=signals,
            bar_map=bar_map,
            positions=broker_positions,
            available_cash=broker_account.cash,
            signal_date=run_date,
        )

        submitted = 0
        rejected = 0
        for request in requests:
            try:
                order = self.broker.submit_order(request)
                logger.info(
                    f"broker 提交成功 {order.direction} {order.code} "
                    f"{order.req_volume}股 status={order.status}"
                )
                submitted += 1
            except Exception as e:
                logger.error(f"broker 提交失败 {request.code} {request.direction.value}: {e}")
                self._notify(
                    subject=f"[Apex][Live][Submit Failed] {self.strategy_key} {request.code}",
                    body=(
                        f"实例ID: {self.instance_id}\n"
                        f"策略: {self.strategy.name}\n"
                        f"Broker: {self.broker.name}\n"
                        f"订单ID: {request.order_id}\n"
                        f"方向: {request.direction.value}\n"
                        f"代码: {request.code}\n"
                        f"执行时机: {request.execute_at}\n"
                        f"计划执行日: {request.planned_execute_date}\n"
                        f"价格: {request.price}\n"
                        f"数量: {request.volume}\n"
                        f"原因: {e}\n"
                    ),
                )
                rejected += 1

        summary = {
            "run_date": run_date,
            "instance_id": self.instance_id,
            "strategy": self.strategy.name,
            "broker": self.broker.name,
            "planned_orders_activated": activation_result["submitted"],
            "planned_orders_failed": activation_result["rejected"],
            "signals_generated": len(signals),
            "orders_built": len(requests),
            "orders_submitted": submitted,
            "orders_rejected": rejected,
            "cash": broker_account.cash,
            "total_equity": broker_account.total_equity,
            "position_count": len(broker_positions),
        }
        logger.info(
            f"实盘基座运行完成 | 信号 {len(signals)} 个 | "
            f"委托 {len(requests)} 笔 | 成功 {submitted} | 拒绝 {rejected} | "
            f"计划单激活 {activation_result['submitted']}/{activation_result['total']}"
        )
        return summary

    def _submit_due_planned_orders(
        self,
        run_date: date,
        bar_map: dict[str, BarData],
    ) -> dict:
        due_orders = self._live_repo.get_due_live_orders(self.instance_id, run_date)
        result = {"total": len(due_orders), "submitted": 0, "rejected": 0}
        for row in due_orders:
            bar = bar_map.get(row.code)
            if bar is None:
                self._live_repo.update_live_order(
                    order_id=row.order_id,
                    status="rejected",
                    broker_order_id=row.broker_order_id or "",
                    reason="到期执行时无行情数据",
                )
                self._notify(
                    subject=f"[Apex][Live][Activation Failed] {self.strategy_key} {row.code}",
                    body=(
                        f"实例ID: {self.instance_id}\n"
                        f"策略: {self.strategy.name}\n"
                        f"Broker: {self.broker.name}\n"
                        f"订单ID: {row.order_id}\n"
                        f"代码: {row.code}\n"
                        f"执行日: {run_date}\n"
                        "原因: 到期执行时无行情数据\n"
                    ),
                )
                result["rejected"] += 1
                continue

            req_price = row.req_price or bar.open
            request = BrokerOrderRequest(
                order_id=row.order_id,
                instance_id=row.instance_id,
                strategy_key=row.strategy_key,
                code=row.code,
                direction=Direction(row.direction),
                signal_date=row.signal_date,
                execute_at="open",
                planned_execute_date=run_date,
                price=req_price,
                volume=row.req_volume or 0,
                reason=row.reason or "",
            )

            try:
                self.broker.submit_order(request)
                result["submitted"] += 1
            except Exception as e:
                self._live_repo.update_live_order(
                    order_id=row.order_id,
                    status="rejected",
                    broker_order_id=row.broker_order_id or "",
                    reason=str(e),
                )
                self._notify(
                    subject=f"[Apex][Live][Activation Failed] {self.strategy_key} {row.code}",
                    body=(
                        f"实例ID: {self.instance_id}\n"
                        f"策略: {self.strategy.name}\n"
                        f"Broker: {self.broker.name}\n"
                        f"订单ID: {row.order_id}\n"
                        f"代码: {row.code}\n"
                        f"执行日: {run_date}\n"
                        f"原因: {e}\n"
                    ),
                )
                result["rejected"] += 1
        return result

    def _load_bars(self, trade_date: date) -> dict[str, BarData]:
        bar_map: dict[str, BarData] = {}
        for code in self.stock_codes:
            df = self._repo.get_daily_bars(code, trade_date, trade_date)
            if df.empty:
                continue
            row = df.iloc[0]
            bar_map[code] = BarData(
                code=code,
                trade_date=row["trade_date"],
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                pre_close=row.get("pre_close") or row["close"],
                volume=int(row.get("volume") or 0),
                amount=float(row.get("amount") or 0.0),
            )
        return bar_map

    def _rebuild_bar_history(self, run_date: date) -> None:
        history_start = run_date - timedelta(days=_LOOKBACK_DAYS * 2)
        history_end = run_date - timedelta(days=1)
        for code in self.stock_codes:
            df = self._repo.get_daily_bars(code, history_start, history_end)
            if df.empty:
                continue
            for _, row in df.iterrows():
                self.strategy._update_bar(
                    BarData(
                        code=code,
                        trade_date=row["trade_date"],
                        open=row["open"],
                        high=row["high"],
                        low=row["low"],
                        close=row["close"],
                        pre_close=row.get("pre_close") or row["close"],
                        volume=int(row.get("volume") or 0),
                        amount=float(row.get("amount") or 0.0),
                    )
                )

    def _to_strategy_positions(
        self,
        broker_positions: list[BrokerPosition],
    ) -> dict[str, Position]:
        return {
            p.code: Position(
                code=p.code,
                volume=p.volume,
                available=p.available,
                cost_price=p.cost_price,
                current_price=p.current_price,
            )
            for p in broker_positions
        }

    def _sync_live_snapshot(self, broker_account, broker_positions: list[BrokerPosition]) -> None:
        live_account = self._live_repo.get_live_account(self.instance_id)
        if live_account is None:
            self._live_repo.create_live_account(
                instance_id=self.instance_id,
                strategy_key=self.strategy_key,
                broker_provider=self.broker.name,
                broker_account_id=broker_account.broker_account_id,
                initial_capital=broker_account.total_equity,
                stock_codes=self.stock_codes,
                cash=broker_account.cash,
                total_equity=broker_account.total_equity,
            )
        else:
            self._live_repo.update_live_account(
                instance_id=self.instance_id,
                cash=broker_account.cash,
                total_equity=broker_account.total_equity,
                stock_codes=self.stock_codes,
                broker_account_id=broker_account.broker_account_id,
                status=broker_account.status,
            )

        self._live_repo.replace_live_positions(
            self.instance_id,
            [
                {
                    "instance_id": self.instance_id,
                    "code": p.code,
                    "volume": p.volume,
                    "available": p.available,
                    "cost_price": p.cost_price,
                    "current_price": p.current_price,
                    "source": "broker",
                }
                for p in broker_positions
            ],
        )

    def _build_order_requests(
        self,
        signals: list[Signal],
        bar_map: dict[str, BarData],
        positions: list[BrokerPosition],
        available_cash: float,
        signal_date: date,
    ) -> list[BrokerOrderRequest]:
        pos_map = {p.code: p for p in positions}
        sell_signals = [s for s in signals if s.direction == Direction.SELL]
        buy_signals = [s for s in signals if s.direction == Direction.BUY]
        ordered_signals = sell_signals + buy_signals
        planned_buy_volumes = self._estimate_buy_volumes(
            buy_signals=buy_signals,
            bar_map=bar_map,
            available_cash=available_cash,
        )

        requests: list[BrokerOrderRequest] = []
        for signal in ordered_signals:
            bar = bar_map.get(signal.code)
            if bar is None:
                continue

            planned_execute_date = (
                self._next_trade_date(signal_date)
                if signal.execute_at == "next_open"
                else signal_date
            )
            req_price = self._resolve_price(signal, bar)
            volume = self._resolve_volume(
                signal,
                bar,
                pos_map,
                available_cash,
                planned_buy_volumes=planned_buy_volumes,
            )

            if volume <= 0:
                continue

            if signal.direction == Direction.SELL:
                pos = pos_map.get(signal.code)
                available = pos.available if pos else 0
                if available <= 0 and signal.execute_at == "next_open":
                    available = planned_buy_volumes.get(signal.code, 0)
                if available <= 0 or volume > available:
                    continue
                if not TradingRules.is_valid_sell_volume(volume, available):
                    continue

            requests.append(
                BrokerOrderRequest(
                    order_id=uuid.uuid4().hex,
                    instance_id=self.instance_id,
                    strategy_key=self.strategy_key,
                    code=signal.code,
                    direction=signal.direction,
                    signal_date=signal_date,
                    execute_at=signal.execute_at,
                    planned_execute_date=planned_execute_date,
                    price=req_price,
                    volume=volume,
                    reason=signal.reason or "",
                )
            )
        return requests

    def _estimate_buy_volumes(
        self,
        buy_signals: list[Signal],
        bar_map: dict[str, BarData],
        available_cash: float,
    ) -> dict[str, int]:
        estimates: dict[str, int] = {}
        cash_cursor = available_cash
        for signal in buy_signals:
            bar = bar_map.get(signal.code)
            if bar is None:
                continue
            volume = self._resolve_volume(
                signal,
                bar,
                {},
                cash_cursor,
                planned_buy_volumes={},
            )
            if volume <= 0:
                continue
            estimates[signal.code] = volume
            ref_price = signal.price if signal.price > 0 else bar.close
            cash_cursor = max(0.0, cash_cursor - ref_price * volume)
        return estimates

    def _resolve_price(self, signal: Signal, bar: BarData) -> float:
        if signal.price > 0:
            return signal.price
        if signal.execute_at == "close":
            return round(bar.close, 3)
        if signal.execute_at == "open":
            return round(bar.open, 3)
        return 0.0

    def _resolve_volume(
        self,
        signal: Signal,
        bar: BarData,
        pos_map: dict[str, BrokerPosition],
        available_cash: float,
        planned_buy_volumes: dict[str, int],
    ) -> int:
        if signal.volume > 0:
            if signal.direction == Direction.BUY:
                return TradingRules.round_volume(signal.volume, Direction.BUY)
            return signal.volume

        if signal.direction == Direction.BUY:
            ref_price = signal.price if signal.price > 0 else bar.close
            if ref_price <= 0:
                return 0
            max_vol = int(available_cash * 0.95 / ref_price)
            return TradingRules.round_volume(max_vol, Direction.BUY)

        pos = pos_map.get(signal.code)
        if pos and pos.available > 0:
            return pos.available
        if signal.execute_at == "next_open":
            return planned_buy_volumes.get(signal.code, 0)
        return 0

    def _next_trade_date(self, current_date: date) -> Optional[date]:
        check = current_date + timedelta(days=1)
        for _ in range(30):
            if self._repo.is_trade_date(check):
                return check
            check += timedelta(days=1)
        return None

    def _notify(self, subject: str, body: str) -> None:
        if not self.notifier:
            return
        try:
            self.notifier.notify(subject, body)
        except Exception as e:
            logger.error(f"邮件通知发送失败: {e}")
