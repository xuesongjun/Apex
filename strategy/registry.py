"""
策略注册表

统一管理所有可用策略，支持按名称动态加载。
新策略只需在 STRATEGY_REGISTRY 中添加一条记录即可接入回测和模拟盘。
"""
import importlib
from typing import Optional

from strategy.base import BaseStrategy

# ── 策略注册表 ────────────────────────────────────────────────────────────────
# key:   命令行/配置中使用的策略名称
# value: class_path（模块.类名）、描述、默认参数
STRATEGY_REGISTRY: dict[str, dict] = {
    "ma_cross": {
        "class": "strategy.technical.ma_cross.MACrossStrategy",
        "description": "均线交叉策略（金叉买入/死叉卖出）",
        "default_params": {"short_period": 5, "long_period": 20, "ma_type": "EMA"},
    },
    "macd": {
        "class": "strategy.technical.macd_strategy.MACDStrategy",
        "description": "MACD 策略（柱状线金叉/死叉）",
        "default_params": {"fast_period": 12, "slow_period": 26, "signal_period": 9},
    },
    "limitdown_short": {
        "class": "strategy.technical.limitdown_short.LimitDownShortStrategy",
        "description": "跌停做空策略（集合竞价卖出 + 收盘买入）",
        "default_params": {},
    },
}


def load_strategy(name: str, params: Optional[dict] = None) -> BaseStrategy:
    """
    按名称加载策略实例。

    参数：
        name:   策略名称（STRATEGY_REGISTRY 的 key）
        params: 额外参数，会覆盖 default_params

    返回：
        已实例化的策略对象

    异常：
        ValueError: 策略名称不存在
    """
    if name not in STRATEGY_REGISTRY:
        available = ", ".join(STRATEGY_REGISTRY.keys())
        raise ValueError(f"未知策略: '{name}'，可用策略: {available}")

    info = STRATEGY_REGISTRY[name]
    module_path, class_name = info["class"].rsplit(".", 1)
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)

    config = {**info["default_params"], **(params or {})}
    return cls(config)


def list_strategies() -> list[dict]:
    """返回所有已注册策略的描述列表"""
    return [
        {"name": k, "description": v["description"], "default_params": v["default_params"]}
        for k, v in STRATEGY_REGISTRY.items()
    ]
