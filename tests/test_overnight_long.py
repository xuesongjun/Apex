"""
overnight_long 策略单元测试

覆盖新语义：
- 空仓日：BUY @ close + SELL @ next_open
- 持仓日：SELL @ next_open
- 过滤参数仅作用于 BUY 分支
"""
from datetime import date

from strategy.base import BarData, Direction, Position
from strategy.registry import load_strategy
from strategy.technical.overnight_long import OvernightLongStrategy


def make_bar(code="513090", trade_date=None, open_=None, close=1.0, pre_close=1.0):
    """构造一根 BarData，open 缺省等于 pre_close。"""
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


def test_load_strategy_merges_yaml_defaults():
    """registry 应合并 strategies.yaml 默认参数，而不只用硬编码 default_params。"""
    strategy = load_strategy("overnight_long")

    assert strategy.config["min_drop_pct"] is None
    assert strategy.config["max_rise_pct"] is None
    assert "limit_pct" not in strategy.config


def test_empty_position_generates_buy_and_next_open_sell():
    """空仓 + 默认参数 → 当日 BUY @ close，同时预约明早 SELL @ next_open。"""
    strategy = OvernightLongStrategy()
    bar = make_bar(close=1.80, pre_close=1.82)

    signals = strategy.on_bar(bar)

    assert len(signals) == 2
    assert signals[0].direction == Direction.BUY
    assert signals[0].execute_at == "close"
    assert signals[1].direction == Direction.SELL
    assert signals[1].execute_at == "next_open"


def test_held_position_generates_only_next_open_sell():
    """已有持仓时，只需要预约明早卖出，不应同日再买。"""
    strategy = OvernightLongStrategy()
    strategy._sync_account(
        positions={"513090": make_position()},
        cash=0.0,
        total_value=18000.0,
    )

    bar = make_bar(close=1.85, pre_close=1.80)
    signals = strategy.on_bar(bar)

    assert len(signals) == 1
    assert signals[0].direction == Direction.SELL
    assert signals[0].execute_at == "next_open"


def test_position_with_zero_available_still_schedules_next_open_sell():
    """即便 available=0，只要今晚仍会持仓，也应预约明早卖出。"""
    strategy = OvernightLongStrategy()
    strategy._sync_account(
        positions={"513090": make_position(available=0, buy_date=date(2026, 1, 5))},
        cash=0.0,
        total_value=18000.0,
    )

    bar = make_bar(close=1.85, pre_close=1.80)
    signals = strategy.on_bar(bar)

    assert len(signals) == 1
    assert signals[0].direction == Direction.SELL
    assert signals[0].execute_at == "next_open"


def test_filters_disabled_by_default_even_on_big_rise():
    """默认过滤关闭：空仓日即使大涨，也会 BUY + 预约 SELL。"""
    strategy = OvernightLongStrategy()
    bar = make_bar(close=1.05, pre_close=1.00)
    signals = strategy.on_bar(bar)

    assert len(signals) == 2
    assert signals[0].direction == Direction.BUY
    assert signals[1].direction == Direction.SELL


def test_min_drop_pct_blocks_flat_entry():
    """空仓 + 跌幅不足 → 不买，也不应预约明早卖出。"""
    strategy = OvernightLongStrategy(config={"min_drop_pct": 3.0})
    bar = make_bar(close=0.98, pre_close=1.00)

    signals = strategy.on_bar(bar)

    assert signals == []


def test_min_drop_pct_keeps_sell_when_holding():
    """过滤参数只影响 BUY 分支，持仓出场不受影响。"""
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


def test_min_drop_pct_allows_flat_entry_when_drop_sufficient():
    """空仓 + 跌幅满足阈值 → BUY + 预约 SELL。"""
    strategy = OvernightLongStrategy(config={"min_drop_pct": 3.0})
    bar = make_bar(close=0.95, pre_close=1.00)

    signals = strategy.on_bar(bar)

    assert len(signals) == 2
    assert signals[0].direction == Direction.BUY
    assert signals[1].direction == Direction.SELL


def test_max_rise_pct_blocks_flat_entry():
    """空仓 + 涨幅超阈值 → 不买，也不应生成 SELL。"""
    strategy = OvernightLongStrategy(config={"max_rise_pct": 3.0})
    bar = make_bar(close=1.05, pre_close=1.00)

    signals = strategy.on_bar(bar)

    assert signals == []


def test_max_rise_pct_keeps_sell_when_holding():
    """持仓状态下，即使涨幅超阈值，仍需预约明早卖出。"""
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
