"""
live 风控兜底
"""
from __future__ import annotations

from datetime import date, datetime, time

from config import RiskControlConfig
from strategy.base import Direction
from trading.broker.base import BrokerOrderRequest, BrokerPosition

_OPEN_START = time(9, 15)
_OPEN_END = time(9, 35)
_CLOSE_START = time(14, 45)
_CLOSE_END = time(15, 0)


class LiveRiskGuard:
    """
    提交前的最小 live 风控兜底。

    只做本地拦截，不修改 broker 状态。
    """

    def __init__(
        self,
        total_equity: float,
        cash: float,
        positions: list[BrokerPosition],
        run_date: date,
        current_dt: datetime | None = None,
        enforce_submit_window: bool = True,
    ):
        self.total_equity = float(total_equity or 0.0)
        self.cash = float(cash or 0.0)
        self.run_date = run_date
        self.current_dt = current_dt or datetime.now()
        self.enforce_submit_window = enforce_submit_window
        self.max_single_position = float(RiskControlConfig.live_max_single_position or 0.0)
        self.max_total_position = float(RiskControlConfig.live_max_total_position or 0.0)

        self._positions: dict[str, dict] = {}
        self._total_market_value = 0.0
        for row in positions:
            market_value = float(row.current_price or 0.0) * int(row.volume or 0)
            self._positions[row.code] = {
                "volume": int(row.volume or 0),
                "available": int(row.available or 0),
                "market_value": market_value,
            }
            self._total_market_value += market_value

    def validate(
        self,
        request: BrokerOrderRequest,
        reference_price: float,
        position_available: int = 0,
    ) -> tuple[bool, str]:
        valid, reason = self._check_submit_window(request)
        if not valid:
            return False, reason

        valid, reason = self._check_price_and_volume(
            request=request,
            reference_price=reference_price,
            position_available=position_available,
        )
        if not valid:
            return False, reason

        if request.direction == Direction.BUY:
            valid, reason = self._check_position_limits(
                request=request,
                reference_price=reference_price,
            )
            if not valid:
                return False, reason

        return True, "通过"

    def apply(self, request: BrokerOrderRequest, reference_price: float) -> None:
        code_state = self._positions.setdefault(
            request.code,
            {"volume": 0, "available": 0, "market_value": 0.0},
        )
        trade_value = float(reference_price or 0.0) * int(request.volume or 0)

        if request.direction == Direction.BUY:
            code_state["volume"] += int(request.volume or 0)
            # 对于 next_open 计划卖单依赖的“今日买入仓位”，这里按未来可卖持仓处理。
            code_state["available"] += int(request.volume or 0)
            code_state["market_value"] += trade_value
            self.cash = max(0.0, self.cash - trade_value)
            self._total_market_value += trade_value
            return

        sell_volume = min(int(request.volume or 0), code_state["volume"])
        code_state["volume"] -= sell_volume
        code_state["available"] = max(0, code_state["available"] - sell_volume)
        reduction = min(code_state["market_value"], trade_value)
        code_state["market_value"] = max(0.0, code_state["market_value"] - reduction)
        self.cash += trade_value
        self._total_market_value = max(0.0, self._total_market_value - reduction)

    def get_available(self, code: str) -> int:
        state = self._positions.get(code)
        return int(state["available"]) if state else 0

    def _check_submit_window(self, request: BrokerOrderRequest) -> tuple[bool, str]:
        if not self.enforce_submit_window:
            return True, "通过"
        if request.execute_at == "next_open":
            return True, "通过"
        if self.run_date != self.current_dt.date():
            return True, "通过"

        current_time = self.current_dt.time()
        if request.execute_at == "open":
            if _OPEN_START <= current_time <= _OPEN_END:
                return True, "通过"
            return False, f"非交易时段禁止提交 open 委托（当前 {current_time.strftime('%H:%M:%S')}）"
        if request.execute_at == "close":
            if _CLOSE_START <= current_time <= _CLOSE_END:
                return True, "通过"
            return False, f"非交易时段禁止提交 close 委托（当前 {current_time.strftime('%H:%M:%S')}）"
        return False, f"未知执行时机：{request.execute_at}"

    def _check_price_and_volume(
        self,
        request: BrokerOrderRequest,
        reference_price: float,
        position_available: int,
    ) -> tuple[bool, str]:
        if int(request.volume or 0) <= 0:
            return False, "非法数量：委托数量必须大于 0"

        if request.execute_at in {"open", "close"} and float(reference_price or 0.0) <= 0:
            return False, "非法价格：即时委托价格必须大于 0"
        if request.execute_at == "next_open" and float(reference_price or 0.0) < 0:
            return False, "非法价格：计划单价格不能为负数"

        if request.direction == Direction.BUY:
            if int(request.volume or 0) % 100 != 0:
                return False, "非法数量：买入数量必须为 100 的整数倍"
            return True, "通过"

        if position_available <= 0:
            return False, "无可用持仓可卖"
        if int(request.volume or 0) > position_available:
            return False, f"卖出数量超出可用持仓：委托 {request.volume}，可用 {position_available}"
        return True, "通过"

    def _check_position_limits(
        self,
        request: BrokerOrderRequest,
        reference_price: float,
    ) -> tuple[bool, str]:
        if self.total_equity <= 0:
            return False, "账户总资产非法，无法评估 live 风控"

        trade_value = float(reference_price or 0.0) * int(request.volume or 0)
        if trade_value <= 0:
            return False, "非法价格：无法估算买入市值"

        current_state = self._positions.get(request.code, {})
        current_code_value = float(current_state.get("market_value", 0.0) or 0.0)
        projected_code_ratio = (current_code_value + trade_value) / self.total_equity
        if (
            self.max_single_position > 0
            and projected_code_ratio > self.max_single_position + 1e-9
        ):
            return (
                False,
                "触发 live 风控：单票仓位超限 "
                f"({projected_code_ratio:.2%} > {self.max_single_position:.2%})",
            )

        projected_total_ratio = (self._total_market_value + trade_value) / self.total_equity
        if (
            self.max_total_position > 0
            and projected_total_ratio > self.max_total_position + 1e-9
        ):
            return (
                False,
                "触发 live 风控：总仓位超限 "
                f"({projected_total_ratio:.2%} > {self.max_total_position:.2%})",
            )

        return True, "通过"
