"""
A股交易规则
模拟真实市场的各种限制和特殊规则
"""
from datetime import date

from config import TradingRulesConfig
from strategy.base import BarData, Direction, Signal


class TradingRules:
    """A股交易规则检查器"""

    MIN_TRADE_UNIT = TradingRulesConfig.min_trade_unit  # 最小交易单位：100股

    @staticmethod
    def get_price_limit(code: str, is_st: bool = False) -> float:
        """
        获取涨跌停幅度

        参数:
            code: 股票代码
            is_st: 是否为 ST 股票
        """
        limits = TradingRulesConfig.price_limit
        if is_st:
            return limits.get("st", 0.05)
        if code.startswith("688"):
            return limits.get("star", 0.20)   # 科创板
        if code.startswith("300") or code.startswith("301"):
            return limits.get("gem", 0.20)     # 创业板
        if code.startswith("8") or code.startswith("4"):
            return limits.get("bse", 0.30)     # 北交所
        return limits.get("main_board", 0.10)  # 主板

    @staticmethod
    def calc_limit_prices(
        pre_close: float, code: str, is_st: bool = False
    ) -> tuple[float, float]:
        """
        计算涨停价和跌停价

        返回:
            (涨停价, 跌停价)
        """
        limit = TradingRules.get_price_limit(code, is_st)
        up_limit = round(pre_close * (1 + limit), 2)
        down_limit = round(pre_close * (1 - limit), 2)
        return up_limit, down_limit

    @staticmethod
    def is_limit_up(bar: BarData, is_st: bool = False) -> bool:
        """判断是否涨停"""
        if bar.pre_close <= 0:
            return False
        up_limit, _ = TradingRules.calc_limit_prices(
            bar.pre_close, bar.code, is_st
        )
        return bar.close >= up_limit

    @staticmethod
    def is_limit_down(bar: BarData, is_st: bool = False) -> bool:
        """判断是否跌停"""
        if bar.pre_close <= 0:
            return False
        _, down_limit = TradingRules.calc_limit_prices(
            bar.pre_close, bar.code, is_st
        )
        return bar.close <= down_limit

    @staticmethod
    def check_t_plus_1(buy_date: date, sell_date: date) -> bool:
        """
        检查 T+1 规则
        当日买入的股票，次日才能卖出

        返回:
            True = 允许卖出
        """
        return sell_date > buy_date

    @staticmethod
    def round_volume(volume: int, direction: Direction) -> int:
        """
        调整交易数量为合法值

        买入：必须为100的整数倍
        卖出：可以不足100股（零股一次性卖出）
        """
        unit = TradingRules.MIN_TRADE_UNIT
        if direction == Direction.BUY:
            return (volume // unit) * unit
        else:
            # 卖出时，不足100股可以一次性卖出，超过100股的部分必须为100的整数倍
            if volume <= unit:
                return volume
            remainder = volume % unit
            return volume  # 卖出允许零股

    @staticmethod
    def validate_order(
        signal: Signal,
        bar: BarData,
        available_cash: float,
        position_volume: int,
        position_available: int,
        is_st: bool = False,
    ) -> tuple[bool, str]:
        """
        验证订单是否合法

        返回:
            (是否合法, 原因说明)
        """
        # 检查涨跌停
        if signal.direction == Direction.BUY:
            if TradingRules.is_limit_up(bar, is_st):
                return False, "涨停板无法买入"
        elif signal.direction == Direction.SELL:
            if TradingRules.is_limit_down(bar, is_st):
                return False, "跌停板无法卖出"

        # 买入检查
        if signal.direction == Direction.BUY:
            volume = TradingRules.round_volume(signal.volume, Direction.BUY)
            if volume <= 0:
                return False, f"买入数量不足最小交易单位（{TradingRules.MIN_TRADE_UNIT}股）"
            cost = signal.price * volume
            if cost > available_cash:
                return False, f"资金不足：需要 {cost:.2f}，可用 {available_cash:.2f}"

        # 卖出检查
        if signal.direction == Direction.SELL:
            if position_volume <= 0:
                return False, "无持仓可卖"
            if position_available <= 0:
                return False, "T+1 限制：今日买入的股票明日才可卖出"
            if signal.volume > position_available:
                return False, f"卖出数量超出可用持仓：委托 {signal.volume}，可用 {position_available}"

        return True, "通过"
