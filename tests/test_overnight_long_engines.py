"""
overnight_long 引擎级回归测试

锁定用户目标语义：
- 回测：T 日 close 买入，T+1 日 open 卖出
- 模拟盘：T 日 close 买入后生成 T+1 open 的 pending SELL
"""
from datetime import date

import pandas as pd

from backtest.engine import BacktestEngine
from config import DatabaseConfig
from data.models import init_db
from data.storage.repository import PaperRepository
from strategy.technical.overnight_long import OvernightLongStrategy
from trading.paper_engine import PaperEngine


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
            {
                "trade_date": date(2026, 1, 7),
                "open": 1.03,
                "high": 1.05,
                "low": 1.00,
                "close": 1.01,
                "pre_close": 1.02,
                "volume": 1_050_000,
                "amount": 1_060_500.0,
                "turnover": 0.0,
                "pct_change": -0.98,
            },
        ]
    }


def test_backtest_executes_close_buy_then_next_day_open_sell():
    strategy = OvernightLongStrategy()
    engine = BacktestEngine(
        strategy=strategy,
        stock_codes=["513090"],
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 6),
        initial_capital=10_000.0,
        slippage_rate=0.0,
    )
    engine.repo = FakeStockRepository(make_bars())

    result = engine.run()
    trades = result.get_trades_df()

    assert len(trades) == 2

    first = trades.iloc[0]
    second = trades.iloc[1]

    assert first["action"] == "建仓"
    assert first["buy_price"] == 1.05
    assert pd.isna(first["sell_price"])

    assert second["action"] == "换仓"
    assert second["sell_price"] == 1.08
    assert second["buy_price"] == 1.02
    assert second["holding_days"] == 1

    # metrics 不应再因为 direction 字段缺失而把交易次数统计成 0
    assert result.metrics.total_trades == 1
    assert result.metrics.win_count == 1


def test_paper_engine_creates_next_day_open_sell_for_close_buy(tmp_path, monkeypatch):
    db_path = tmp_path / "paper_overnight_long.db"
    monkeypatch.setattr(DatabaseConfig, "engine", "sqlite")
    monkeypatch.setattr(DatabaseConfig, "sqlite_url", f"sqlite:///{db_path}")
    init_db()

    fake_repo = FakeStockRepository(make_bars())

    engine_day1 = PaperEngine(
        strategy=OvernightLongStrategy(),
        stock_codes=["513090"],
        initial_capital=10_000.0,
        run_date=date(2026, 1, 5),
    )
    engine_day1._repo = fake_repo
    summary_day1 = engine_day1.run_daily()

    repo = PaperRepository()
    day1_orders = repo.get_order_history("overnight_long")
    pending_day2 = repo.get_pending_orders("overnight_long", date(2026, 1, 6))

    assert summary_day1["orders_filled"] == 1
    assert summary_day1["pending_for_tomorrow"] == 1
    assert summary_day1["position_count"] == 1
    assert len(pending_day2) == 1
    assert pending_day2[0].direction == "SELL"
    assert pending_day2[0].req_volume == 9000

    filled_day1_buys = [
        o for o in day1_orders
        if o.direction == "BUY" and o.status == "filled" and o.execute_date == date(2026, 1, 5)
    ]
    assert len(filled_day1_buys) == 1
    assert filled_day1_buys[0].filled_price == 1.05

    engine_day2 = PaperEngine(
        strategy=OvernightLongStrategy(),
        stock_codes=["513090"],
        initial_capital=10_000.0,
        run_date=date(2026, 1, 6),
    )
    engine_day2._repo = fake_repo
    summary_day2 = engine_day2.run_daily()

    day2_orders = repo.get_order_history("overnight_long")
    filled_day2_sells = [
        o for o in day2_orders
        if o.direction == "SELL" and o.status == "filled" and o.execute_date == date(2026, 1, 6)
    ]
    pending_day3 = repo.get_pending_orders("overnight_long", date(2026, 1, 7))

    assert summary_day2["orders_filled"] == 2
    assert summary_day2["pending_for_tomorrow"] == 1
    assert summary_day2["position_count"] == 1
    assert len(filled_day2_sells) == 1
    assert filled_day2_sells[0].filled_price == 1.08
    assert len(pending_day3) == 1
    assert pending_day3[0].direction == "SELL"
