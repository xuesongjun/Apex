"""
live rehearsal / validation 辅助逻辑测试
"""
from __future__ import annotations

import sys
from datetime import date

import pandas as pd

from config import DatabaseConfig
from data.models import init_db
from data.storage.repository import LiveRepository, PaperRepository, StockRepository
from scripts import run_live_validation as validation_cli
from trading.live_validation import (
    build_validation_ids,
    summarize_validation_day,
    summarize_validation_report,
)


def setup_temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "live_validation.db"
    monkeypatch.setattr(DatabaseConfig, "engine", "sqlite")
    monkeypatch.setattr(DatabaseConfig, "sqlite_url", f"sqlite:///{db_path}")
    init_db()


def test_build_validation_ids_is_stable_and_short():
    ids_a = build_validation_ids(
        strategy_key="overnight_long",
        codes=["513090"],
        params={"min_drop_pct": 3.0},
        tag="small-cap",
    )
    ids_b = build_validation_ids(
        strategy_key="overnight_long",
        codes=["513090"],
        params={"min_drop_pct": 3.0},
        tag="small-cap",
    )

    assert ids_a == ids_b
    assert len(ids_a.paper_account_id) <= 50
    assert len(ids_a.live_instance_id) <= 64


def test_summarize_validation_day_and_report():
    row_1 = summarize_validation_day(
        trade_date=date(2026, 1, 5),
        paper_summary={
            "signals_generated": 2,
            "orders_filled": 1,
            "pending_for_tomorrow": 1,
            "orders_rejected": 0,
            "orders_cancelled": 0,
            "total_equity": 10_100.0,
        },
        live_summary={
            "signals_generated": 2,
            "orders_built": 2,
            "orders_submitted": 2,
            "planned_orders_activated": 0,
            "orders_risk_rejected": 0,
            "orders_broker_rejected": 0,
            "total_equity": 10_000.0,
        },
    )
    row_2 = summarize_validation_day(
        trade_date=date(2026, 1, 6),
        paper_summary={
            "signals_generated": 1,
            "orders_filled": 2,
            "pending_for_tomorrow": 0,
            "orders_rejected": 1,
            "orders_cancelled": 0,
            "total_equity": 10_050.0,
        },
        live_summary={
            "signals_generated": 2,
            "orders_built": 1,
            "orders_submitted": 1,
            "planned_orders_activated": 1,
            "orders_risk_rejected": 1,
            "orders_broker_rejected": 0,
            "total_equity": 10_000.0,
        },
    )

    report = summarize_validation_report(
        rows=[row_1, row_2],
        paper_account_id="paper-id",
        live_instance_id="live-id",
    )

    assert row_1["signal_match"] is True
    assert row_1["has_issue"] is False
    assert row_2["signal_match"] is False
    assert row_2["has_issue"] is True

    assert report["trade_days"] == 2
    assert report["signal_match_days"] == 1
    assert len(report["issue_days"]) == 1
    assert report["paper_orders_filled_total"] == 3
    assert report["live_orders_built_total"] == 3
    assert report["live_planned_activated_total"] == 1
    assert report["paper_rejections_total"] == 1
    assert report["live_rejections_total"] == 1
    assert report["final_paper_total_equity"] == 10_050.0


def test_skipped_days_are_excluded_from_signal_comparison():
    both_skipped = summarize_validation_day(date(2026, 1, 5), {}, None)
    paper_only = summarize_validation_day(
        date(2026, 1, 6), {"signals_generated": 2, "total_equity": 10_500.0}, {}
    )
    live_only = summarize_validation_day(
        date(2026, 1, 7), None, {"signals_generated": 3, "total_equity": 10_200.0}
    )

    assert (both_skipped["paper_ran"], both_skipped["live_ran"]) == (False, False)
    assert (paper_only["paper_ran"], paper_only["live_ran"]) == (True, False)
    assert (live_only["paper_ran"], live_only["live_ran"]) == (False, True)
    assert paper_only["paper_signals"] == 2
    assert live_only["live_signals"] == 3

    rows = [both_skipped, paper_only, live_only]
    assert all(row["signal_match"] is None for row in rows)
    report = summarize_validation_report(rows, "paper-id", "live-id")

    assert report["trade_days"] == 3
    assert report["comparable_days"] == 0
    assert report["signal_match_days"] == 0
    assert report["issue_days"] == rows
    assert report["final_paper_total_equity"] == 10_500.0
    assert report["final_live_total_equity"] == 10_200.0


def test_report_distinguishes_zero_signals_and_equity_from_skipped_values():
    zero = {"signals_generated": 0, "total_equity": 0.0}
    matched = summarize_validation_day(date(2026, 1, 5), zero, zero)
    mismatched = summarize_validation_day(
        date(2026, 1, 6), {"signals_generated": 1, "total_equity": 0.0}, zero
    )
    paper_only = summarize_validation_day(date(2026, 1, 7), zero, None)
    report = summarize_validation_report([matched, mismatched, paper_only], "paper-id", "live-id")

    assert matched["signal_match"] is True
    assert matched["has_issue"] is False
    assert mismatched["signal_match"] is False
    assert report["trade_days"] == 3
    assert report["comparable_days"] == 2
    assert report["signal_match_days"] == 1
    assert report["issue_days"] == [mismatched, paper_only]
    assert report["final_paper_total_equity"] == 0.0
    assert report["final_live_total_equity"] == 0.0

    partial_report = summarize_validation_report([paper_only], "paper-id", "live-id")
    assert partial_report["final_paper_total_equity"] == 0.0
    assert partial_report["final_live_total_equity"] is None


def test_matched_signals_with_order_failures_are_issue_days():
    paper_cancelled = summarize_validation_day(
        date(2026, 1, 5), {"signals_generated": 0, "orders_cancelled": 1}, {"signals_generated": 0}
    )
    live_failed = summarize_validation_day(
        date(2026, 1, 6), {"signals_generated": 0}, {"signals_generated": 0, "planned_orders_failed": 1}
    )
    report = summarize_validation_report([paper_cancelled, live_failed], "paper-id", "live-id")

    assert report["signal_match_days"] == 2
    assert report["issue_days"] == [paper_cancelled, live_failed]
    assert report["paper_rejections_total"] == 1
    assert report["live_planned_failed_total"] == 1


def test_print_report_shows_skipped_side_and_missing_equity(capsys):
    day = date(2026, 1, 5)
    row = summarize_validation_day(day, {"signals_generated": 2, "total_equity": 0.0}, {})
    validation_cli.print_report(
        {
            "strategy_key": "ma_cross",
            "start_date": day,
            "end_date": day,
            "tag": "report-test",
            "paper_account_id": "paper-id",
            "live_instance_id": "live-id",
            "rows": [row],
            "aggregate": summarize_validation_report([row], "paper-id", "live-id"),
        }
    )
    output = capsys.readouterr().out

    assert "交易日数：  1" in output
    assert "可比较日数：0" in output
    assert "信号一致：  无可比较日" in output
    assert "期末 Live 总资产： 无数据" in output
    paper_equity_line = next(line for line in output.splitlines() if "期末 Paper 总资产：" in line)
    assert paper_equity_line.endswith("0.00")
    daily_summary = next(line for line in output.splitlines() if line.startswith(f"  {day}  "))
    assert daily_summary.split()[:4] == [str(day), "2", "跳过", "-"]
    assert f"{day} | Paper=完成 | Live=跳过 | signal_match=不可比较" in output


def test_validation_cli_reports_missing_trade_day(tmp_path, monkeypatch, capsys):
    setup_temp_db(tmp_path, monkeypatch)
    complete_day = date(2026, 1, 5)
    missing_day = date(2026, 1, 6)
    code = "513090"
    stock_repo = StockRepository()
    stock_repo.save_trade_calendar(
        pd.DataFrame({"cal_date": [complete_day, missing_day], "is_open": [True, True]})
    )
    stock_repo.save_daily_bars(
        code,
        pd.DataFrame(
            [{
                "trade_date": complete_day,
                "open": 1.00,
                "high": 1.06,
                "low": 0.99,
                "close": 1.05,
                "pre_close": 1.00,
                "volume": 1_000_000,
                "amount": 1_050_000.0,
            }]
        ),
    )
    monkeypatch.setattr(validation_cli, "setup_logging", lambda: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_live_validation.py",
            "--strategy", "ma_cross",
            "--codes", code,
            "--start", str(complete_day),
            "--end", str(missing_day),
        ],
    )

    validation_cli.main()
    output = capsys.readouterr().out

    assert "交易日数：  2" in output
    assert "可比较日数：1" in output
    assert "信号一致：  1/1" in output
    assert f"{missing_day} | Paper=跳过 | Live=跳过 | signal_match=不可比较" in output
    assert f"{complete_day} | Paper=" not in output
    for account in ("Paper", "Live"):
        equity_line = next(line for line in output.splitlines() if f"期末 {account} 总资产：" in line)
        assert equity_line.endswith("10,000.00")


def test_validation_cleanup_deletes_paper_and_live_state(tmp_path, monkeypatch):
    setup_temp_db(tmp_path, monkeypatch)

    paper_repo = PaperRepository()
    live_repo = LiveRepository()

    paper_repo.create_paper_account("validation:paper", 10_000.0, ["513090"])
    paper_repo.upsert_paper_positions(
        "validation:paper",
        [
            {
                "strategy_name": "validation:paper",
                "code": "513090",
                "volume": 9000,
                "available": 9000,
                "cost_price": 1.05,
                "current_price": 1.08,
                "buy_date": date(2026, 1, 5),
            }
        ],
    )
    paper_repo.save_paper_order(
        {
            "strategy_name": "validation:paper",
            "code": "513090",
            "direction": "BUY",
            "signal_date": date(2026, 1, 5),
            "execute_date": date(2026, 1, 6),
            "status": "pending",
            "req_volume": 9000,
            "reason": "validation",
        }
    )
    paper_repo.save_paper_nav(
        {
            "strategy_name": "validation:paper",
            "trade_date": date(2026, 1, 5),
            "cash": 1000.0,
            "market_value": 9000.0,
            "total_equity": 10_000.0,
            "nav": 1.0,
            "daily_pnl": 0.0,
            "position_count": 1,
        }
    )

    live_repo.create_live_account(
        instance_id="validation:live",
        strategy_key="overnight_long",
        broker_provider="dry_run",
        broker_account_id="VAL",
        initial_capital=10_000.0,
        stock_codes=["513090"],
        cash=10_000.0,
        total_equity=10_000.0,
    )
    live_repo.replace_live_positions(
        "validation:live",
        [
            {
                "instance_id": "validation:live",
                "code": "513090",
                "volume": 9000,
                "available": 0,
                "cost_price": 1.05,
                "current_price": 1.08,
                "source": "broker",
            }
        ],
    )
    live_repo.save_live_order(
        {
            "order_id": "validation-order-1",
            "instance_id": "validation:live",
            "strategy_key": "overnight_long",
            "broker_provider": "dry_run",
            "broker_order_id": "VAL-1",
            "code": "513090",
            "direction": "BUY",
            "signal_date": date(2026, 1, 5),
            "planned_execute_date": date(2026, 1, 5),
            "execute_at": "close",
            "req_price": 1.05,
            "req_volume": 9000,
            "status": "submitted",
            "reason": "validation",
        }
    )

    paper_repo.delete_paper_account_state("validation:paper")
    live_repo.delete_live_instance_state("validation:live")

    assert paper_repo.get_paper_account("validation:paper") is None
    assert paper_repo.get_paper_positions("validation:paper") == []
    assert paper_repo.get_order_history("validation:paper") == []
    assert paper_repo.get_nav_series("validation:paper") == []

    assert live_repo.get_live_account("validation:live") is None
    assert live_repo.get_live_positions("validation:live") == []
    assert live_repo.get_live_orders("validation:live") == []
