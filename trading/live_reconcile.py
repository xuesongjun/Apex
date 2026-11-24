"""
实盘状态只读对账
"""
from __future__ import annotations

from typing import Any

from data.storage.repository import LiveRepository
from trading.broker.base import BaseBroker, BrokerAccount, BrokerOrder, BrokerPosition

_ACCOUNT_MONEY_TOL = 0.01
_PRICE_TOL = 0.001
_COMMISSION_TOL = 0.01


def _is_close(left: float, right: float, tol: float) -> bool:
    return abs(float(left) - float(right)) <= tol


def _make_diff(field: str, local_value: Any, broker_value: Any) -> dict:
    diff = {
        "field": field,
        "local": local_value,
        "broker": broker_value,
    }
    if isinstance(local_value, (int, float)) and isinstance(broker_value, (int, float)):
        diff["delta"] = round(float(local_value) - float(broker_value), 6)
    return diff


def _serialize_account(row) -> dict | None:
    if row is None:
        return None
    return {
        "instance_id": row.instance_id,
        "broker_provider": row.broker_provider,
        "broker_account_id": row.broker_account_id or "",
        "cash": float(row.cash or 0.0),
        "total_equity": float(row.total_equity or 0.0),
        "status": row.status or "",
    }


def _serialize_broker_account(account: BrokerAccount) -> dict:
    return {
        "broker_provider": account.broker_provider,
        "broker_account_id": account.broker_account_id or "",
        "cash": float(account.cash or 0.0),
        "total_equity": float(account.total_equity or 0.0),
        "status": account.status or "",
    }


def _serialize_local_position(row) -> dict:
    return {
        "code": row.code,
        "volume": int(row.volume or 0),
        "available": int(row.available or 0),
        "cost_price": float(row.cost_price or 0.0),
        "current_price": float(row.current_price or 0.0),
        "source": row.source or "",
    }


def _serialize_broker_position(row: BrokerPosition) -> dict:
    return {
        "code": row.code,
        "volume": int(row.volume or 0),
        "available": int(row.available or 0),
        "cost_price": float(row.cost_price or 0.0),
        "current_price": float(row.current_price or 0.0),
    }


def _serialize_local_order(row) -> dict:
    return {
        "order_id": row.order_id,
        "broker_order_id": row.broker_order_id or "",
        "code": row.code,
        "direction": row.direction,
        "signal_date": row.signal_date,
        "planned_execute_date": row.planned_execute_date,
        "execute_at": row.execute_at,
        "req_price": float(row.req_price or 0.0),
        "req_volume": int(row.req_volume or 0),
        "status": row.status,
        "filled_price": float(row.filled_price or 0.0),
        "filled_volume": int(row.filled_volume or 0),
        "commission": float(row.commission or 0.0),
        "reason": row.reason or "",
    }


def _serialize_broker_order(row: BrokerOrder) -> dict:
    return {
        "order_id": row.order_id,
        "broker_order_id": row.broker_order_id or "",
        "code": row.code,
        "direction": row.direction,
        "signal_date": row.signal_date,
        "planned_execute_date": row.planned_execute_date,
        "execute_at": row.execute_at,
        "req_price": float(row.req_price or 0.0),
        "req_volume": int(row.req_volume or 0),
        "status": row.status,
        "filled_price": float(row.filled_price or 0.0),
        "filled_volume": int(row.filled_volume or 0),
        "commission": float(row.commission or 0.0),
        "reason": row.reason or "",
    }


def _reconcile_account(local_account, broker_account: BrokerAccount) -> dict:
    local_data = _serialize_account(local_account)
    broker_data = _serialize_broker_account(broker_account)

    if local_data is None:
        return {
            "matched": False,
            "local_exists": False,
            "local": None,
            "broker": broker_data,
            "differences": [{"field": "live_account", "local": None, "broker": broker_data}],
        }

    differences: list[dict] = []
    if local_data["broker_account_id"] != broker_data["broker_account_id"]:
        differences.append(_make_diff("broker_account_id", local_data["broker_account_id"], broker_data["broker_account_id"]))
    if not _is_close(local_data["cash"], broker_data["cash"], _ACCOUNT_MONEY_TOL):
        differences.append(_make_diff("cash", local_data["cash"], broker_data["cash"]))
    if not _is_close(local_data["total_equity"], broker_data["total_equity"], _ACCOUNT_MONEY_TOL):
        differences.append(_make_diff("total_equity", local_data["total_equity"], broker_data["total_equity"]))
    if local_data["status"] != broker_data["status"]:
        differences.append(_make_diff("status", local_data["status"], broker_data["status"]))

    return {
        "matched": len(differences) == 0,
        "local_exists": True,
        "local": local_data,
        "broker": broker_data,
        "differences": differences,
    }


def _reconcile_positions(local_positions: list, broker_positions: list[BrokerPosition]) -> dict:
    local_by_code = {row.code: row for row in local_positions}
    broker_by_code = {row.code: row for row in broker_positions}

    missing_in_local = [
        _serialize_broker_position(broker_by_code[code])
        for code in sorted(set(broker_by_code) - set(local_by_code))
    ]
    missing_in_broker = [
        _serialize_local_position(local_by_code[code])
        for code in sorted(set(local_by_code) - set(broker_by_code))
    ]

    mismatched = []
    for code in sorted(set(local_by_code) & set(broker_by_code)):
        local_row = local_by_code[code]
        broker_row = broker_by_code[code]
        differences: list[dict] = []
        if int(local_row.volume or 0) != int(broker_row.volume or 0):
            differences.append(_make_diff("volume", int(local_row.volume or 0), int(broker_row.volume or 0)))
        if int(local_row.available or 0) != int(broker_row.available or 0):
            differences.append(_make_diff("available", int(local_row.available or 0), int(broker_row.available or 0)))
        if not _is_close(float(local_row.cost_price or 0.0), float(broker_row.cost_price or 0.0), _PRICE_TOL):
            differences.append(_make_diff("cost_price", float(local_row.cost_price or 0.0), float(broker_row.cost_price or 0.0)))
        if not _is_close(float(local_row.current_price or 0.0), float(broker_row.current_price or 0.0), _PRICE_TOL):
            differences.append(_make_diff("current_price", float(local_row.current_price or 0.0), float(broker_row.current_price or 0.0)))

        if differences:
            mismatched.append(
                {
                    "code": code,
                    "local": _serialize_local_position(local_row),
                    "broker": _serialize_broker_position(broker_row),
                    "differences": differences,
                }
            )

    return {
        "matched": not missing_in_local and not missing_in_broker and not mismatched,
        "local_count": len(local_positions),
        "broker_count": len(broker_positions),
        "missing_in_local": missing_in_local,
        "missing_in_broker": missing_in_broker,
        "mismatched": mismatched,
    }


def _reconcile_orders(local_orders: list, broker_orders: list[BrokerOrder]) -> dict:
    local_planned_pending = [
        _serialize_local_order(row)
        for row in local_orders
        if not (row.broker_order_id or "") and row.status == "planned"
    ]
    local_unlinked = [
        _serialize_local_order(row)
        for row in local_orders
        if not (row.broker_order_id or "") and row.status != "planned"
    ]

    local_by_broker_id = {
        row.broker_order_id: row
        for row in local_orders
        if row.broker_order_id
    }
    broker_by_broker_id = {
        row.broker_order_id: row
        for row in broker_orders
        if row.broker_order_id
    }

    missing_in_local = [
        _serialize_broker_order(broker_by_broker_id[broker_order_id])
        for broker_order_id in sorted(set(broker_by_broker_id) - set(local_by_broker_id))
    ]
    missing_in_broker = [
        _serialize_local_order(local_by_broker_id[broker_order_id])
        for broker_order_id in sorted(set(local_by_broker_id) - set(broker_by_broker_id))
    ]

    mismatched = []
    for broker_order_id in sorted(set(local_by_broker_id) & set(broker_by_broker_id)):
        local_row = local_by_broker_id[broker_order_id]
        broker_row = broker_by_broker_id[broker_order_id]
        differences: list[dict] = []
        if local_row.code != broker_row.code:
            differences.append(_make_diff("code", local_row.code, broker_row.code))
        if local_row.direction != broker_row.direction:
            differences.append(_make_diff("direction", local_row.direction, broker_row.direction))
        if int(local_row.req_volume or 0) != int(broker_row.req_volume or 0):
            differences.append(_make_diff("req_volume", int(local_row.req_volume or 0), int(broker_row.req_volume or 0)))
        if not _is_close(float(local_row.req_price or 0.0), float(broker_row.req_price or 0.0), _PRICE_TOL):
            differences.append(_make_diff("req_price", float(local_row.req_price or 0.0), float(broker_row.req_price or 0.0)))
        if local_row.status != broker_row.status:
            differences.append(_make_diff("status", local_row.status, broker_row.status))
        if int(local_row.filled_volume or 0) != int(broker_row.filled_volume or 0):
            differences.append(_make_diff("filled_volume", int(local_row.filled_volume or 0), int(broker_row.filled_volume or 0)))
        if not _is_close(float(local_row.filled_price or 0.0), float(broker_row.filled_price or 0.0), _PRICE_TOL):
            differences.append(_make_diff("filled_price", float(local_row.filled_price or 0.0), float(broker_row.filled_price or 0.0)))
        if not _is_close(float(local_row.commission or 0.0), float(broker_row.commission or 0.0), _COMMISSION_TOL):
            differences.append(_make_diff("commission", float(local_row.commission or 0.0), float(broker_row.commission or 0.0)))

        if differences:
            mismatched.append(
                {
                    "broker_order_id": broker_order_id,
                    "local": _serialize_local_order(local_row),
                    "broker": _serialize_broker_order(broker_row),
                    "differences": differences,
                }
            )

    return {
        "matched": (
            not missing_in_local
            and not missing_in_broker
            and not mismatched
            and not local_unlinked
        ),
        "local_count": len(local_orders),
        "broker_count": len(broker_orders),
        "comparable_local_count": len(local_by_broker_id),
        "local_planned_pending": local_planned_pending,
        "local_unlinked": local_unlinked,
        "missing_in_local": missing_in_local,
        "missing_in_broker": missing_in_broker,
        "mismatched": mismatched,
    }


def reconcile_live_state(
    instance_id: str,
    broker: BaseBroker,
    repo: LiveRepository | None = None,
) -> dict:
    """
    对单个策略实例执行只读对账。
    """
    repo = repo or LiveRepository()

    local_account = repo.get_live_account(instance_id)
    local_positions = repo.get_live_positions(instance_id)
    local_orders = repo.get_live_orders(instance_id)

    broker_account = broker.get_account()
    broker_positions = broker.get_positions()
    broker_orders = broker.list_orders()

    account_report = _reconcile_account(local_account, broker_account)
    position_report = _reconcile_positions(local_positions, broker_positions)
    order_report = _reconcile_orders(local_orders, broker_orders)

    has_diff = not (
        account_report["matched"]
        and position_report["matched"]
        and order_report["matched"]
    )
    return {
        "instance_id": instance_id,
        "broker": broker.name,
        "account": account_report,
        "positions": position_report,
        "orders": order_report,
        "has_diff": has_diff,
    }
