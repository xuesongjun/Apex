"""
隔夜多头策略（连续隔夜模式：今日尾盘买，明日开盘卖）

严格时序：
  - T 日收盘前 14:55 买入（近似为 T 日 close）
  - T+1 日集合竞价挂跌停价卖出（实际成交价近似为 T+1 日 open）

在“收盘后统一运行”的引擎模型下，策略在 T 日日终需要完成两件事：
  1. 若今晚将持有仓位，则预约 1 笔明早的 SELL @ next_open
  2. 若当前空仓且买入过滤通过，则执行 1 笔 BUY @ close

因此空仓日会返回两个信号：
  - BUY  @ close      （今天尾盘建仓）
  - SELL @ next_open  （预约明早开盘平仓）

而持仓日只返回一个信号：
  - SELL @ next_open  （预约明早开盘平仓）

可选过滤参数（仅作用于 BUY 分支）：
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
        pos = self.get_position(bar.code)
        holding = pos is not None and pos.volume > 0

        should_buy = False
        if not holding and bar.pre_close > 0:
            pct = (bar.close - bar.pre_close) / bar.pre_close * 100
            if min_drop is not None and -pct < min_drop:
                should_buy = False
            elif max_rise is not None and pct > max_rise:
                should_buy = False
            else:
                should_buy = True

        if should_buy:
            signals.append(Signal(
                code=bar.code,
                direction=Direction.BUY,
                trade_date=bar.trade_date,
                price=0,
                volume=0,
                reason="尾盘 14:55 卖1价全仓买入",
                execute_at="close",
            ))

        # 今晚会持仓（已有仓，或即将尾盘买入）→ 预约明早集合竞价卖出
        if holding or should_buy:
            signals.append(Signal(
                code=bar.code,
                direction=Direction.SELL,
                trade_date=bar.trade_date,
                price=0,
                volume=0,
                reason="次日集合竞价挂跌停价卖（开盘价成交）",
                execute_at="next_open",
            ))

        return signals
