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
    parser.add_argument(
        "--all",
        action="store_true",
        dest="show_all",
        help="显示全部交易明细（默认只显示最近20笔）",
    )
    parser.add_argument(
        "--csv",
        default="",
        metavar="FILE",
        help="导出全部交易明细到 CSV 文件，如 --csv result.csv",
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

    # 检查每只股票的数据库日期范围
    from data.storage.repository import StockRepository
    repo = StockRepository()
    abort = False
    for code in args.codes:
        db_start, db_end = repo.get_date_range(code)
        if db_start is None:
            print(f"\n[错误] 数据库中没有 {code} 的任何数据，请先运行：")
            print(f"  python scripts/init_db.py --codes {code} --start {args.start}")
            abort = True
            continue
        if db_start > start_date:
            print(f"\n[警告] {code} 数据库最早为 {db_start}，晚于请求的起始日期 {start_date}")
            print(f"  若需要更早数据，请先运行：python scripts/init_db.py --codes {code} --start {args.start}")
            ans = input(f"  继续使用现有数据（从 {db_start} 开始）回测？[Y/n]: ").strip().lower()
            if ans == "n":
                abort = True
        if db_end < end_date:
            print(f"\n[警告] {code} 数据库最新为 {db_end}，早于请求的结束日期 {end_date}")
            print(f"  若需要最新数据，请先运行：python scripts/daily_update.py --codes {code}")
            ans = input(f"  继续使用现有数据（至 {db_end} 为止）回测？[Y/n]: ").strip().lower()
            if ans == "n":
                abort = True
    if abort:
        return

    result = engine.run()
    result.print_summary()

    # 打印交易明细
    trades_df = result.get_trades_df()
    if not trades_df.empty:
        display_df = trades_df if args.show_all else trades_df.tail(20)
        _print_trades(display_df, len(result.trades))
        if args.csv:
            trades_df.to_csv(args.csv, index=False, encoding="utf-8-sig")
            print(f"\n[已导出] 全部 {len(trades_df)} 笔交易明细 → {args.csv}")
    else:
        print("无交易记录")


def _pad_str(s: str, width: int, align: str = ">") -> str:
    """按显示宽度对齐（中文占2列）"""
    import unicodedata
    display_width = sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s)
    padding = max(0, width - display_width)
    if align == ">":
        return " " * padding + s
    elif align == "<":
        return s + " " * padding
    else:
        left = padding // 2
        return " " * left + s + " " * (padding - left)


def _print_trades(df, total_count: int):
    """格式化打印交易明细"""
    show_count = len(df)
    if show_count == total_count:
        print(f"\n【交易明细】（全部 {total_count} 笔）")
    else:
        print(f"\n【交易明细】（显示最近 {show_count} 笔，共 {total_count} 笔）")

    # 列定义: (表头, 宽度)
    cols = [
        ("代码", 8), ("买入日", 12), ("卖出日", 12), ("买入价", 8),
        ("卖出价", 8), ("数量(股)", 10), ("盈亏", 12),
        ("收益率%", 8), ("持仓天数", 8), ("卖出原因", 38),
    ]

    sep = "+" + "+".join("-" * w for _, w in cols) + "+"
    header = "|" + "|".join(_pad_str(name, w, "^") for name, w in cols) + "|"

    print(sep)
    print(header)
    print(sep)

    for _, row in df.iterrows():
        values = [
            row.get("code", ""),
            str(row.get("buy_date", "")),
            str(row.get("sell_date", "")),
            f"{row.get('buy_price', 0):.2f}",
            f"{row.get('sell_price', 0):.2f}",
            f"{row.get('volume', 0):,d}",
            f"{row.get('profit', 0):+,.2f}",
            f"{row.get('profit_pct', 0):+.2f}",
            str(row.get("holding_days", 0)),
            str(row.get("reason", "")),
        ]
        line = "|" + "|".join(_pad_str(val, w) for val, (_, w) in zip(values, cols)) + "|"
        print(line)

    print(sep)


if __name__ == "__main__":
    main()
