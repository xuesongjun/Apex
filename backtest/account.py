"""
账户管理
维护资金、持仓、冻结状态，处理订单成交后的资产变动
"""
from datetime import date
from typing import Optional

from loguru import logger

from backtest.fee import FeeModel, FeeResult
from strategy.base import Direction, OrderData, Position


class Account:
    """交易账户"""

    def __init__(self, initial_capital: float):
        self.initial_capital = initial_capital
        self.cash = initial_capital            # 可用资金
        self.frozen_cash = 0.0                 # 冻结资金（已委托未成交）
        self.positions: dict[str, Position] = {}  # 持仓
        self.fee_model = FeeModel()
        self.total_commission = 0.0            # 累计手续费
        self.total_tax = 0.0                   # 累计印花税

        # 每日资产记录（用于绩效评估）
        self.equity_curve: list[dict] = []

    @property
    def total_market_value(self) -> float:
        """总持仓市值"""
        return sum(pos.market_value for pos in self.positions.values())

    @property
    def total_equity(self) -> float:
        """总资产 = 可用资金 + 冻结资金 + 持仓市值"""
        return self.cash + self.frozen_cash + self.total_market_value

    @property
    def total_profit(self) -> float:
        """总盈亏"""
        return self.total_equity - self.initial_capital

    @property
    def total_profit_pct(self) -> float:
        """总收益率"""
        return self.total_profit / self.initial_capital

    def get_position(self, code: str) -> Optional[Position]:
        """获取持仓"""
        return self.positions.get(code)

    def update_prices(self, price_map: dict[str, float]):
        """
        更新所有持仓的当前价格
        每根K线推送后调用
        """
        for code, price in price_map.items():
            if code in self.positions:
                self.positions[code].current_price = price

    def new_trading_day(self, current_date: date):
        """
        新交易日开始时调用
        将昨日买入的股票变为可卖（T+1规则）
        """
        for pos in self.positions.values():
            if pos.buy_date is not None and pos.buy_date < current_date:
                # 昨天及之前买入的全部变为可卖
                pos.available = pos.volume

    def process_buy(self, order: OrderData) -> OrderData:
        """
        处理买入成交

        计算费用，扣减资金，增加持仓
        """
        price = order.price
        volume = order.volume
        fees = self.fee_model.calculate(price, volume, Direction.BUY)
        total_cost = price * volume + fees.total

        # 资金不足检查
        if total_cost > self.cash:
            order.status = "rejected"
            order.reason = f"资金不足：需 {total_cost:.2f}，可用 {self.cash:.2f}"
            return order

        # 扣减资金
        self.cash -= total_cost
        self.total_commission += fees.commission
        self.total_tax += fees.stamp_tax

        # 更新持仓
        if order.code in self.positions:
            pos = self.positions[order.code]
            # 加仓：重新计算成本价
            total_volume = pos.volume + volume
            pos.cost_price = (
                (pos.cost_price * pos.volume + price * volume) / total_volume
            )
            pos.volume = total_volume
            pos.current_price = price
            pos.buy_date = order.trade_date
            # 注意：今日买入部分不能卖出（available 不增加）
        else:
            self.positions[order.code] = Position(
                code=order.code,
                volume=volume,
                available=0,  # T+1：今日买入不可卖
                cost_price=price,
                current_price=price,
                buy_date=order.trade_date,
            )

        # 更新订单状态
        order.status = "filled"
        order.filled_price = price
        order.filled_volume = volume
        order.commission = fees.total

        logger.debug(
            f"买入成交: {order.code} {volume}股 @ {price:.2f}, "
            f"费用 {fees.total:.2f}, 剩余资金 {self.cash:.2f}"
        )
        return order

    def process_sell(self, order: OrderData) -> OrderData:
        """
        处理卖出成交

        计算费用，增加资金，减少持仓
        """
        pos = self.positions.get(order.code)
        if not pos or pos.available < order.volume:
            order.status = "rejected"
            avail = pos.available if pos else 0
            order.reason = f"可卖数量不足：需 {order.volume}，可卖 {avail}"
            return order

        price = order.price
        volume = order.volume
        fees = self.fee_model.calculate(price, volume, Direction.SELL)
        proceeds = price * volume - fees.total

        # 增加资金
        self.cash += proceeds
        self.total_commission += fees.commission
        self.total_tax += fees.stamp_tax

        # 更新持仓
        pos.volume -= volume
        pos.available -= volume
        pos.current_price = price

        # 持仓清零则删除
        if pos.volume <= 0:
            del self.positions[order.code]

        # 更新订单状态
        order.status = "filled"
        order.filled_price = price
        order.filled_volume = volume
        order.commission = fees.total

        logger.debug(
            f"卖出成交: {order.code} {volume}股 @ {price:.2f}, "
            f"费用 {fees.total:.2f}, 回收 {proceeds:.2f}"
        )
        return order

    def record_equity(self, current_date: date):
        """记录当日资产快照"""
        self.equity_curve.append({
            "date": current_date,
            "cash": round(self.cash, 2),
            "market_value": round(self.total_market_value, 2),
            "total_equity": round(self.total_equity, 2),
            "position_count": len(self.positions),
        })

    def get_summary(self) -> dict:
        """获取账户摘要"""
        return {
            "initial_capital": self.initial_capital,
            "total_equity": round(self.total_equity, 2),
            "cash": round(self.cash, 2),
            "market_value": round(self.total_market_value, 2),
            "total_profit": round(self.total_profit, 2),
            "total_profit_pct": round(self.total_profit_pct * 100, 2),
            "total_commission": round(self.total_commission, 2),
            "total_tax": round(self.total_tax, 2),
            "position_count": len(self.positions),
        }
