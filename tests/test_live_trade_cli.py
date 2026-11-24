"""
run_live_trade CLI 辅助逻辑测试
"""
from datetime import date
from types import SimpleNamespace

import pytest

from scripts.run_live_trade import build_broker_check_request


def make_args(**overrides):
    defaults = {
        "check_order_code": None,
        "check_order_price": None,
        "check_order_volume": None,
        "check_order_direction": "BUY",
        "check_order_reason": "broker-check",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_build_broker_check_request_returns_none_in_read_only_mode():
    request = build_broker_check_request(
        args=make_args(),
        instance_id="overnight_long:test",
        strategy_key="overnight_long",
        run_date=date(2026, 1, 5),
    )

    assert request is None


def test_build_broker_check_request_requires_complete_limit_order_args():
    with pytest.raises(ValueError, match="参数不完整"):
        build_broker_check_request(
            args=make_args(check_order_code="513090"),
            instance_id="overnight_long:test",
            strategy_key="overnight_long",
            run_date=date(2026, 1, 5),
        )


def test_build_broker_check_request_builds_explicit_limit_order():
    request = build_broker_check_request(
        args=make_args(
            check_order_code="513090",
            check_order_price=1.01,
            check_order_volume=100,
            check_order_direction="SELL",
            check_order_reason="manual-check",
        ),
        instance_id="overnight_long:test",
        strategy_key="overnight_long",
        run_date=date(2026, 1, 5),
    )

    assert request is not None
    assert request.code == "513090"
    assert request.direction.value == "SELL"
    assert request.price == 1.01
    assert request.volume == 100
    assert request.reason == "manual-check"
