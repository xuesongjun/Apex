"""
A股交易费用模型
包含佣金、印花税、过户费的计算
"""
from dataclasses import dataclass

from config import TradingRulesConfig
from strategy.base import Direction


@dataclass
class FeeResult:
    """费用计算结果"""
    commission: float    # 佣金
    stamp_tax: float     # 印花税
    transfer_fee: float  # 过户费
    total: float         # 总费用


class FeeModel:
    """A股交易费用模型"""

    def __init__(
        self,
        commission_rate: float = None,
        min_commission: float = None,
        stamp_tax_rate: float = None,
        transfer_fee_rate: float = None,
    ):
        self.commission_rate = commission_rate or TradingRulesConfig.commission_rate
        self.min_commission = min_commission or TradingRulesConfig.min_commission
        self.stamp_tax_rate = stamp_tax_rate or TradingRulesConfig.stamp_tax_rate
        self.transfer_fee_rate = transfer_fee_rate or TradingRulesConfig.transfer_fee_rate

    def calculate(
        self, price: float, volume: int, direction: Direction
    ) -> FeeResult:
        """
        计算交易费用

        参数:
            price: 成交价格
            volume: 成交数量（股）
            direction: 交易方向

        返回:
            FeeResult 费用明细
        """
        amount = price * volume

        # 佣金（买卖都收，有最低限额）
        commission = max(amount * self.commission_rate, self.min_commission)

        # 印花税（仅卖出收取，千分之一）
        stamp_tax = 0.0
        if direction == Direction.SELL:
            stamp_tax = amount * self.stamp_tax_rate

        # 过户费（买卖都收）
        transfer_fee = amount * self.transfer_fee_rate

        total = commission + stamp_tax + transfer_fee

        return FeeResult(
            commission=round(commission, 2),
            stamp_tax=round(stamp_tax, 2),
            transfer_fee=round(transfer_fee, 2),
            total=round(total, 2),
        )
