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
        # MACD 增量缓存：{code: {"fast_ema", "slow_ema", "dif", "dea", "hist"}}
        self._macd_cache: dict[str, dict[str, float]] = {}

    @property
    def name(self) -> str:
        return f"MACD({self.fast_period}/{self.slow_period}/{self.signal_period})"

    def on_bar(self, bar: BarData) -> list[Signal]:
        closes = self.get_close_series(bar.code)
        min_len = self.slow_period + self.signal_period
        if len(closes) < min_len:
            return []

        code = bar.code
        fast_mul = 2 / (self.fast_period + 1)
        slow_mul = 2 / (self.slow_period + 1)
        signal_mul = 2 / (self.signal_period + 1)

        if code not in self._macd_cache:
            # 首次：用 closes[:-1] 从头初始化所有状态（只做一次）
            prev_closes = closes[:-1]
            fast_emas = _ema_series_full(prev_closes, self.fast_period)
            slow_emas = _ema_series_full(prev_closes, self.slow_period)

            min_l = min(len(fast_emas), len(slow_emas))
            dif_series = [f - s for f, s in zip(fast_emas[-min_l:], slow_emas[-min_l:])]
            dea_series = _ema_series_full(dif_series, self.signal_period)

            prev_fast = fast_emas[-1]
            prev_slow = slow_emas[-1]
            prev_dea = dea_series[-1]
            prev_dif = dif_series[-1]
            prev_hist = (prev_dif - prev_dea) * 2
        else:
            cache = self._macd_cache[code]
            prev_fast = cache["fast_ema"]
            prev_slow = cache["slow_ema"]
            prev_dea = cache["dea"]
            prev_hist = cache["hist"]

        # 当前 K 线增量更新，O(1)
        curr_fast = (closes[-1] - prev_fast) * fast_mul + prev_fast
        curr_slow = (closes[-1] - prev_slow) * slow_mul + prev_slow
        curr_dif = curr_fast - curr_slow
        curr_dea = (curr_dif - prev_dea) * signal_mul + prev_dea
        curr_hist = (curr_dif - curr_dea) * 2

        self._macd_cache[code] = {
            "fast_ema": curr_fast,
            "slow_ema": curr_slow,
            "dif": curr_dif,
            "dea": curr_dea,
            "hist": curr_hist,
        }

        # 金叉：MACD柱从负转正
        if prev_hist <= 0 and curr_hist > 0:
            if not self.has_position(code):
                strength = "强" if curr_dif > 0 else "弱"
                return [Signal(
                    code=code,
                    direction=Direction.BUY,
                    trade_date=bar.trade_date,
                    reason=f"MACD金叉({strength}): DIF={curr_dif:.3f}, HIST={curr_hist:.3f}",
                    confidence=0.9 if curr_dif > 0 else 0.6,
                )]

        # 死叉：MACD柱从正转负
        if prev_hist >= 0 and curr_hist < 0:
            if self.has_position(code):
                return [Signal(
                    code=code,
                    direction=Direction.SELL,
                    trade_date=bar.trade_date,
                    reason=f"MACD死叉: DIF={curr_dif:.3f}, HIST={curr_hist:.3f}",
                    confidence=0.8,
                )]

        return []


def _ema_series_full(values: list[float], period: int) -> list[float]:
    """从头计算完整 EMA 序列，仅在初始化时调用一次"""
    if len(values) < period:
        return []
    multiplier = 2 / (period + 1)
    ema_val = sum(values[:period]) / period
    result = [ema_val]
    for val in values[period:]:
        ema_val = (val - ema_val) * multiplier + ema_val
        result.append(ema_val)
    return result
