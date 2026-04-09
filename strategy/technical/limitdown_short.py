"""
跌停做空（集合竞价卖出 + 收盘买入）策略

原理：
- 每日开盘集合竞价：以跌停价挂卖单，竞价出清时以开盘价成交
- 每日收盘前：以收盘价买回

A股集合竞价机制：
  集合竞价阶段挂跌停价卖出 → 若有买盘，系统以竞价出清价（即开盘价）成交
  因此：卖出实际成交价 = 开盘价（而非跌停价）

信号说明：
  每日产生两个信号：
    1. execute_at="open"  → 开盘价卖出（模拟集合竞价阶段挂跌停价）
    2. execute_at="close" → 收盘价买入

参数：
  无（纯执行策略，不依赖均线等计算）
"""
from typing import Optional

from strategy.base import BarData, BaseStrategy, Direction, Signal


class LimitDownShortStrategy(BaseStrategy):
    """
    跌停做空策略

    每个交易日：
      - 以开盘价卖出（集合竞价挂跌停价，出清时以开盘价成交）
      - 以收盘价买入
    """

    @property
    def name(self) -> str:
        return "跌停做空(竞价卖出+收盘买入)"

    def on_bar(self, bar: BarData) -> list[Signal]:
        signals: list[Signal] = []

        # 开盘价卖出（有持仓才卖）
        if self.has_position(bar.code):
            signals.append(Signal(
                code=bar.code,
                direction=Direction.SELL,
                trade_date=bar.trade_date,
                price=0,        # 0 = 由引擎按 execute_at 决定价格
                volume=0,       # 0 = 全部可卖持仓
                reason="集合竞价跌停挂卖，以开盘价成交",
                execute_at="open",
            ))

        # 收盘价买入（无持仓才买）
        if not self.has_position(bar.code):
            signals.append(Signal(
                code=bar.code,
                direction=Direction.BUY,
                trade_date=bar.trade_date,
                price=0,        # 0 = 由引擎按 execute_at 决定价格
                volume=0,       # 0 = 用可用资金估算最大量
                reason="收盘前买入",
                execute_at="close",
            ))

        return signals
