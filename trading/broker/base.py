"""
统一 broker 抽象层
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Optional

from strategy.base import Direction


@dataclass
class BrokerAccount:
    broker_provider: str
    broker_account_id: str
    cash: float
    total_equity: float
    status: str = "ready"


@dataclass
class BrokerPosition:
    code: str
    volume: int
    available: int
    cost_price: float = 0.0
    current_price: float = 0.0


@dataclass
class BrokerOrderRequest:
    order_id: str
    instance_id: str
    strategy_key: str
    code: str
    direction: Direction
    signal_date: date
    execute_at: str
    planned_execute_date: Optional[date]
    price: float = 0.0
    volume: int = 0
    reason: str = ""


@dataclass
class BrokerOrder:
    order_id: str
    broker_provider: str
    code: str
    direction: str
    signal_date: date
    execute_at: str
    planned_execute_date: Optional[date]
    req_price: float
    req_volume: int
    status: str
    broker_order_id: str = ""
    filled_price: float = 0.0
    filled_volume: int = 0
    commission: float = 0.0
    reason: str = ""


class BaseBroker(ABC):
    """统一 broker 接口。"""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def get_account(self) -> BrokerAccount:
        ...

    @abstractmethod
    def get_positions(self) -> list[BrokerPosition]:
        ...

    @abstractmethod
    def submit_order(self, request: BrokerOrderRequest) -> BrokerOrder:
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> BrokerOrder | None:
        ...

    @abstractmethod
    def list_orders(self, status: Optional[str] = None) -> list[BrokerOrder]:
        ...
