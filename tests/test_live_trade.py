"""
Phase 7A 实盘交易基座测试
"""
from datetime import date

import pandas as pd

from config import DatabaseConfig
from data.models import init_db
from data.storage.repository import LiveRepository
from strategy.base import Direction
from strategy.technical.overnight_long import OvernightLongStrategy
from trading.broker.base import BrokerOrderRequest
from trading.broker.dry_run import DryRunBroker
from trading.live_engine import LiveEngine


class FakeStockRepository:
    def __init__(self, bars_by_code: dict[str, list[dict]]):
        self._bars_by_code = bars_by_code
        self._trade_dates = {
            row["trade_date"]
            for rows in bars_by_code.values()
            for row in rows
        }

    def get_daily_bars(self, code: str, start_date: date, end_date: date) -> pd.DataFrame:
        rows = [
            row
            for row in self._bars_by_code.get(code, [])
            if start_date <= row["trade_date"] <= end_date
        ]
        return pd.DataFrame(rows)

    def is_trade_date(self, check_date: date) -> bool:
        return check_date in self._trade_dates


def make_bars() -> dict[str, list[dict]]:
    return {
        "513090": [
            {
                "trade_date": date(2026, 1, 5),
                "open": 1.00,
                "high": 1.06,
                "low": 0.99,
                "close": 1.05,
                "pre_close": 1.00,
                "volume": 1_000_000,
                "amount": 1_050_000.0,
                "turnover": 0.0,
                "pct_change": 5.0,
            },
            {
                "trade_date": date(2026, 1, 6),
                "open": 1.08,
                "high": 1.10,
                "low": 1.00,
                "close": 1.02,
                "pre_close": 1.05,
                "volume": 1_100_000,
                "amount": 1_122_000.0,
                "turnover": 0.0,
                "pct_change": -2.86,
            },
        ]
    }


def setup_temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "live_trade.db"
    monkeypatch.setattr(DatabaseConfig, "engine", "sqlite")
    monkeypatch.setattr(DatabaseConfig, "sqlite_url", f"sqlite:///{db_path}")
    init_db()


def test_dry_run_broker_submit_order_persists_live_order(tmp_path, monkeypatch):
    setup_temp_db(tmp_path, monkeypatch)

    broker = DryRunBroker(
        instance_id="overnight_long:test",
        strategy_key="overnight_long",
        stock_codes=["513090"],
        initial_capital=10_000.0,
    )
    request = BrokerOrderRequest(
        order_id="test-order-1",
        instance_id="overnight_long:test",
        strategy_key="overnight_long",
        code="513090",
        direction=Direction.BUY,
        signal_date=date(2026, 1, 5),
        execute_at="close",
        planned_execute_date=date(2026, 1, 5),
        price=1.05,
        volume=9000,
        reason="unit-test",
    )

    order = broker.submit_order(request)

    repo = LiveRepository()
    live_orders = repo.get_live_orders("overnight_long:test")

    assert order.status == "submitted"
    assert len(live_orders) == 1
    assert live_orders[0].order_id == "test-order-1"
    assert live_orders[0].status == "submitted"
    assert live_orders[0].req_volume == 9000


def test_live_engine_builds_buy_close_and_sell_next_open_for_overnight_long(tmp_path, monkeypatch):
    setup_temp_db(tmp_path, monkeypatch)

    broker = DryRunBroker(
        instance_id="overnight_long:test",
        strategy_key="overnight_long",
        stock_codes=["513090"],
        initial_capital=10_000.0,
    )
    engine = LiveEngine(
        strategy=OvernightLongStrategy(),
        strategy_key="overnight_long",
        stock_codes=["513090"],
        broker=broker,
        instance_id="overnight_long:test",
        run_date=date(2026, 1, 5),
    )
    engine._repo = FakeStockRepository(make_bars())

    summary = engine.run_daily()

    repo = LiveRepository()
    live_orders = repo.get_live_orders("overnight_long:test")
    assert summary["signals_generated"] == 2
    assert summary["orders_built"] == 2
    assert summary["orders_submitted"] == 2
    assert len(live_orders) == 2

    by_execute_at = {row.execute_at: row for row in live_orders}
    assert by_execute_at["close"].direction == "BUY"
    assert by_execute_at["close"].req_price == 1.05
    assert by_execute_at["close"].req_volume == 9000
    assert by_execute_at["close"].status == "submitted"

    assert by_execute_at["next_open"].direction == "SELL"
    assert by_execute_at["next_open"].planned_execute_date == date(2026, 1, 6)
    assert by_execute_at["next_open"].req_volume == 9000
    assert by_execute_at["next_open"].status == "planned"
