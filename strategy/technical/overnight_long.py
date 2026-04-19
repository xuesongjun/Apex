"""
隔夜多头策略（尾盘买 / 次日开盘卖）

交易规则：
  - T 日 14:55 以卖1价全仓买入（近似为 T 日收盘价买入）
  - T+1 日 9:20 集合竞价挂跌停价卖（实际成交于 T+1 日开盘价）

边界处理：
  - 空仓才买入（C 项守卫），避免重复加仓
  - 有可卖仓位才挂卖，T+1 冻结期跳过
  - 被一字跌停套牢时，次日 available 解冻后继续挂卖（A 方案）

可选过滤参数（默认禁用）：
  - min_drop_pct: 当日跌幅必须 ≥ 该值才买入（抄反弹）
  - max_rise_pct: 当日涨幅必须 ≤ 该值才买入（避免追高）
"""
from typing import Optional

from strategy.base import BarData, BaseStrategy, Direction, Signal


class OvernightLongStrategy(BaseStrategy):

    @property
    def name(self) -> str:
        return "overnight_long"

    def on_bar(self, bar: BarData) -> list[Signal]:
        signals: list[Signal] = []
        min_drop: Optional[float] = self.config.get("min_drop_pct")
        max_rise: Optional[float] = self.config.get("max_rise_pct")

        # 1) 卖出：有可卖仓位 → 次日集合竞价挂跌停价卖（开盘成交）
        pos = self.get_position(bar.code)
        if pos and pos.available > 0:
            signals.append(Signal(
                code=bar.code,
                direction=Direction.SELL,
                trade_date=bar.trade_date,
                price=0,
                volume=0,
                reason="次日集合竞价挂跌停价卖（开盘价成交）",
                execute_at="next_open",
            ))

        # 2) 买入：空仓 + 通过过滤 → 当日收盘价全仓买（近似 14:55 卖1价）
        if not self.has_position(bar.code) and bar.pre_close > 0:
            pct = (bar.close - bar.pre_close) / bar.pre_close * 100
            if min_drop is not None and -pct < min_drop:
                return signals
            if max_rise is not None and pct > max_rise:
                return signals
            signals.append(Signal(
                code=bar.code,
                direction=Direction.BUY,
                trade_date=bar.trade_date,
                price=0,
                volume=0,
                reason="尾盘 14:55 卖1价全仓买入",
                execute_at="close",
            ))

        return signals
