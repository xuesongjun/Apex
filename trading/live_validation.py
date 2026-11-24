"""
live rehearsal / validation
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

from data.storage.repository import LiveRepository, PaperRepository, StockRepository
from strategy.registry import load_strategy
from trading.account_id import build_account_id
from trading.broker import DryRunBroker
from trading.live_engine import LiveEngine
from trading.paper_engine import PaperEngine

_VALIDATION_RUN_TIME = time(14, 55)


@dataclass(frozen=True)
class ValidationIds:
    paper_account_id: str
    live_instance_id: str
    tag_digest: str


def build_validation_ids(
    strategy_key: str,
    codes: list[str],
    params: dict[str, Any],
    tag: str,
) -> ValidationIds:
    """
    为 rehearsal 生成和正式账户隔离的稳定 ID。
    """
    base = build_account_id(strategy_key, codes, params)
    digest = hashlib.sha1(tag.encode("utf-8")).hexdigest()[:8]
    return ValidationIds(
        paper_account_id=f"{base}:pv{digest}",
        live_instance_id=f"{base}:lv{digest}",
        tag_digest=digest,
    )


def summarize_validation_day(
    trade_date: date,
    paper_summary: dict | None,
    live_summary: dict | None,
) -> dict:
    paper_ran = bool(paper_summary)
    live_ran = bool(live_summary)
    paper_summary = paper_summary or {}
    live_summary = live_summary or {}

    paper_signals = int(paper_summary.get("signals_generated", 0) or 0)
    live_signals = int(live_summary.get("signals_generated", 0) or 0)
    paper_rejections = int(paper_summary.get("orders_rejected", 0) or 0) + int(
        paper_summary.get("orders_cancelled", 0) or 0
    )
    live_rejections = int(live_summary.get("orders_risk_rejected", 0) or 0) + int(
        live_summary.get("orders_broker_rejected", 0) or 0
    )
    live_planned_failed = int(live_summary.get("planned_orders_failed", 0) or 0)
    signal_match = (paper_signals == live_signals) if paper_ran and live_ran else None

    return {
        "trade_date": trade_date,
        "paper_ran": paper_ran,
        "live_ran": live_ran,
        "paper_signals": paper_signals,
        "live_signals": live_signals,
        "signal_match": signal_match,
        "paper_orders_filled": int(paper_summary.get("orders_filled", 0) or 0),
        "paper_pending_for_tomorrow": int(paper_summary.get("pending_for_tomorrow", 0) or 0),
        "paper_rejections": paper_rejections,
        "live_orders_built": int(live_summary.get("orders_built", 0) or 0),
        "live_orders_submitted": int(live_summary.get("orders_submitted", 0) or 0),
        "live_planned_activated": int(live_summary.get("planned_orders_activated", 0) or 0),
        "live_planned_failed": live_planned_failed,
        "live_rejections": live_rejections,
        "paper_total_equity": float(paper_summary.get("total_equity", 0.0) or 0.0),
        "live_total_equity": float(live_summary.get("total_equity", 0.0) or 0.0),
        "has_issue": (
            signal_match is not True
            or paper_rejections > 0
            or live_rejections > 0
            or live_planned_failed > 0
        ),
    }


def summarize_validation_report(
    rows: list[dict],
    paper_account_id: str,
    live_instance_id: str,
) -> dict:
    comparable_days = sum(row["signal_match"] is not None for row in rows)
    signal_match_days = sum(row["signal_match"] is True for row in rows)
    issue_days = [row for row in rows if row["has_issue"]]
    final_paper_equity = next(
        (row["paper_total_equity"] for row in reversed(rows) if row["paper_ran"]),
        None,
    )
    final_live_equity = next(
        (row["live_total_equity"] for row in reversed(rows) if row["live_ran"]),
        None,
    )

    return {
        "trade_days": len(rows),
        "comparable_days": comparable_days,
        "signal_match_days": signal_match_days,
        "issue_days": issue_days,
        "paper_account_id": paper_account_id,
        "live_instance_id": live_instance_id,
        "paper_orders_filled_total": sum(row["paper_orders_filled"] for row in rows),
        "paper_pending_total": sum(row["paper_pending_for_tomorrow"] for row in rows),
        "paper_rejections_total": sum(row["paper_rejections"] for row in rows),
        "live_orders_built_total": sum(row["live_orders_built"] for row in rows),
        "live_orders_submitted_total": sum(row["live_orders_submitted"] for row in rows),
        "live_planned_activated_total": sum(row["live_planned_activated"] for row in rows),
        "live_planned_failed_total": sum(row["live_planned_failed"] for row in rows),
        "live_rejections_total": sum(row["live_rejections"] for row in rows),
        "final_paper_total_equity": final_paper_equity,
        "final_live_total_equity": final_live_equity,
    }


def run_live_validation(
    strategy_key: str,
    codes: list[str],
    params: dict[str, Any],
    start_date: date,
    end_date: date,
    capital: float,
    tag: str = "validation",
    reset: bool = False,
) -> dict:
    stock_repo = StockRepository()
    paper_repo = PaperRepository()
    live_repo = LiveRepository()

    trade_dates = stock_repo.get_trade_dates(start_date, end_date)
    if not trade_dates:
        raise ValueError(f"{start_date} ~ {end_date} 范围内没有交易日")

    ids = build_validation_ids(strategy_key, codes, params, tag)
    if reset:
        paper_repo.delete_paper_account_state(ids.paper_account_id)
        live_repo.delete_live_instance_state(ids.live_instance_id)
    else:
        if paper_repo.get_paper_account(ids.paper_account_id) is not None:
            raise ValueError(
                f"validation 账户已存在: {ids.paper_account_id}，请改用其他 --tag 或加 --reset"
            )
        if live_repo.get_live_account(ids.live_instance_id) is not None:
            raise ValueError(
                f"validation 实例已存在: {ids.live_instance_id}，请改用其他 --tag 或加 --reset"
            )

    rows: list[dict] = []
    for trade_date in trade_dates:
        paper_strategy = load_strategy(strategy_key, params)
        paper_engine = PaperEngine(
            strategy=paper_strategy,
            stock_codes=codes,
            initial_capital=capital,
            run_date=trade_date,
            account_id=ids.paper_account_id,
        )
        paper_summary = paper_engine.run_daily()

        live_strategy = load_strategy(strategy_key, params)
        live_broker = DryRunBroker(
            instance_id=ids.live_instance_id,
            strategy_key=strategy_key,
            stock_codes=codes,
            initial_capital=capital,
            broker_account_id=f"VAL{ids.tag_digest.upper()}",
        )
        live_engine = LiveEngine(
            strategy=live_strategy,
            stock_codes=codes,
            broker=live_broker,
            instance_id=ids.live_instance_id,
            strategy_key=strategy_key,
            run_date=trade_date,
            current_dt=datetime.combine(trade_date, _VALIDATION_RUN_TIME),
            enforce_submit_window=False,
        )
        live_summary = live_engine.run_daily()

        rows.append(
            summarize_validation_day(
                trade_date=trade_date,
                paper_summary=paper_summary,
                live_summary=live_summary,
            )
        )

    aggregate = summarize_validation_report(
        rows=rows,
        paper_account_id=ids.paper_account_id,
        live_instance_id=ids.live_instance_id,
    )
    return {
        "strategy_key": strategy_key,
        "codes": codes,
        "params": params,
        "tag": tag,
        "start_date": trade_dates[0],
        "end_date": trade_dates[-1],
        "paper_account_id": ids.paper_account_id,
        "live_instance_id": ids.live_instance_id,
        "rows": rows,
        "aggregate": aggregate,
    }
