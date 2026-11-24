"""
Phase 6 Dashboard API schemas
"""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class AccountOption(BaseModel):
    account_id: str
    strategy_key: str
    stock_codes: list[str]
    updated_at: datetime | None = None
    created_at: datetime | None = None


class DashboardOverview(BaseModel):
    account_id: str
    strategy_key: str
    stock_codes: list[str]
    initial_capital: float
    cash: float
    market_value: float
    total_equity: float
    nav: float
    total_profit: float
    total_profit_pct: float
    total_commission: float
    total_tax: float
    position_count: int
    pending_count: int
    latest_trade_date: date | None = None


class PositionItem(BaseModel):
    code: str
    volume: int
    available: int
    cost_price: float
    current_price: float
    market_value: float
    profit: float
    profit_pct: float
    buy_date: date | None = None


class PendingOrderItem(BaseModel):
    order_id: str
    code: str
    direction: str
    req_volume: int
    execute_date: date | None = None
    signal_date: date
    status: str
    reason: str


class NavPoint(BaseModel):
    trade_date: date
    total_equity: float
    cash: float | None = None
    market_value: float | None = None
    nav: float | None = None
    daily_pnl: float | None = None


class DashboardPayload(BaseModel):
    accounts: list[AccountOption]
    selected_account_id: str | None = None
    overview: DashboardOverview | None = None
    positions: list[PositionItem] = []
    pending_orders: list[PendingOrderItem] = []
    nav: list[NavPoint] = []
