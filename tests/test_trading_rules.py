"""
交易规则回归测试
"""
from datetime import date

from backtest.rules import TradingRules
from strategy.base import BarData, Direction, Signal


def make_bar():
    return BarData(
        code="000001",
        trade_date=date(2026, 1, 6),
        open=10.0,
        high=10.2,
        low=9.8,
        close=10.0,
        pre_close=10.0,
        volume=1_000_000,
        amount=10_000_000.0,
    )


def test_validate_order_rejects_invalid_partial_sell_odd_lot():
    signal = Signal(
        code="000001",
        direction=Direction.SELL,
        trade_date=date(2026, 1, 6),
        price=10.0,
        volume=250,
    )

    valid, reason = TradingRules.validate_order(
        signal=signal,
        bar=make_bar(),
        available_cash=0.0,
        position_volume=350,
        position_available=350,
    )

    assert valid is False
    assert "卖出数量不合法" in reason


def test_validate_order_allows_selling_all_remaining_odd_lot():
    signal = Signal(
        code="000001",
        direction=Direction.SELL,
        trade_date=date(2026, 1, 6),
        price=10.0,
        volume=150,
    )

    valid, reason = TradingRules.validate_order(
        signal=signal,
        bar=make_bar(),
        available_cash=0.0,
        position_volume=150,
        position_available=150,
    )

    assert valid is True
    assert reason == "通过"
