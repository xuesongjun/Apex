"""
策略基类
所有交易策略必须继承 BaseStrategy 并实现核心方法
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional


class Direction(Enum):
    """交易方向"""
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class BarData:
    """单根K线数据"""
    code: str
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    pre_close: float
    volume: int
    amount: float
    turnover: float = 0.0
    pct_change: float = 0.0


@dataclass
class Signal:
    """交易信号"""
    code: str                          # 股票代码
    direction: Direction               # 交易方向
    trade_date: date                   # 信号日期
    price: float = 0.0                 # 期望价格（0 表示以开盘价成交）
    volume: int = 0                    # 期望数量（0 表示由仓位管理决定）
    reason: str = ""                   # 触发原因
    confidence: float = 1.0            # 信号置信度 0.0 ~ 1.0


@dataclass
class OrderData:
    """订单数据"""
    code: str
    direction: Direction
    price: float                       # 委托价格
    volume: int                        # 委托数量
    trade_date: date
    order_id: str = ""
    status: str = "created"            # created / filled / rejected / cancelled
    filled_price: float = 0.0          # 实际成交价格
    filled_volume: int = 0             # 实际成交数量
    commission: float = 0.0            # 手续费
    reason: str = ""                   # 拒绝原因（如有）


@dataclass
class Position:
    """持仓数据"""
    code: str
    volume: int = 0                    # 总持仓量
    available: int = 0                 # 可卖数量（T+1 规则下，今买不可卖）
    cost_price: float = 0.0            # 成本价
    current_price: float = 0.0         # 当前价
    frozen: int = 0                    # 冻结数量（已委托卖出）
    buy_date: Optional[date] = None    # 最近买入日期

    @property
    def market_value(self) -> float:
        """持仓市值"""
        return self.volume * self.current_price

    @property
    def profit(self) -> float:
        """浮动盈亏"""
        return (self.current_price - self.cost_price) * self.volume

    @property
    def profit_pct(self) -> float:
        """浮动盈亏比例"""
        if self.cost_price <= 0:
            return 0.0
        return (self.current_price - self.cost_price) / self.cost_price


class BaseStrategy(ABC):
    """
    策略抽象基类

    所有策略必须实现：
    - name: 策略名称
    - on_bar(): K线驱动的信号生成
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self._positions: dict[str, Position] = {}  # 当前持仓（由引擎同步）
        self._cash: float = 0.0                     # 当前可用资金
        self._total_value: float = 0.0              # 账户总资产
        self._bar_history: dict[str, list[BarData]] = {}  # 历史K线缓存

    @property
    @abstractmethod
    def name(self) -> str:
        """策略名称"""
        ...

    @abstractmethod
    def on_bar(self, bar: BarData) -> Optional[Signal]:
        """
        K线驱动：每根K线触发一次
        分析行情数据，决定是否产生交易信号

        参数:
            bar: 当前K线数据

        返回:
            Signal 对象（产生信号时）或 None（无信号）
        """
        ...

    def on_order(self, order: OrderData):
        """订单回报处理（可选覆盖）"""
        pass

    def on_start(self):
        """策略启动时调用（可选覆盖）"""
        pass

    def on_stop(self):
        """策略停止时调用（可选覆盖）"""
        pass

    # ========== 辅助方法（子类可直接调用） ==========

    def get_position(self, code: str) -> Optional[Position]:
        """获取指定股票的持仓"""
        return self._positions.get(code)

    def has_position(self, code: str) -> bool:
        """是否持有某只股票"""
        pos = self._positions.get(code)
        return pos is not None and pos.volume > 0

    def get_history(self, code: str, count: int = 0) -> list[BarData]:
        """
        获取历史K线

        参数:
            code: 股票代码
            count: 获取最近 N 根K线，0 表示全部
        """
        bars = self._bar_history.get(code, [])
        if count > 0:
            return bars[-count:]
        return bars

    def get_close_series(self, code: str, count: int = 0) -> list[float]:
        """获取收盘价序列"""
        bars = self.get_history(code, count)
        return [b.close for b in bars]

    def get_volume_series(self, code: str, count: int = 0) -> list[float]:
        """获取成交量序列"""
        bars = self.get_history(code, count)
        return [b.volume for b in bars]

    # ========== 引擎调用的内部方法 ==========

    def _update_bar(self, bar: BarData):
        """引擎调用：推送K线并更新历史缓存"""
        if bar.code not in self._bar_history:
            self._bar_history[bar.code] = []
        self._bar_history[bar.code].append(bar)

    def _sync_account(
        self,
        positions: dict[str, Position],
        cash: float,
        total_value: float,
    ):
        """引擎调用：同步账户状态"""
        self._positions = positions
        self._cash = cash
        self._total_value = total_value
