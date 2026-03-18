"""
均线交叉策略（Moving Average Crossover）

原理：
- 短期均线上穿长期均线（金叉）→ 买入信号
- 短期均线下穿长期均线（死叉）→ 卖出信号

参数：
- short_period: 短期均线周期（默认5）
- long_period: 长期均线周期（默认20）
- ma_type: 均线类型 SMA / EMA（默认 EMA）
"""
from typing import Optional

from strategy.base import BarData, BaseStrategy, Direction, Signal


class MACrossStrategy(BaseStrategy):
    """均线交叉策略"""

    def __init__(self, config: Optional[dict] = None):
        super().__init__(config)
        self.short_period = self.config.get("short_period", 5)
        self.long_period = self.config.get("long_period", 20)
        self.ma_type = self.config.get("ma_type", "EMA")

    @property
    def name(self) -> str:
        return f"MA交叉({self.short_period}/{self.long_period} {self.ma_type})"

    def on_bar(self, bar: BarData) -> Optional[Signal]:
        """
        每根K线触发：
        1. 计算短期和长期均线
        2. 判断金叉/死叉
        3. 产生买入/卖出信号
        """
        closes = self.get_close_series(bar.code)

        # 需要足够的历史数据才能计算均线
        if len(closes) < self.long_period + 1:
            return None

        # 计算当前和前一根的均线值
        short_ma_curr = self._calc_ma(closes, self.short_period)
        short_ma_prev = self._calc_ma(closes[:-1], self.short_period)
        long_ma_curr = self._calc_ma(closes, self.long_period)
        long_ma_prev = self._calc_ma(closes[:-1], self.long_period)

        # 金叉：短期均线从下方上穿长期均线
        if short_ma_prev <= long_ma_prev and short_ma_curr > long_ma_curr:
            if not self.has_position(bar.code):
                return Signal(
                    code=bar.code,
                    direction=Direction.BUY,
                    trade_date=bar.trade_date,
                    price=0,  # 以下一根K线开盘价成交
                    volume=0,  # 由引擎自动计算
                    reason=f"金叉: MA{self.short_period}={short_ma_curr:.2f} 上穿 MA{self.long_period}={long_ma_curr:.2f}",
                    confidence=0.8,
                )

        # 死叉：短期均线从上方下穿长期均线
        if short_ma_prev >= long_ma_prev and short_ma_curr < long_ma_curr:
            if self.has_position(bar.code):
                return Signal(
                    code=bar.code,
                    direction=Direction.SELL,
                    trade_date=bar.trade_date,
                    price=0,
                    volume=0,  # 全部卖出
                    reason=f"死叉: MA{self.short_period}={short_ma_curr:.2f} 下穿 MA{self.long_period}={long_ma_curr:.2f}",
                    confidence=0.8,
                )

        return None

    def _calc_ma(self, prices: list[float], period: int) -> float:
        """计算均线值"""
        if len(prices) < period:
            return 0.0

        if self.ma_type == "SMA":
            return sum(prices[-period:]) / period
        elif self.ma_type == "EMA":
            return self._calc_ema(prices, period)
        return 0.0

    def _calc_ema(self, prices: list[float], period: int) -> float:
        """计算指数移动平均"""
        if len(prices) < period:
            return 0.0

        multiplier = 2 / (period + 1)
        # 用前 period 个值的 SMA 作为 EMA 初始值
        ema = sum(prices[:period]) / period

        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema

        return ema
