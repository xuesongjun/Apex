"""
QmtBroker 适配层测试

通过 fake xtquant 模块验证：
- 账户查询映射
- 持仓查询映射
- 订单提交映射
"""
from __future__ import annotations

from datetime import date
from types import ModuleType, SimpleNamespace

from config import DatabaseConfig
from data.models import init_db
from data.storage.repository import LiveRepository
from strategy.base import Direction
from trading.broker.base import BrokerOrderRequest
from trading.broker.qmt_broker import QmtBroker


def setup_temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "qmt_broker.db"
    monkeypatch.setattr(DatabaseConfig, "engine", "sqlite")
    monkeypatch.setattr(DatabaseConfig, "sqlite_url", f"sqlite:///{db_path}")
    init_db()


def install_fake_xtquant(monkeypatch):
    xtquant_pkg = ModuleType("xtquant")
    xttrader_mod = ModuleType("xtquant.xttrader")
    xttype_mod = ModuleType("xtquant.xttype")
    xtconstant_mod = ModuleType("xtquant.xtconstant")

    class FakeCallback:
        pass

    class FakeStockAccount:
        def __init__(self, account_id, account_type):
            self.account_id = account_id
            self.account_type = account_type

    class FakeTrader:
        def __init__(self, userdata_path, session_id):
            self.userdata_path = userdata_path
            self.session_id = session_id
            self.orders = []

        def register_callback(self, callback):
            self.callback = callback

        def start(self):
            return 0

        def connect(self):
            return 0

        def subscribe(self, account):
            self.account = account
            return 0

        def query_stock_asset(self, account):
            return SimpleNamespace(cash=120000.0, total_asset=150000.0)

        def query_stock_positions(self, account):
            return [
                SimpleNamespace(
                    stock_code="513090.SH",
                    volume=9000,
                    can_use_volume=9000,
                    open_price=1.05,
                    last_price=1.08,
                )
            ]

        def order_stock(self, account, stock_code, order_type, volume, price_type, price, strategy_name, remark):
            self.orders.append({
                "stock_code": stock_code,
                "order_type": order_type,
                "volume": volume,
                "price_type": price_type,
                "price": price,
                "strategy_name": strategy_name,
                "remark": remark,
            })
            return 10001

        def cancel_order_stock(self, account, broker_order_id):
            return 0

        def query_stock_orders(self, account):
            return [
                SimpleNamespace(
                    order_id=10001,
                    stock_code="513090.SH",
                    order_type=23,
                    order_volume=9000,
                    traded_volume=0,
                    order_status=50,
                    price=1.05,
                    traded_price=0.0,
                    commission=0.0,
                    order_remark="test",
                )
            ]

    xttrader_mod.XtQuantTrader = FakeTrader
    xttrader_mod.XtQuantTraderCallback = FakeCallback
    xttype_mod.StockAccount = FakeStockAccount
    xtconstant_mod.STOCK_BUY = 23
    xtconstant_mod.STOCK_SELL = 24
    xtconstant_mod.FIX_PRICE = 11
    xtconstant_mod.LATEST_PRICE = 5
    xtconstant_mod.ORDER_REPORTED = 50
    xtconstant_mod.ORDER_CANCELED = 54
    xtconstant_mod.ORDER_REJECTED = 57

    import importlib

    real_import_module = importlib.import_module

    def fake_import_module(name, package=None):
        if name == "xtquant":
            return xtquant_pkg
        if name == "xtquant.xttrader":
            return xttrader_mod
        if name == "xtquant.xttype":
            return xttype_mod
        if name == "xtquant.xtconstant":
            return xtconstant_mod
        return real_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)


def test_qmt_broker_queries_account_positions_and_submits_order(tmp_path, monkeypatch):
    setup_temp_db(tmp_path, monkeypatch)
    install_fake_xtquant(monkeypatch)

    broker = QmtBroker(
        instance_id="overnight_long:test",
        strategy_key="overnight_long",
        stock_codes=["513090"],
        initial_capital=100000.0,
        account_id="demo-account",
        userdata_path="/tmp/qmt",
        session_id=100001,
        account_type="STOCK",
        dynamic_price_type="LATEST_PRICE",
    )

    account = broker.get_account()
    positions = broker.get_positions()
    order = broker.submit_order(
        BrokerOrderRequest(
            order_id="qmt-order-1",
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
    )

    repo = LiveRepository()
    saved = repo.get_live_order("qmt-order-1")

    assert account.broker_provider == "qmt"
    assert account.cash == 120000.0
    assert account.total_equity == 150000.0
    assert len(positions) == 1
    assert positions[0].code == "513090"
    assert positions[0].available == 9000
    assert order.broker_order_id == "10001"
    assert order.status == "submitted"
    assert saved is not None
    assert saved.broker_order_id == "10001"
    assert saved.status == "submitted"
