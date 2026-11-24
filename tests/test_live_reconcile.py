"""
live 对账测试
"""
from __future__ import annotations

from datetime import date

from config import DatabaseConfig
from data.models import init_db
from data.storage.repository import LiveRepository
from trading.broker.base import BaseBroker, BrokerAccount, BrokerOrder, BrokerPosition
from trading.broker.dry_run import DryRunBroker
from trading.live_reconcile import reconcile_live_state


def setup_temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "live_reconcile.db"
    monkeypatch.setattr(DatabaseConfig, "engine", "sqlite")
    monkeypatch.setattr(DatabaseConfig, "sqlite_url", f"sqlite:///{db_path}")
    init_db()


class FakeBroker(BaseBroker):
    def __init__(
        self,
        account: BrokerAccount,
        positions: list[BrokerPosition],
        orders: list[BrokerOrder],
        broker_name: str = "qmt",
    ):
        self._account = account
        self._positions = positions
        self._orders = orders
        self._name = broker_name

    @property
    def name(self) -> str:
        return self._name

    def get_account(self) -> BrokerAccount:
        return self._account

    def get_positions(self) -> list[BrokerPosition]:
        return self._positions

    def submit_order(self, request):
        raise NotImplementedError

    def cancel_order(self, order_id: str):
        raise NotImplementedError

    def list_orders(self, status: str | None = None) -> list[BrokerOrder]:
        if status is None:
            return self._orders
        return [row for row in self._orders if row.status == status]


def test_reconcile_live_state_matches_when_local_and_broker_consistent(tmp_path, monkeypatch):
    setup_temp_db(tmp_path, monkeypatch)

    instance_id = "overnight_long:test"
    broker = DryRunBroker(
        instance_id=instance_id,
        strategy_key="overnight_long",
        stock_codes=["513090"],
        initial_capital=10_000.0,
        broker_account_id="DRYRUN",
    )
    repo = LiveRepository()
    repo.replace_live_positions(
        instance_id,
        [
            {
                "instance_id": instance_id,
                "code": "513090",
                "volume": 9000,
                "available": 9000,
                "cost_price": 1.05,
                "current_price": 1.08,
                "source": "broker",
            }
        ],
    )
    repo.save_live_order(
        {
            "order_id": "dry-order-1",
            "instance_id": instance_id,
            "strategy_key": "overnight_long",
            "broker_provider": "dry_run",
            "broker_order_id": "DRY-ORDER-1",
            "code": "513090",
            "direction": "BUY",
            "signal_date": date(2026, 1, 5),
            "planned_execute_date": date(2026, 1, 5),
            "execute_at": "close",
            "req_price": 1.05,
            "req_volume": 9000,
            "status": "submitted",
            "reason": "match",
        }
    )
    repo.save_live_order(
        {
            "order_id": "dry-order-2",
            "instance_id": instance_id,
            "strategy_key": "overnight_long",
            "broker_provider": "dry_run",
            "broker_order_id": "",
            "code": "513090",
            "direction": "SELL",
            "signal_date": date(2026, 1, 5),
            "planned_execute_date": date(2026, 1, 6),
            "execute_at": "next_open",
            "req_price": 1.08,
            "req_volume": 9000,
            "status": "planned",
            "reason": "planned",
        }
    )

    report = reconcile_live_state(instance_id=instance_id, broker=broker)

    assert report["has_diff"] is False
    assert report["account"]["matched"] is True
    assert report["positions"]["matched"] is True
    assert report["orders"]["matched"] is True
    assert len(report["orders"]["local_planned_pending"]) == 1
    assert report["orders"]["missing_in_local"] == []
    assert report["orders"]["missing_in_broker"] == []
    assert report["orders"]["mismatched"] == []


def test_reconcile_live_state_reports_account_position_and_order_diffs(tmp_path, monkeypatch):
    setup_temp_db(tmp_path, monkeypatch)

    instance_id = "overnight_long:test"
    repo = LiveRepository()
    repo.create_live_account(
        instance_id=instance_id,
        strategy_key="overnight_long",
        broker_provider="qmt",
        broker_account_id="LOCAL-ACC",
        initial_capital=100000.0,
        stock_codes=["513090", "600000"],
        cash=100000.0,
        total_equity=120000.0,
    )
    repo.replace_live_positions(
        instance_id,
        [
            {
                "instance_id": instance_id,
                "code": "513090",
                "volume": 9000,
                "available": 8000,
                "cost_price": 1.05,
                "current_price": 1.08,
                "source": "broker",
            },
            {
                "instance_id": instance_id,
                "code": "600000",
                "volume": 1000,
                "available": 1000,
                "cost_price": 10.0,
                "current_price": 10.2,
                "source": "broker",
            },
        ],
    )
    repo.save_live_order(
        {
            "order_id": "local-order-1",
            "instance_id": instance_id,
            "strategy_key": "overnight_long",
            "broker_provider": "qmt",
            "broker_order_id": "B-1",
            "code": "513090",
            "direction": "BUY",
            "signal_date": date(2026, 1, 5),
            "planned_execute_date": date(2026, 1, 5),
            "execute_at": "close",
            "req_price": 1.05,
            "req_volume": 9000,
            "status": "submitted",
            "reason": "mismatch",
        }
    )
    repo.save_live_order(
        {
            "order_id": "local-order-2",
            "instance_id": instance_id,
            "strategy_key": "overnight_long",
            "broker_provider": "qmt",
            "broker_order_id": "B-LOCAL",
            "code": "600000",
            "direction": "SELL",
            "signal_date": date(2026, 1, 5),
            "planned_execute_date": date(2026, 1, 5),
            "execute_at": "open",
            "req_price": 10.2,
            "req_volume": 1000,
            "status": "submitted",
            "reason": "local-only",
        }
    )
    repo.save_live_order(
        {
            "order_id": "local-order-3",
            "instance_id": instance_id,
            "strategy_key": "overnight_long",
            "broker_provider": "qmt",
            "broker_order_id": "",
            "code": "513090",
            "direction": "SELL",
            "signal_date": date(2026, 1, 5),
            "planned_execute_date": date(2026, 1, 6),
            "execute_at": "next_open",
            "req_price": 1.08,
            "req_volume": 9000,
            "status": "planned",
            "reason": "planned",
        }
    )

    broker = FakeBroker(
        account=BrokerAccount(
            broker_provider="qmt",
            broker_account_id="BROKER-ACC",
            cash=90000.0,
            total_equity=118000.0,
            status="ready",
        ),
        positions=[
            BrokerPosition(
                code="513090",
                volume=8000,
                available=8000,
                cost_price=1.04,
                current_price=1.07,
            ),
            BrokerPosition(
                code="159915",
                volume=5000,
                available=5000,
                cost_price=2.0,
                current_price=2.05,
            ),
        ],
        orders=[
            BrokerOrder(
                order_id="broker-order-1",
                broker_provider="qmt",
                broker_order_id="B-1",
                code="513090",
                direction="BUY",
                signal_date=date(2026, 1, 5),
                execute_at="open",
                planned_execute_date=date(2026, 1, 5),
                req_price=1.05,
                req_volume=8000,
                status="accepted",
                reason="broker",
            ),
            BrokerOrder(
                order_id="broker-order-2",
                broker_provider="qmt",
                broker_order_id="B-2",
                code="159915",
                direction="BUY",
                signal_date=date(2026, 1, 5),
                execute_at="open",
                planned_execute_date=date(2026, 1, 5),
                req_price=2.0,
                req_volume=5000,
                status="submitted",
                reason="broker-only",
            ),
        ],
    )

    report = reconcile_live_state(instance_id=instance_id, broker=broker)

    assert report["has_diff"] is True

    account_fields = {item["field"] for item in report["account"]["differences"]}
    assert {"broker_account_id", "cash", "total_equity", "status"} <= account_fields

    assert report["positions"]["matched"] is False
    assert report["positions"]["missing_in_local"][0]["code"] == "159915"
    assert report["positions"]["missing_in_broker"][0]["code"] == "600000"
    assert report["positions"]["mismatched"][0]["code"] == "513090"

    assert report["orders"]["matched"] is False
    assert len(report["orders"]["local_planned_pending"]) == 1
    assert report["orders"]["missing_in_local"][0]["broker_order_id"] == "B-2"
    assert report["orders"]["missing_in_broker"][0]["broker_order_id"] == "B-LOCAL"
    mismatch = report["orders"]["mismatched"][0]
    assert mismatch["broker_order_id"] == "B-1"
    mismatch_fields = {item["field"] for item in mismatch["differences"]}
    assert {"req_volume", "status"} <= mismatch_fields
