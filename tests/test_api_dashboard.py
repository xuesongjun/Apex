"""
Dashboard API 路由逻辑测试

说明：
- 当前环境下 `httpx 0.28.1` + FastAPI/Starlette 组合会导致 ASGI 测试链不稳定卡住
- 仓库已通过 `requirements.txt` 收紧到 `httpx<0.28`
- 在开发环境按新依赖重建之前，这里先锁路由逻辑本身，保证回归稳定
"""
from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.main import health
from api.routers.dashboard import get_dashboard, list_accounts


class FakePaperRepository:
    def __init__(self):
        self._accounts = [
            SimpleNamespace(
                strategy_name="overnight_long:abcd1234",
                initial_capital=100000.0,
                cash=20000.0,
                total_commission=123.45,
                total_tax=0.0,
                stock_codes="",
                updated_at=datetime(2026, 4, 24, 10, 0, 0),
                created_at=datetime(2026, 4, 23, 10, 0, 0),
            )
        ]
        self._positions = {
            "overnight_long:abcd1234": [
                SimpleNamespace(
                    code="513090",
                    volume=9000,
                    available=9000,
                    cost_price=1.05,
                    current_price=1.08,
                    buy_date=date(2026, 4, 23),
                )
            ]
        }
        self._orders = {
            "overnight_long:abcd1234": [
                SimpleNamespace(
                    order_id="o1",
                    code="513090",
                    direction="SELL",
                    req_volume=9000,
                    execute_date=date(2026, 4, 25),
                    signal_date=date(2026, 4, 24),
                    status="pending",
                    reason="test-order",
                ),
                SimpleNamespace(
                    order_id="o2",
                    code="513090",
                    direction="BUY",
                    req_volume=9000,
                    execute_date=date(2026, 4, 24),
                    signal_date=date(2026, 4, 24),
                    status="filled",
                    reason="filled-order",
                ),
            ]
        }
        self._nav = {
            "overnight_long:abcd1234": [
                SimpleNamespace(
                    trade_date=date(2026, 4, 23),
                    total_equity=100500.0,
                    cash=25000.0,
                    market_value=75500.0,
                    nav=1.005,
                    daily_pnl=500.0,
                ),
                SimpleNamespace(
                    trade_date=date(2026, 4, 24),
                    total_equity=101200.0,
                    cash=20000.0,
                    market_value=81200.0,
                    nav=1.012,
                    daily_pnl=700.0,
                ),
            ]
        }

    def list_paper_accounts(self):
        return self._accounts

    def get_paper_positions(self, strategy_name: str):
        return self._positions.get(strategy_name, [])

    def get_paper_account(self, strategy_name: str):
        return next((a for a in self._accounts if a.strategy_name == strategy_name), None)

    def get_order_history(self, strategy_name: str, start_date=None, end_date=None):
        return self._orders.get(strategy_name, [])

    def get_nav_series(self, strategy_name: str, start_date=None, end_date=None):
        return self._nav.get(strategy_name, [])


class FakeLiveRepository:
    def __init__(self):
        self._accounts = [
            SimpleNamespace(
                instance_id="overnight_long:live1234",
                strategy_key="overnight_long",
                initial_capital=100000.0,
                cash=30000.0,
                total_equity=101200.0,
                broker_provider="qmt",
                broker_account_id="demo-account",
                stock_codes="",
                status="ready",
                updated_at=datetime(2026, 4, 24, 11, 0, 0),
                created_at=datetime(2026, 4, 23, 11, 0, 0),
            )
        ]
        self._positions = {
            "overnight_long:live1234": [
                SimpleNamespace(
                    code="513090",
                    volume=9000,
                    available=0,
                    cost_price=1.05,
                    current_price=1.08,
                )
            ]
        }
        self._orders = {
            "overnight_long:live1234": [
                SimpleNamespace(
                    order_id="l1",
                    broker_order_id="B-1",
                    code="513090",
                    direction="BUY",
                    signal_date=date(2026, 4, 24),
                    planned_execute_date=date(2026, 4, 24),
                    execute_at="close",
                    req_price=1.05,
                    req_volume=9000,
                    status="submitted",
                    filled_price=0.0,
                    filled_volume=0,
                    commission=0.0,
                    reason="submit-buy",
                    created_at=datetime(2026, 4, 24, 14, 55, 0),
                    updated_at=datetime(2026, 4, 24, 14, 55, 0),
                ),
                SimpleNamespace(
                    order_id="l2",
                    broker_order_id="",
                    code="513090",
                    direction="SELL",
                    signal_date=date(2026, 4, 24),
                    planned_execute_date=date(2026, 4, 25),
                    execute_at="next_open",
                    req_price=1.08,
                    req_volume=9000,
                    status="planned",
                    filled_price=0.0,
                    filled_volume=0,
                    commission=0.0,
                    reason="planned-sell",
                    created_at=datetime(2026, 4, 24, 14, 55, 1),
                    updated_at=datetime(2026, 4, 24, 14, 55, 1),
                ),
                SimpleNamespace(
                    order_id="l3",
                    broker_order_id="B-3",
                    code="513090",
                    direction="BUY",
                    signal_date=date(2026, 4, 23),
                    planned_execute_date=date(2026, 4, 23),
                    execute_at="close",
                    req_price=1.02,
                    req_volume=10000,
                    status="rejected",
                    filled_price=0.0,
                    filled_volume=0,
                    commission=0.0,
                    reason="risk-rejected",
                    created_at=datetime(2026, 4, 23, 14, 55, 0),
                    updated_at=datetime(2026, 4, 23, 14, 55, 0),
                ),
            ]
        }

    def list_live_accounts(self):
        return self._accounts

    def get_live_account(self, instance_id: str):
        return next((a for a in self._accounts if a.instance_id == instance_id), None)

    def get_live_positions(self, instance_id: str):
        return self._positions.get(instance_id, [])

    def get_live_orders(self, instance_id: str, status=None, start_date=None, end_date=None):
        rows = self._orders.get(instance_id, [])
        if status:
            rows = [row for row in rows if row.status == status]
        return rows


def test_health_returns_ok():
    assert health() == {"status": "ok"}


def test_list_accounts_uses_position_fallback_when_stock_codes_missing():
    payload = list_accounts(FakePaperRepository(), FakeLiveRepository(), mode="paper")

    assert len(payload) == 1
    assert payload[0].account_id == "overnight_long:abcd1234"
    assert payload[0].strategy_key == "overnight_long"
    assert payload[0].stock_codes == ["513090"]
    assert payload[0].mode == "paper"


def test_list_accounts_returns_live_accounts_when_mode_live():
    payload = list_accounts(FakePaperRepository(), FakeLiveRepository(), mode="live")

    assert len(payload) == 1
    assert payload[0].account_id == "overnight_long:live1234"
    assert payload[0].strategy_key == "overnight_long"
    assert payload[0].stock_codes == ["513090"]
    assert payload[0].mode == "live"


def test_get_dashboard_returns_overview_positions_orders_and_nav():
    payload = get_dashboard(
        paper_repo=FakePaperRepository(),
        live_repo=FakeLiveRepository(),
        account_id="overnight_long:abcd1234",
        mode="paper",
        days=1,
    )

    assert payload.mode == "paper"
    assert payload.selected_account_id == "overnight_long:abcd1234"
    assert payload.overview is not None
    assert payload.overview.strategy_key == "overnight_long"
    assert payload.overview.position_count == 1
    assert payload.overview.pending_count == 1
    assert len(payload.positions) == 1
    assert payload.positions[0].code == "513090"
    assert len(payload.pending_orders) == 1
    assert payload.pending_orders[0].status == "pending"
    assert payload.orders == []
    assert len(payload.nav) == 1
    assert payload.nav[0].trade_date == date(2026, 4, 24)


def test_get_dashboard_returns_live_overview_positions_and_orders():
    payload = get_dashboard(
        paper_repo=FakePaperRepository(),
        live_repo=FakeLiveRepository(),
        account_id="overnight_long:live1234",
        mode="live",
        days=60,
    )

    assert payload.mode == "live"
    assert payload.selected_account_id == "overnight_long:live1234"
    assert payload.overview is not None
    assert payload.overview.strategy_key == "overnight_long"
    assert payload.overview.broker_provider == "qmt"
    assert payload.overview.account_status == "ready"
    assert payload.overview.pending_count == 2
    assert len(payload.positions) == 1
    assert payload.positions[0].code == "513090"
    assert payload.pending_orders == []
    assert len(payload.orders) == 3
    assert payload.orders[0].status == "submitted"
    assert payload.orders[1].status == "planned"
    assert payload.orders[2].status == "rejected"
    assert payload.nav == []


def test_get_dashboard_raises_404_for_unknown_account():
    with pytest.raises(HTTPException) as exc:
        get_dashboard(
            paper_repo=FakePaperRepository(),
            live_repo=FakeLiveRepository(),
            account_id="missing-account",
            mode="paper",
            days=60,
        )

    assert exc.value.status_code == 404
    assert "账户不存在" in str(exc.value.detail)
