"""
overnight_long 策略单元测试（模式 B：连续隔夜）

覆盖所有信号分支，构造 BarData 直接喂给策略，不依赖数据库/引擎。
"""
from datetime import date

import pytest

from strategy.base import BarData, Direction, Position
from strategy.technical.overnight_long import OvernightLongStrategy


def make_bar(code="513090", trade_date=None, open_=None, close=1.0, pre_close=1.0):
    """构造一根 BarData 便于测试，open 缺省等于 pre_close"""
    td = trade_date or date(2026, 1, 5)
    o = open_ if open_ is not None else pre_close
    return BarData(
        code=code,
        trade_date=td,
        open=o,
        high=max(o, close, pre_close),
        low=min(o, close, pre_close),
        close=close,
        pre_close=pre_close,
        volume=1_000_000,
        amount=close * 1_000_000,
    )


def make_position(code="513090", volume=10000, available=10000, buy_date=None):
    return Position(
        code=code,
        volume=volume,
        available=available,
        cost_price=1.80,
        current_price=1.80,
        buy_date=buy_date or date(2026, 1, 4),
    )


def test_empty_position_generates_buy_signal():
    """空仓 + 默认参数 → 产生 1 个 BUY 信号，execute_at='close'"""
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


def test_held_position_generates_sell_and_buy():
    """
    有可卖仓位 + 非一字跌停 → 产生 2 个信号：[SELL @ next_open, BUY @ close]
    模式 B 核心行为：同一根 bar 先卖再买，实现连续隔夜
    """
    strategy = OvernightLongStrategy()
    strategy._sync_account(
        positions={"513090": make_position()},
        cash=0.0,
        total_value=18000.0,
    )

    bar = make_bar(close=1.85, pre_close=1.80)
    signals = strategy.on_bar(bar)

    assert len(signals) == 2
    assert signals[0].direction == Direction.SELL
    assert signals[0].execute_at == "next_open"
    assert signals[1].direction == Direction.BUY
    assert signals[1].execute_at == "close"


def test_position_with_zero_available_skips_sell():
    """T+1 未解冻（available=0）→ 不产 SELL；has_position=True 阻断 BUY → 无信号"""
    strategy = OvernightLongStrategy()
    strategy._sync_account(
        positions={"513090": make_position(available=0, buy_date=date(2026, 1, 5))},
        cash=0.0,
        total_value=18000.0,
    )

    bar = make_bar(close=1.85, pre_close=1.80)
    signals = strategy.on_bar(bar)

    assert len(signals) == 0


def test_filters_disabled_by_default_even_on_big_rise():
    """默认两参数 None → 当日涨 5% 也产 BUY（过滤未生效）"""
    strategy = OvernightLongStrategy()
    bar = make_bar(close=1.05, pre_close=1.00)
    signals = strategy.on_bar(bar)

    assert len(signals) == 1
    assert signals[0].direction == Direction.BUY


def test_min_drop_pct_blocks_when_drop_insufficient():
    """
    持仓 + min_drop_pct=3 + 当日跌 2% → SELL 仍产（过滤不作用于卖），BUY 被过滤
    验证：过滤参数只管 BUY 分支
    """
    strategy = OvernightLongStrategy(config={"min_drop_pct": 3.0})
    strategy._sync_account(
        positions={"513090": make_position()},
        cash=0.0,
        total_value=18000.0,
    )
    bar = make_bar(close=0.98, pre_close=1.00)

    signals = strategy.on_bar(bar)

    assert len(signals) == 1
    assert signals[0].direction == Direction.SELL


def test_min_drop_pct_allows_when_drop_sufficient():
    """空仓 + min_drop_pct=3 + 当日跌 5% → 产 BUY"""
    strategy = OvernightLongStrategy(config={"min_drop_pct": 3.0})
    bar = make_bar(close=0.95, pre_close=1.00)
    signals = strategy.on_bar(bar)
    assert len(signals) == 1
    assert signals[0].direction == Direction.BUY


def test_max_rise_pct_blocks_when_rise_exceeds():
    """
    持仓 + max_rise_pct=3 + 当日涨 5% → SELL 仍产，BUY 被过滤
    """
    strategy = OvernightLongStrategy(config={"max_rise_pct": 3.0})
    strategy._sync_account(
        positions={"513090": make_position()},
        cash=0.0,
        total_value=18000.0,
    )
    bar = make_bar(close=1.05, pre_close=1.00)

    signals = strategy.on_bar(bar)

    assert len(signals) == 1
    assert signals[0].direction == Direction.SELL


def test_two_day_cycle_continuous_overnight():
    """
    模式 B 两日循环：
      T 日空仓 → 产 BUY
      T+1 日持仓（已解冻）→ 产 SELL + BUY（连续隔夜）
    """
    strategy = OvernightLongStrategy()

    # T 日：空仓
    bar_t = make_bar(trade_date=date(2026, 1, 5), close=1.80, pre_close=1.82)
    signals_t = strategy.on_bar(bar_t)
    assert len(signals_t) == 1
    assert signals_t[0].direction == Direction.BUY

    # T+1 日：模拟已解冻持仓
    strategy._sync_account(
        positions={"513090": make_position(buy_date=date(2026, 1, 5))},
        cash=0.0,
        total_value=18000.0,
    )

    bar_t1 = make_bar(trade_date=date(2026, 1, 6), close=1.85, pre_close=1.80)
    signals_t1 = strategy.on_bar(bar_t1)

    assert len(signals_t1) == 2
    assert signals_t1[0].direction == Direction.SELL
    assert signals_t1[1].direction == Direction.BUY


def test_one_limit_down_blocks_both_signals():
    """
    一字跌停：bar.open 正好触及跌停价 → SELL 被阻塞（挂不出去）
    同时 BUY 也被阻塞（资金仍被持仓占用）→ 无信号
    """
    strategy = OvernightLongStrategy(config={"limit_pct": 0.10})
    strategy._sync_account(
        positions={"513090": make_position()},
        cash=0.0,
        total_value=18000.0,
    )

    # pre_close=1.00, 跌停价 = 0.900
    bar = make_bar(open_=0.900, close=0.900, pre_close=1.00)

    signals = strategy.on_bar(bar)

    assert len(signals) == 0


def test_limit_down_recovery_next_day():
    """
    被套次日开盘回升（非一字跌停）→ 恢复连续隔夜：SELL + BUY 各 1 条
    """
    strategy = OvernightLongStrategy(config={"limit_pct": 0.10})
    strategy._sync_account(
        positions={"513090": make_position(buy_date=date(2026, 1, 5))},
        cash=0.0,
        total_value=18000.0,
    )

    # pre_close=0.900（昨日跌停收盘），今日开盘 0.92（未触跌停 0.810）
    bar = make_bar(
        trade_date=date(2026, 1, 7),
        open_=0.92,
        close=0.95,
        pre_close=0.900,
    )

    signals = strategy.on_bar(bar)

    assert len(signals) == 2
    assert signals[0].direction == Direction.SELL
    assert signals[1].direction == Direction.BUY


def test_custom_limit_pct_changes_limit_threshold():
    """
    limit_pct=0.20（创业板 ETF）+ bar.open 跌 15% → 未触跌停（0.80）→ 正常 SELL+BUY
    对比默认 0.10 时 bar.open=0.85 会被判为跌停（跌停价=0.90）
    """
    # 用 0.20 限制：跌停价 = 0.80，open=0.85 未触及
    strategy_20 = OvernightLongStrategy(config={"limit_pct": 0.20})
    strategy_20._sync_account(
        positions={"513090": make_position()},
        cash=0.0,
        total_value=18000.0,
    )
    bar = make_bar(open_=0.85, close=0.85, pre_close=1.00)
    signals_20 = strategy_20.on_bar(bar)
    assert len(signals_20) == 2  # SELL + BUY

    # 对照组：默认 0.10，open=0.85 < 跌停价 0.90 → 一字跌停（或更深）
    strategy_10 = OvernightLongStrategy(config={"limit_pct": 0.10})
    strategy_10._sync_account(
        positions={"513090": make_position()},
        cash=0.0,
        total_value=18000.0,
    )
    signals_10 = strategy_10.on_bar(bar)
    assert len(signals_10) == 0  # SELL 被阻，BUY 也被阻
