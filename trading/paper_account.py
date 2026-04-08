"""
模拟盘持久化账户

与 backtest/account.py 的内存账户平行，但所有状态持久化到 SQLite。
fee.py 和 rules.py 完全复用，不做任何修改。

生命周期（每次 run_daily 调用）：
    1. load_or_create()     从数据库恢复状态
    2. new_trading_day()    T+1 解冻
    3. process_buy/sell()   处理成交（修改内存状态）
    4. update_prices()      按收盘价更新持仓估值
    5. save()               批量写回数据库
    6. record_nav()         写入每日净值快照
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from loguru import logger

from backtest.fee import FeeModel
from backtest.rules import TradingRules
from data.storage.repository import PaperRepository
from strategy.base import Direction, OrderData, Position


class PaperAccount:
    """
    持久化模拟盘账户

    属性（内存，每次 load_or_create 从数据库恢复）：
        cash            当前可用现金
        positions       dict[code, Position]
        total_commission 累计佣金
        total_tax        累计印花税
    """

    def __init__(self, strategy_name: str, initial_capital: float = None):
        """
        参数：
            strategy_name:    账户唯一标识（同策略+参数组合的名称）
            initial_capital:  仅首次创建账户时有效，后续忽略
        """
        self.strategy_name = strategy_name
        self._initial_capital_hint = initial_capital
        self._repo = PaperRepository()
        self._fee_model = FeeModel()

        # 内存状态（load_or_create 后填充）
        self._initial_capital: float = 0.0
        self._cash: float = 0.0
        self._total_commission: float = 0.0
        self._total_tax: float = 0.0
        self._positions: dict[str, Position] = {}
        self._loaded: bool = False

    # ── 属性 ──────────────────────────────────────────────────────────────

    @property
    def cash(self) -> float:
        return self._cash

    @property
    def initial_capital(self) -> float:
        return self._initial_capital

    @property
    def positions(self) -> dict[str, Position]:
        return self._positions

    @property
    def total_market_value(self) -> float:
        return sum(p.market_value for p in self._positions.values())

    @property
    def total_equity(self) -> float:
        return self._cash + self.total_market_value

    # ── 初始化 / 恢复 ─────────────────────────────────────────────────────

    def load_or_create(self) -> None:
        """从数据库加载账户状态，若不存在则创建新账户"""
        account_row = self._repo.get_paper_account(self.strategy_name)

        if account_row is None:
            if self._initial_capital_hint is None or self._initial_capital_hint <= 0:
                raise ValueError(
                    f"账户 '{self.strategy_name}' 不存在，首次创建必须提供 initial_capital"
                )
            self._repo.create_paper_account(
                self.strategy_name, self._initial_capital_hint, []
            )
            account_row = self._repo.get_paper_account(self.strategy_name)
        else:
            if self._initial_capital_hint is not None:
                logger.warning(
                    f"账户 '{self.strategy_name}' 已存在，忽略 --capital 参数"
                    f"（当前资金 {account_row.cash:,.2f}）"
                )

        self._initial_capital = account_row.initial_capital
        self._cash = account_row.cash
        self._total_commission = account_row.total_commission or 0.0
        self._total_tax = account_row.total_tax or 0.0

        # 恢复持仓
        pos_rows = self._repo.get_paper_positions(self.strategy_name)
        self._positions = {}
        for row in pos_rows:
            self._positions[row.code] = Position(
                code=row.code,
                volume=row.volume,
                available=row.available,
                cost_price=row.cost_price,
                current_price=row.current_price,
                buy_date=row.buy_date,
            )

        self._loaded = True
        logger.info(
            f"账户已加载：{self.strategy_name} | "
            f"现金 {self._cash:,.2f} | 持仓 {len(self._positions)} 只"
        )

    # ── T+1 解冻 ──────────────────────────────────────────────────────────

    def new_trading_day(self, current_date: date) -> None:
        """新交易日开始时调用，解冻昨日及之前买入的持仓"""
        for pos in self._positions.values():
            if pos.buy_date is not None and pos.buy_date < current_date:
                pos.available = pos.volume

    # ── 交易处理 ──────────────────────────────────────────────────────────

    def process_buy(self, order: OrderData) -> OrderData:
        """
        处理买入成交：扣减现金、增加持仓

        注意：今日买入的 available=0（T+1），volume 正常增加
        """
        price = order.price
        volume = order.volume
        is_etf = TradingRules.is_etf(order.code)
        fees = self._fee_model.calculate(price, volume, Direction.BUY, is_etf=is_etf)
        total_cost = price * volume + fees.total

        if total_cost > self._cash:
            order.status = "rejected"
            order.reason = f"资金不足：需 {total_cost:.2f}，可用 {self._cash:.2f}"
            logger.warning(f"买入拒绝 {order.code}: {order.reason}")
            return order

        self._cash -= total_cost
        self._total_commission += fees.commission
        self._total_tax += fees.stamp_tax

        if order.code in self._positions:
            pos = self._positions[order.code]
            total_vol = pos.volume + volume
            pos.cost_price = (pos.cost_price * pos.volume + price * volume) / total_vol
            pos.volume = total_vol
            pos.current_price = price
            pos.buy_date = order.trade_date
            # 今日新买部分不解冻（T+1），available 不变
        else:
            self._positions[order.code] = Position(
                code=order.code,
                volume=volume,
                available=0,  # T+1：今日买入不可卖
                cost_price=price,
                current_price=price,
                buy_date=order.trade_date,
            )

        order.status = "filled"
        order.filled_price = price
        order.filled_volume = volume
        order.commission = fees.total
        logger.info(
            f"买入成交 {order.code} {volume}股 @ {price:.3f} | "
            f"费用 {fees.total:.2f} | 剩余现金 {self._cash:,.2f}"
        )
        return order

    def process_sell(self, order: OrderData) -> OrderData:
        """处理卖出成交：增加现金、减少持仓"""
        pos = self._positions.get(order.code)
        if not pos or pos.available < order.volume:
            avail = pos.available if pos else 0
            order.status = "rejected"
            order.reason = f"可卖数量不足：需 {order.volume}，可卖 {avail}"
            logger.warning(f"卖出拒绝 {order.code}: {order.reason}")
            return order

        price = order.price
        volume = order.volume
        is_etf = TradingRules.is_etf(order.code)
        fees = self._fee_model.calculate(price, volume, Direction.SELL, is_etf=is_etf)
        proceeds = price * volume - fees.total

        self._cash += proceeds
        self._total_commission += fees.commission
        self._total_tax += fees.stamp_tax

        pos.volume -= volume
        pos.available -= volume
        pos.current_price = price
        if pos.volume <= 0:
            del self._positions[order.code]

        order.status = "filled"
        order.filled_price = price
        order.filled_volume = volume
        order.commission = fees.total
        logger.info(
            f"卖出成交 {order.code} {volume}股 @ {price:.3f} | "
            f"费用 {fees.total:.2f} | 剩余现金 {self._cash:,.2f}"
        )
        return order

    # ── 价格更新 ──────────────────────────────────────────────────────────

    def update_prices(self, price_map: dict[str, float]) -> None:
        """用当日收盘价更新各持仓的 current_price"""
        for code, price in price_map.items():
            if code in self._positions:
                self._positions[code].current_price = price

    # ── 持久化 ────────────────────────────────────────────────────────────

    def save(self) -> None:
        """将内存状态批量写回数据库"""
        if not self._loaded:
            return

        # 更新账户资金
        self._repo.update_paper_account(
            strategy_name=self.strategy_name,
            cash=self._cash,
            total_commission=self._total_commission,
            total_tax=self._total_tax,
        )

        # 更新持仓（upsert 现有持仓）
        if self._positions:
            records = [
                {
                    "strategy_name": self.strategy_name,
                    "code": pos.code,
                    "volume": pos.volume,
                    "available": pos.available,
                    "cost_price": pos.cost_price,
                    "current_price": pos.current_price,
                    "buy_date": pos.buy_date,
                }
                for pos in self._positions.values()
            ]
            self._repo.upsert_paper_positions(self.strategy_name, records)

        # 删除已清空的持仓（仓位为0的行）
        existing_rows = self._repo.get_paper_positions(self.strategy_name)
        for row in existing_rows:
            if row.code not in self._positions:
                self._repo.delete_paper_position(self.strategy_name, row.code)

    def record_nav(self, trade_date: date) -> None:
        """记录当日净值快照"""
        total_equity = self.total_equity
        nav_series = self._repo.get_nav_series(self.strategy_name)

        if nav_series:
            prev_equity = nav_series[-1].total_equity
        else:
            prev_equity = self._initial_capital

        nav_val = total_equity / self._initial_capital if self._initial_capital > 0 else 1.0
        daily_pnl = total_equity - prev_equity

        self._repo.save_paper_nav({
            "strategy_name": self.strategy_name,
            "trade_date": trade_date,
            "cash": round(self._cash, 2),
            "market_value": round(self.total_market_value, 2),
            "total_equity": round(total_equity, 2),
            "nav": round(nav_val, 6),
            "daily_pnl": round(daily_pnl, 2),
            "position_count": len(self._positions),
        })
