"""
Dashboard read-only API
"""
from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from api.dependencies import AccountIdDep, LiveRepoDep, PaperRepoDep
from api.schemas import (
    AccountOption,
    DashboardOverview,
    DashboardPayload,
    NavPoint,
    OrderItem,
    PendingOrderItem,
    PositionItem,
)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

DashboardMode = Literal["paper", "live"]
_LIVE_ACTIVE_ORDER_STATUSES = {"planned", "submitted", "accepted"}


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


def _list_paper_accounts(repo) -> list[AccountOption]:
    rows = repo.list_paper_accounts()
    items: list[AccountOption] = []
    for row in rows:
        positions = repo.get_paper_positions(row.strategy_name)
        items.append(
            AccountOption(
                account_id=row.strategy_name,
                strategy_key=_strategy_key_from_account_id(row.strategy_name),
                stock_codes=_stock_codes_with_fallback(row.stock_codes, positions),
                mode="paper",
                updated_at=row.updated_at,
                created_at=row.created_at,
            )
        )
    return items


def _list_live_accounts(repo) -> list[AccountOption]:
    rows = repo.list_live_accounts()
    items: list[AccountOption] = []
    for row in rows:
        positions = repo.get_live_positions(row.instance_id)
        items.append(
            AccountOption(
                account_id=row.instance_id,
                strategy_key=row.strategy_key or _strategy_key_from_account_id(row.instance_id),
                stock_codes=_stock_codes_with_fallback(row.stock_codes, positions),
                mode="live",
                updated_at=row.updated_at,
                created_at=row.created_at,
            )
        )
    return items


@router.get("/accounts", response_model=list[AccountOption])
def list_accounts(
    paper_repo: PaperRepoDep,
    live_repo: LiveRepoDep,
    mode: DashboardMode = Query("paper", description="视图模式：paper / live"),
):
    if mode == "live":
        return _list_live_accounts(live_repo)
    return _list_paper_accounts(paper_repo)


def _build_paper_dashboard(repo, selected: str, accounts: list[AccountOption], days: int) -> DashboardPayload:
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
        mode="paper",
        accounts=accounts,
        selected_account_id=selected,
        overview=overview,
        positions=position_items,
        pending_orders=pending_items,
        orders=[],
        nav=nav_points,
    )


def _build_live_dashboard(repo, selected: str, accounts: list[AccountOption], days: int) -> DashboardPayload:
    del days  # live 视图当前没有净值曲线历史

    account_row = repo.get_live_account(selected)
    if account_row is None:
        raise HTTPException(status_code=404, detail=f"账户不存在: {selected}")

    positions = repo.get_live_positions(selected)
    orders = repo.get_live_orders(selected)
    active_orders = [o for o in orders if o.status in _LIVE_ACTIVE_ORDER_STATUSES]

    cash = float(account_row.cash or 0.0)
    market_value = sum((p.volume or 0) * (p.current_price or 0.0) for p in positions)
    total_equity = float(account_row.total_equity or (cash + market_value))
    initial_capital = float(account_row.initial_capital or 0.0)
    total_profit = total_equity - initial_capital
    total_profit_pct = (total_profit / initial_capital * 100) if initial_capital > 0 else 0.0
    total_commission = sum(float(o.commission or 0.0) for o in orders)
    latest_trade_date = max(
        [
            dt
            for dt in (
                [o.signal_date for o in orders if o.signal_date]
                + [o.planned_execute_date for o in orders if o.planned_execute_date]
            )
        ],
        default=None,
    )

    overview = DashboardOverview(
        account_id=selected,
        strategy_key=account_row.strategy_key or _strategy_key_from_account_id(selected),
        stock_codes=_stock_codes_with_fallback(account_row.stock_codes, positions),
        initial_capital=round(initial_capital, 2),
        cash=round(cash, 2),
        market_value=round(market_value, 2),
        total_equity=round(total_equity, 2),
        nav=round(total_equity / initial_capital, 6) if initial_capital > 0 else 1.0,
        total_profit=round(total_profit, 2),
        total_profit_pct=round(total_profit_pct, 2),
        total_commission=round(total_commission, 2),
        total_tax=0.0,
        position_count=len(positions),
        pending_count=len(active_orders),
        latest_trade_date=latest_trade_date,
        broker_provider=account_row.broker_provider,
        account_status=account_row.status,
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
            buy_date=None,
        )
        for p in positions
    ]

    order_items = [
        OrderItem(
            order_id=o.order_id,
            broker_order_id=o.broker_order_id or "",
            code=o.code,
            direction=o.direction,
            req_volume=o.req_volume or 0,
            req_price=round(o.req_price or 0.0, 3),
            execute_at=o.execute_at,
            execute_date=o.planned_execute_date,
            signal_date=o.signal_date,
            status=o.status,
            filled_volume=o.filled_volume or 0,
            filled_price=round(o.filled_price or 0.0, 3),
            commission=round(o.commission or 0.0, 2),
            reason=o.reason or "",
            created_at=o.created_at,
            updated_at=o.updated_at,
        )
        for o in orders
    ]

    return DashboardPayload(
        mode="live",
        accounts=accounts,
        selected_account_id=selected,
        overview=overview,
        positions=position_items,
        pending_orders=[],
        orders=order_items,
        nav=[],
    )


@router.get("", response_model=DashboardPayload)
def get_dashboard(
    paper_repo: PaperRepoDep,
    live_repo: LiveRepoDep,
    account_id: AccountIdDep,
    mode: DashboardMode = Query("paper", description="视图模式：paper / live"),
    days: int = Query(60, ge=1, le=365, description="净值曲线天数"),
):
    accounts = list_accounts(paper_repo=paper_repo, live_repo=live_repo, mode=mode)
    selected = account_id or (accounts[0].account_id if accounts else None)

    if not selected:
        return DashboardPayload(mode=mode, accounts=accounts, selected_account_id=None)

    if mode == "live":
        return _build_live_dashboard(live_repo, selected, accounts, days)
    return _build_paper_dashboard(paper_repo, selected, accounts, days)
