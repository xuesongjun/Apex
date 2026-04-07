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
        # EMA 增量缓存：{code: {"short": float, "long": float}}
        # 存储上一根 K 线处理完后的 EMA 值，下一根 K 线用作 prev
        self._ema_cache: dict[str, dict[str, float]] = {}

    @property
    def name(self) -> str:
        return f"MA交叉({self.short_period}/{self.long_period} {self.ma_type})"

    def on_bar(self, bar: BarData) -> Optional[Signal]:
        closes = self.get_close_series(bar.code)
        if len(closes) < self.long_period + 1:
            return None

        code = bar.code

        if self.ma_type == "SMA":
            # SMA：直接窗口切片，O(period)，无需缓存
            short_ma_prev = sum(closes[-self.short_period - 1:-1]) / self.short_period
            short_ma_curr = sum(closes[-self.short_period:]) / self.short_period
            long_ma_prev = sum(closes[-self.long_period - 1:-1]) / self.long_period
            long_ma_curr = sum(closes[-self.long_period:]) / self.long_period
        else:
            # EMA：增量计算，每根 K 线 O(1)
            sm = 2 / (self.short_period + 1)
            lm = 2 / (self.long_period + 1)

            if code not in self._ema_cache:
                # 首次到达足够数据：从头算一次 closes[:-1] 作为 prev（只发生一次）
                prev_closes = closes[:-1]
                short_prev = self._calc_ema_full(prev_closes, self.short_period)
                long_prev = self._calc_ema_full(prev_closes, self.long_period)
            else:
                cache = self._ema_cache[code]
                short_prev = cache["short"]
                long_prev = cache["long"]

            short_curr = (closes[-1] - short_prev) * sm + short_prev
            long_curr = (closes[-1] - long_prev) * lm + long_prev

            # 更新缓存（存当前值，下次作为 prev）
            self._ema_cache[code] = {"short": short_curr, "long": long_curr}

            short_ma_prev, short_ma_curr = short_prev, short_curr
            long_ma_prev, long_ma_curr = long_prev, long_curr

        # 金叉：短期均线从下方上穿长期均线
        if short_ma_prev <= long_ma_prev and short_ma_curr > long_ma_curr:
            if not self.has_position(code):
                return Signal(
                    code=code,
                    direction=Direction.BUY,
                    trade_date=bar.trade_date,
                    price=0,
                    volume=0,
                    reason=f"金叉: MA{self.short_period}={short_ma_curr:.2f} 上穿 MA{self.long_period}={long_ma_curr:.2f}",
                    confidence=0.8,
                )

        # 死叉：短期均线从上方下穿长期均线
        if short_ma_prev >= long_ma_prev and short_ma_curr < long_ma_curr:
            if self.has_position(code):
                return Signal(
                    code=code,
                    direction=Direction.SELL,
                    trade_date=bar.trade_date,
                    price=0,
                    volume=0,
                    reason=f"死叉: MA{self.short_period}={short_ma_curr:.2f} 下穿 MA{self.long_period}={long_ma_curr:.2f}",
                    confidence=0.8,
                )

        return None

    @staticmethod
    def _calc_ema_full(prices: list[float], period: int) -> float:
        """从头计算 EMA，仅在首次初始化时调用一次"""
        if len(prices) < period:
            return 0.0
        ema = sum(prices[:period]) / period
        mul = 2 / (period + 1)
        for price in prices[period:]:
            ema = (price - ema) * mul + ema
        return ema
