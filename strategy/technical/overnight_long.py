"""
隔夜多头策略（连续隔夜模式：每天尾盘买 + 次日开盘卖 + 同日尾盘再买）

交易规则：
  - T 日 14:55 以卖1价全仓买入（近似为 T 日收盘价买入）
  - T+1 日 9:20 集合竞价挂跌停价卖（实际成交于 T+1 日开盘价）
  - T+1 日 14:55 继续全仓买入 → T+2 日 9:20 继续挂卖
  - 若 T+1 日开盘即一字跌停（挂不出去），则当日不再买入（资金已被占用）

关键判定：
  - 有可卖仓位 + 非一字跌停 → 生成 SELL（next_open 成交）
  - 当前空仓 OR 本 bar 即将通过 SELL 清仓 → 生成 BUY（close 成交）
  - 一字跌停判定：bar.open <= pre_close × (1 - limit_pct)（含浮点容差 1e-6）

可选过滤参数（仅作用于 BUY 分支）：
  - min_drop_pct: 当日跌幅必须 ≥ 该值才买入（抄反弹）
  - max_rise_pct: 当日涨幅必须 ≤ 该值才买入（避免追高）
  - limit_pct:    涨跌停幅度，默认 0.10（主板/跨境 ETF），创业板/科创板 ETF 应传 0.20
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
        limit_pct: float = self.config.get("limit_pct", 0.10)

        pos = self.get_position(bar.code)
        has_sellable = pos is not None and pos.available > 0

        # 一字跌停判定：开盘价 <= 跌停价（浮点容差 1e-6）
        sell_blocked = False
        if has_sellable and bar.pre_close > 0:
            limit_down_price = round(bar.pre_close * (1 - limit_pct), 3)
            if bar.open <= limit_down_price + 1e-6:
                sell_blocked = True

        # 1) 卖出：有可卖仓位 + 非一字跌停 → 次日集合竞价挂跌停价卖
        if has_sellable and not sell_blocked:
            signals.append(Signal(
                code=bar.code,
                direction=Direction.SELL,
                trade_date=bar.trade_date,
                price=0,
                volume=0,
                reason="集合竞价挂跌停价卖（开盘价成交）",
                execute_at="next_open",
            ))

        # 2) 买入：当前真空仓 OR 即将通过本 bar SELL 清仓
        #    冻结日（pos 存在但 available=0）与一字跌停被套都视为"仓位仍在"，不买
        currently_empty = pos is None or pos.volume == 0
        will_sell_all = has_sellable and not sell_blocked
        will_be_empty = currently_empty or will_sell_all
        if will_be_empty and bar.pre_close > 0:
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
