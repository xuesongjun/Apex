"""
Dashboard read-only API
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query

from api.dependencies import AccountIdDep, PaperRepoDep
from api.schemas import (
    AccountOption,
    DashboardOverview,
    DashboardPayload,
    NavPoint,
    PendingOrderItem,
    PositionItem,
)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _strategy_key_from_account_id(account_id: str) -> str:
    return account_id.split(":", 1)[0]


def _load_stock_codes(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return [str(item) for item in data] if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _stock_codes_with_fallback(raw: str | None, positions: list | None = None) -> list[str]:
    codes = _load_stock_codes(raw)
    if codes:
        return codes
    if positions:
        return sorted({str(p.code) for p in positions if getattr(p, "code", None)})
    return []


@router.get("/accounts", response_model=list[AccountOption])
def list_accounts(repo: PaperRepoDep):
    rows = repo.list_paper_accounts()
    items: list[AccountOption] = []
    for row in rows:
        positions = repo.get_paper_positions(row.strategy_name)
        items.append(
            AccountOption(
                account_id=row.strategy_name,
                strategy_key=_strategy_key_from_account_id(row.strategy_name),
                stock_codes=_stock_codes_with_fallback(row.stock_codes, positions),
                updated_at=row.updated_at,
                created_at=row.created_at,
            )
        )
    return items


@router.get("", response_model=DashboardPayload)
def get_dashboard(
    repo: PaperRepoDep,
    account_id: AccountIdDep,
    days: int = Query(60, ge=1, le=365, description="净值曲线天数"),
):
    accounts = list_accounts(repo)
    selected = account_id or (accounts[0].account_id if accounts else None)

    if not selected:
        return DashboardPayload(accounts=accounts, selected_account_id=None)

    account_row = repo.get_paper_account(selected)
    if account_row is None:
        raise HTTPException(status_code=404, detail=f"账户不存在: {selected}")

    positions = repo.get_paper_positions(selected)
    order_history = repo.get_order_history(selected)
    pending_orders = [o for o in order_history if o.status == "pending"]
    nav_rows = repo.get_nav_series(selected)
    nav_rows = nav_rows[-days:] if days > 0 else nav_rows

    market_value = sum((p.volume or 0) * (p.current_price or 0.0) for p in positions)
    total_equity = (account_row.cash or 0.0) + market_value
    initial_capital = account_row.initial_capital or 0.0
    total_profit = total_equity - initial_capital
    total_profit_pct = (total_profit / initial_capital * 100) if initial_capital > 0 else 0.0
    latest_trade_date = nav_rows[-1].trade_date if nav_rows else None

    overview = DashboardOverview(
        account_id=selected,
        strategy_key=_strategy_key_from_account_id(selected),
        stock_codes=_stock_codes_with_fallback(account_row.stock_codes, positions),
        initial_capital=round(initial_capital, 2),
        cash=round(account_row.cash or 0.0, 2),
        market_value=round(market_value, 2),
        total_equity=round(total_equity, 2),
        nav=round(total_equity / initial_capital, 6) if initial_capital > 0 else 1.0,
        total_profit=round(total_profit, 2),
        total_profit_pct=round(total_profit_pct, 2),
        total_commission=round(account_row.total_commission or 0.0, 2),
        total_tax=round(account_row.total_tax or 0.0, 2),
        position_count=len(positions),
        pending_count=len(pending_orders),
        latest_trade_date=latest_trade_date,
    )

    position_items = [
        PositionItem(
            code=p.code,
            volume=p.volume or 0,
            available=p.available or 0,
            cost_price=round(p.cost_price or 0.0, 3),
            current_price=round(p.current_price or 0.0, 3),
            market_value=round((p.volume or 0) * (p.current_price or 0.0), 2),
            profit=round(((p.current_price or 0.0) - (p.cost_price or 0.0)) * (p.volume or 0), 2),
            profit_pct=round((((p.current_price or 0.0) / (p.cost_price or 1.0)) - 1) * 100, 2)
            if (p.cost_price or 0.0) > 0
            else 0.0,
            buy_date=p.buy_date,
        )
        for p in positions
    ]

    pending_items = [
        PendingOrderItem(
            order_id=o.order_id,
            code=o.code,
            direction=o.direction,
            req_volume=o.req_volume or 0,
            execute_date=o.execute_date,
            signal_date=o.signal_date,
            status=o.status,
            reason=o.reason or "",
        )
        for o in pending_orders
    ]

    nav_points = [
        NavPoint(
            trade_date=row.trade_date,
            total_equity=round(row.total_equity or 0.0, 2),
            cash=round(row.cash or 0.0, 2),
            market_value=round(row.market_value or 0.0, 2),
            nav=round(row.nav or 0.0, 6) if row.nav is not None else None,
            daily_pnl=round(row.daily_pnl or 0.0, 2),
        )
        for row in nav_rows
    ]

    return DashboardPayload(
        accounts=accounts,
        selected_account_id=selected,
        overview=overview,
        positions=position_items,
        pending_orders=pending_items,
        nav=nav_points,
    )
