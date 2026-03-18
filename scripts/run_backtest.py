"""
回测运行入口
提供命令行方式运行策略回测

用法:
    # 均线交叉策略回测
    python scripts/run_backtest.py --strategy ma_cross --codes 000001 600519 --start 2023-01-01 --end 2024-12-31

    # MACD 策略回测
    python scripts/run_backtest.py --strategy macd --codes 000001 --start 2023-01-01

    # 使用自定义参数
    python scripts/run_backtest.py --strategy ma_cross --codes 000001 --start 2023-01-01 --params short_period=10 long_period=30
"""
import argparse
import sys
from datetime import date
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

from loguru import logger
from config import setup_logging
from data.models import init_db


# 可用策略注册表
STRATEGY_MAP = {
    "ma_cross": {
        "class": "strategy.technical.ma_cross.MACrossStrategy",
        "description": "均线交叉策略",
        "default_params": {"short_period": 5, "long_period": 20, "ma_type": "EMA"},
    },
    "macd": {
        "class": "strategy.technical.macd_strategy.MACDStrategy",
        "description": "MACD策略",
        "default_params": {"fast_period": 12, "slow_period": 26, "signal_period": 9},
    },
}


def load_strategy(name: str, params: dict):
    """动态加载策略类"""
    if name not in STRATEGY_MAP:
        available = ", ".join(STRATEGY_MAP.keys())
        raise ValueError(f"未知策略: {name}，可用策略: {available}")

    info = STRATEGY_MAP[name]
    module_path, class_name = info["class"].rsplit(".", 1)

    import importlib
    module = importlib.import_module(module_path)
    strategy_class = getattr(module, class_name)

    # 合并默认参数和自定义参数
    config = {**info["default_params"], **params}
    return strategy_class(config)


def parse_params(param_strings: list[str]) -> dict:
    """解析命令行参数字符串 'key=value' 为字典"""
    params = {}
    if not param_strings:
        return params
    for p in param_strings:
        if "=" not in p:
            continue
        key, value = p.split("=", 1)
        # 自动类型转换
        try:
            value = int(value)
        except ValueError:
            try:
                value = float(value)
            except ValueError:
                pass
        params[key] = value
    return params


def main():
    parser = argparse.ArgumentParser(description="A股炒股系统 - 策略回测")
    parser.add_argument(
        "--strategy", "-s",
        type=str,
        required=True,
        help=f"策略名称: {', '.join(STRATEGY_MAP.keys())}",
    )
    parser.add_argument(
        "--codes", "-c",
        nargs="+",
        required=True,
        help="股票代码列表（空格分隔）",
    )
    parser.add_argument(
        "--start",
        type=str,
        required=True,
        help="回测开始日期 YYYY-MM-DD",
    )
    parser.add_argument(
        "--end",
        type=str,
        default=str(date.today()),
        help="回测结束日期 YYYY-MM-DD（默认今天）",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=1000000,
        help="初始资金（默认 100 万）",
    )
    parser.add_argument(
        "--params",
        nargs="*",
        help="策略参数 key=value 格式（空格分隔多个）",
    )
    args = parser.parse_args()

    setup_logging()

    # 确保数据库存在
    init_db()

    # 加载策略
    params = parse_params(args.params)
    strategy = load_strategy(args.strategy, params)

    start_date = date.fromisoformat(args.start)
    end_date = date.fromisoformat(args.end)

    logger.info(f"策略: {strategy.name}")
    logger.info(f"股票: {args.codes}")
    logger.info(f"区间: {start_date} ~ {end_date}")
    logger.info(f"资金: {args.capital:,.0f}")

    # 运行回测
    from backtest.engine import BacktestEngine

    engine = BacktestEngine(
        strategy=strategy,
        stock_codes=args.codes,
        start_date=start_date,
        end_date=end_date,
        initial_capital=args.capital,
    )

    result = engine.run()
    result.print_summary()

    # 打印交易明细（前20条）
    trades_df = result.get_trades_df()
    if not trades_df.empty:
        print("\n【交易明细（最近20笔）】")
        print(trades_df.tail(20).to_string(index=False))

    print(f"\n提示: 共 {len(result.trades)} 笔交易")


if __name__ == "__main__":
    main()
