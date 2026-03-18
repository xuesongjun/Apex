"""
MACD 策略（Moving Average Convergence Divergence）

原理：
- MACD柱由负转正（DIF上穿DEA）→ 买入信号
- MACD柱由正转负（DIF下穿DEA）→ 卖出信号
- 零轴上方金叉强于零轴下方金叉

参数：
- fast_period: 快线周期（默认12）
- slow_period: 慢线周期（默认26）
- signal_period: 信号线周期（默认9）
"""
from typing import Optional

from strategy.base import BarData, BaseStrategy, Direction, Signal


class MACDStrategy(BaseStrategy):
    """MACD 策略"""

    def __init__(self, config: Optional[dict] = None):
        super().__init__(config)
        self.fast_period = self.config.get("fast_period", 12)
        self.slow_period = self.config.get("slow_period", 26)
        self.signal_period = self.config.get("signal_period", 9)
        # 缓存每只股票的 MACD 历史值
        self._macd_history: dict[str, list[dict]] = {}

    @property
    def name(self) -> str:
        return f"MACD({self.fast_period}/{self.slow_period}/{self.signal_period})"

    def on_bar(self, bar: BarData) -> Optional[Signal]:
        closes = self.get_close_series(bar.code)
        min_len = self.slow_period + self.signal_period
        if len(closes) < min_len:
            return None

        # 计算 MACD
        dif, dea, macd_hist = self._calc_macd(closes)
        if len(macd_hist) < 2:
            return None

        curr_hist = macd_hist[-1]
        prev_hist = macd_hist[-2]
        curr_dif = dif[-1]

        # 金叉：MACD柱从负转正
        if prev_hist <= 0 and curr_hist > 0:
            if not self.has_position(bar.code):
                strength = "强" if curr_dif > 0 else "弱"
                return Signal(
                    code=bar.code,
                    direction=Direction.BUY,
                    trade_date=bar.trade_date,
                    reason=f"MACD金叉({strength}): DIF={curr_dif:.3f}, HIST={curr_hist:.3f}",
                    confidence=0.9 if curr_dif > 0 else 0.6,
                )

        # 死叉：MACD柱从正转负
        if prev_hist >= 0 and curr_hist < 0:
            if self.has_position(bar.code):
                return Signal(
                    code=bar.code,
                    direction=Direction.SELL,
                    trade_date=bar.trade_date,
                    reason=f"MACD死叉: DIF={curr_dif:.3f}, HIST={curr_hist:.3f}",
                    confidence=0.8,
                )

        return None

    def _calc_macd(
        self, prices: list[float]
    ) -> tuple[list[float], list[float], list[float]]:
        """
        计算 MACD 三要素

        返回:
            (DIF列表, DEA列表, MACD柱列表)
        """
        # 快线 EMA
        fast_ema = self._ema_series(prices, self.fast_period)
        # 慢线 EMA
        slow_ema = self._ema_series(prices, self.slow_period)

        # DIF = 快线 - 慢线
        min_len = min(len(fast_ema), len(slow_ema))
        fast_tail = fast_ema[-min_len:]
        slow_tail = slow_ema[-min_len:]
        dif = [f - s for f, s in zip(fast_tail, slow_tail)]

        # DEA = DIF 的 EMA
        dea = self._ema_series(dif, self.signal_period)

        # MACD 柱 = (DIF - DEA) * 2
        dif_tail = dif[-len(dea):]
        macd_hist = [(d - e) * 2 for d, e in zip(dif_tail, dea)]

        return dif_tail, dea, macd_hist

    @staticmethod
    def _ema_series(values: list[float], period: int) -> list[float]:
        """计算 EMA 序列"""
        if len(values) < period:
            return []

        multiplier = 2 / (period + 1)
        ema_val = sum(values[:period]) / period
        result = [ema_val]

        for val in values[period:]:
            ema_val = (val - ema_val) * multiplier + ema_val
            result.append(ema_val)

        return result
