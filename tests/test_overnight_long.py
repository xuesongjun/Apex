"""
overnight_long 策略单元测试

覆盖所有信号分支，构造 BarData 直接喂给策略，不依赖数据库/引擎。
"""
from datetime import date

import pytest

from strategy.base import BarData, Direction, Position
from strategy.technical.overnight_long import OvernightLongStrategy


def make_bar(code="513090", trade_date=None, close=1.0, pre_close=1.0):
    """构造一根 BarData 便于测试"""
    td = trade_date or date(2026, 1, 5)
    return BarData(
        code=code,
        trade_date=td,
        open=pre_close,
        high=max(pre_close, close),
        low=min(pre_close, close),
        close=close,
        pre_close=pre_close,
        volume=1_000_000,
        amount=close * 1_000_000,
    )


def test_empty_position_generates_buy_signal():
    """空仓 + 默认参数 → 产生 1 个 BUY 信号，execute_at='close'，volume=0 由引擎解析"""
    strategy = OvernightLongStrategy()
    bar = make_bar(close=1.80, pre_close=1.82)

    signals = strategy.on_bar(bar)

    assert len(signals) == 1
    s = signals[0]
    assert s.direction == Direction.BUY
    assert s.code == "513090"
    assert s.execute_at == "close"
    assert s.volume == 0
    assert s.price == 0


def test_held_position_generates_sell_signal():
    """有可卖仓位 → 产生 1 个 SELL 信号，execute_at='next_open'"""
    strategy = OvernightLongStrategy()
    pos = Position(
        code="513090",
        volume=10000,
        available=10000,
        cost_price=1.80,
        current_price=1.80,
        buy_date=date(2026, 1, 4),
    )
    strategy._sync_account(positions={"513090": pos}, cash=0.0, total_value=18000.0)

    bar = make_bar(close=1.85, pre_close=1.80)
    signals = strategy.on_bar(bar)

    assert len(signals) == 1
    s = signals[0]
    assert s.direction == Direction.SELL
    assert s.execute_at == "next_open"
    assert s.volume == 0    # 0 = 全部可卖持仓，引擎解析


def test_position_with_zero_available_skips_sell():
    """T+1 未解冻（available=0）→ 不产 SELL 信号，也不产 BUY（因为 has_position=True）"""
    strategy = OvernightLongStrategy()
    pos = Position(
        code="513090",
        volume=10000,
        available=0,    # 今日刚买入，T+1 未解冻
        cost_price=1.80,
        current_price=1.80,
        buy_date=date(2026, 1, 5),
    )
    strategy._sync_account(positions={"513090": pos}, cash=0.0, total_value=18000.0)

    bar = make_bar(close=1.85, pre_close=1.80)
    signals = strategy.on_bar(bar)

    assert len(signals) == 0


def test_filters_disabled_by_default_even_on_big_rise():
    """默认两参数 None → 当日涨 5% 也产 BUY（过滤未生效）"""
    strategy = OvernightLongStrategy()
    bar = make_bar(close=1.05, pre_close=1.00)  # 涨 5%
    signals = strategy.on_bar(bar)

    assert len(signals) == 1
    assert signals[0].direction == Direction.BUY


def test_min_drop_pct_blocks_when_drop_insufficient():
    """min_drop_pct=3 + 当日跌 2% → 不产 BUY（跌幅不足）"""
    strategy = OvernightLongStrategy(config={"min_drop_pct": 3.0})
    bar = make_bar(close=0.98, pre_close=1.00)   # 跌 2%
    signals = strategy.on_bar(bar)
    assert len(signals) == 0


def test_min_drop_pct_allows_when_drop_sufficient():
    """min_drop_pct=3 + 当日跌 5% → 产 BUY（跌幅达标）"""
    strategy = OvernightLongStrategy(config={"min_drop_pct": 3.0})
    bar = make_bar(close=0.95, pre_close=1.00)   # 跌 5%
    signals = strategy.on_bar(bar)
    assert len(signals) == 1
    assert signals[0].direction == Direction.BUY


def test_max_rise_pct_blocks_when_rise_exceeds():
    """max_rise_pct=3 + 当日涨 5% → 不产 BUY（涨幅超限）"""
    strategy = OvernightLongStrategy(config={"max_rise_pct": 3.0})
    bar = make_bar(close=1.05, pre_close=1.00)   # 涨 5%
    signals = strategy.on_bar(bar)
    assert len(signals) == 0


def test_two_day_cycle_buy_then_sell_no_rebuy():
    """
    T 日空仓 → 产 BUY
    T+1 日持仓（模拟已买入、T+1 已解冻）→ 产 SELL 且不再产 BUY（C 项守卫）
    """
    strategy = OvernightLongStrategy()

    # T 日：空仓
    bar_t = make_bar(trade_date=date(2026, 1, 5), close=1.80, pre_close=1.82)
    signals_t = strategy.on_bar(bar_t)
    assert len(signals_t) == 1
    assert signals_t[0].direction == Direction.BUY

    # T+1 日：模拟持仓已买入并解冻
    pos = Position(
        code="513090",
        volume=10000,
        available=10000,
        cost_price=1.80,
        current_price=1.80,
        buy_date=date(2026, 1, 5),
    )
    strategy._sync_account(positions={"513090": pos}, cash=0.0, total_value=18000.0)

    bar_t1 = make_bar(trade_date=date(2026, 1, 6), close=1.85, pre_close=1.80)
    signals_t1 = strategy.on_bar(bar_t1)

    assert len(signals_t1) == 1
    assert signals_t1[0].direction == Direction.SELL
    assert signals_t1[0].execute_at == "next_open"
