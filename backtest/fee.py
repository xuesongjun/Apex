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
        self.commission_rate = commission_rate if commission_rate is not None else TradingRulesConfig.commission_rate
        self.min_commission = min_commission if min_commission is not None else TradingRulesConfig.min_commission
        self.stamp_tax_rate = stamp_tax_rate if stamp_tax_rate is not None else TradingRulesConfig.stamp_tax_rate
        self.transfer_fee_rate = transfer_fee_rate if transfer_fee_rate is not None else TradingRulesConfig.transfer_fee_rate

    def calculate(
        self, price: float, volume: int, direction: Direction, is_etf: bool = False
    ) -> FeeResult:
        """
        计算交易费用

        参数:
            price:     成交价格
            volume:    成交数量（股）
            direction: 交易方向
            is_etf:    是否为 ETF（ETF 免征印花税）

        返回:
            FeeResult 费用明细
        """
        amount = price * volume

        # 佣金（买卖都收，有最低限额）
        commission = max(amount * self.commission_rate, self.min_commission)

        # 印花税（仅个股卖出收取，ETF 免征）
        stamp_tax = 0.0
        if direction == Direction.SELL and not is_etf:
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
