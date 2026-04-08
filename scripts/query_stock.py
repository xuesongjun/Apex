"""
股票数据查询验证工具
支持从本地数据库或网络接口查询，用于验证数据正确性

用法:
    # 查本地数据库（默认）
    python scripts/query_stock.py -c 000001 -s 2023-01-03 -e 2023-01-10

    # 查网络接口
    python scripts/query_stock.py -c 000001 -s 2023-01-03 -e 2023-01-10 --source api

    # 对比两个源
    python scripts/query_stock.py -c 000001 -s 2023-01-03 -e 2023-01-10 --source both
"""
import argparse
import sys
from datetime import date, timedelta

import pandas as pd
from loguru import logger

# 添加项目根目录到 sys.path
sys.path.insert(0, ".")

from data.models import get_session, StockBasic
from data.sources.akshare_source import AKShareSource
from data.storage.repository import StockRepository


# 表格显示列定义
DISPLAY_COLUMNS = ["trade_date", "open", "high", "low", "close", "volume", "turnover", "pct_change"]
COLUMN_NAMES = {
    "trade_date": "日期",
    "open": "开盘",
    "high": "最高",
    "low": "最低",
    "close": "收盘",
    "volume": "成交量",
    "turnover": "换手率%",
    "pct_change": "涨跌幅%",
}


def get_stock_name(code: str) -> str:
    """从数据库查询股票名称"""
    session = get_session()
    try:
        stock = session.query(StockBasic).filter_by(code=code).first()
        return stock.name if stock else "未知"
    finally:
        session.close()


def query_from_db(code: str, start_date: date, end_date: date) -> pd.DataFrame:
    """从本地数据库查询"""
    repo = StockRepository()
    return repo.get_daily_bars(code, start_date, end_date)


def query_from_api(code: str, start_date: date, end_date: date) -> pd.DataFrame:
    """从网络接口查询"""
    source = AKShareSource()
    return source.get_daily_bars(code, start_date, end_date)


def format_volume(vol) -> str:
    """格式化成交量（股→万手，1手=100股）"""
    if pd.isna(vol) or vol == 0:
        return "-"
    wan_shou = vol / 100 / 10000  # 股 → 手 → 万手
    if wan_shou >= 10000:
        return f"{wan_shou / 10000:.2f}亿手"
    return f"{wan_shou:.2f}万手"


def format_turnover(val) -> str:
    """格式化换手率（新浪源返回小数形式 0.003687 → 0.37%）"""
    if pd.isna(val) or val == 0:
        return "-"
    pct = val * 100 if val < 1 else val
    return f"{pct:.2f}"


def pad_str(s: str, width: int, align: str = ">") -> str:
    """按显示宽度对齐字符串（中文占2列，ASCII占1列）"""
    import unicodedata
    display_width = sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s)
    padding = width - display_width
    if padding < 0:
        padding = 0
    if align == ">":
        return " " * padding + s
    elif align == "<":
        return s + " " * padding
    else:  # center
        left = padding // 2
        right = padding - left
        return " " * left + s + " " * right


def print_dataframe(df: pd.DataFrame, title: str):
    """格式化打印 DataFrame"""
    if df.empty:
        print(f"\n{title}: 无数据")
        return

    # 列定义: (表头, 宽度)
    cols = [("日期", 12), ("开盘", 9), ("最高", 9), ("最低", 9), ("收盘", 9), ("成交量", 12), ("换手率", 8), ("涨跌幅", 8)]

    sep = "+" + "+".join("-" * w for _, w in cols) + "+"
    header = "|" + "|".join(pad_str(name, w, "^") for name, w in cols) + "|"

    print(f"\n{title} (共 {len(df)} 条)")
    print(sep)
    print(header)
    print(sep)

    for _, row in df.iterrows():
        d = str(row.get("trade_date", ""))
        o = f"{row.get('open', 0):.3f}"
        h = f"{row.get('high', 0):.3f}"
        l = f"{row.get('low', 0):.3f}"
        c = f"{row.get('close', 0):.3f}"
        v = format_volume(row.get("volume", 0))
        t = format_turnover(row.get("turnover", 0))
        p = f"{row.get('pct_change', 0):+.2f}" if pd.notna(row.get("pct_change")) else "-"

        values = [d, o, h, l, c, v, t, p]
        line = "|" + "|".join(pad_str(val, w) for val, (_, w) in zip(values, cols)) + "|"
        print(line)

    print(sep)


def print_comparison(db_df: pd.DataFrame, api_df: pd.DataFrame):
    """对比显示两个数据源的差异"""
    if db_df.empty and api_df.empty:
        print("\n两个数据源均无数据")
        return

    if db_df.empty:
        print("\n本地数据库无数据，仅显示网络接口数据：")
        print_dataframe(api_df, "网络接口(API)")
        return

    if api_df.empty:
        print("\n网络接口无数据，仅显示本地数据库数据：")
        print_dataframe(db_df, "本地数据库(DB)")
        return

    # 按日期合并对比
    db_df = db_df.copy()
    api_df = api_df.copy()
    db_df["trade_date"] = pd.to_datetime(db_df["trade_date"]).dt.date
    api_df["trade_date"] = pd.to_datetime(api_df["trade_date"]).dt.date

    merged = pd.merge(
        db_df[["trade_date", "close"]],
        api_df[["trade_date", "close"]],
        on="trade_date",
        how="outer",
        suffixes=("_db", "_api"),
    ).sort_values("trade_date")

    print(f"\n收盘价对比 (共 {len(merged)} 个交易日)")
    print("-" * 60)
    print(f"{'日期':>12s} {'DB收盘':>10s} {'API收盘':>10s} {'差异':>10s}")
    print("-" * 60)

    diff_count = 0
    for _, row in merged.iterrows():
        d = str(row["trade_date"])
        db_close = row.get("close_db")
        api_close = row.get("close_api")

        db_str = f"{db_close:.3f}" if pd.notna(db_close) else "缺失"
        api_str = f"{api_close:.3f}" if pd.notna(api_close) else "缺失"

        if pd.notna(db_close) and pd.notna(api_close):
            diff = abs(db_close - api_close)
            diff_str = f"{diff:.4f}" if diff > 0.001 else "一致"
            if diff > 0.001:
                diff_count += 1
        else:
            diff_str = "缺失"
            diff_count += 1

        print(f"{d:>12s} {db_str:>10s} {api_str:>10s} {diff_str:>10s}")

    print("-" * 60)
    if diff_count == 0:
        print("结论: 所有数据一致 ✓")
    else:
        print(f"结论: 发现 {diff_count} 处差异 ✗")


def parse_args():
    parser = argparse.ArgumentParser(description="股票数据查询验证工具")
    parser.add_argument("--code", "-c", required=True, help="股票代码，如 000001")
    parser.add_argument("--start", "-s", help="起始日期，如 2023-01-01（默认: 近10个交易日）")
    parser.add_argument("--end", "-e", help="结束日期，如 2023-12-31（默认: 今天）")
    parser.add_argument(
        "--source",
        choices=["db", "api", "both"],
        default="db",
        help="数据来源: db=本地数据库, api=网络接口, both=对比（默认: db）",
    )
    return parser.parse_args()


def main():
    # 抑制 loguru 日志，只显示查询结果
    logger.remove()

    args = parse_args()
    code = args.code.zfill(6)  # 补齐6位
    end_date = date.fromisoformat(args.end) if args.end else date.today()
    start_date = date.fromisoformat(args.start) if args.start else end_date - timedelta(days=20)

    stock_name = get_stock_name(code)
    print(f"查询股票: {code} ({stock_name})")
    print(f"日期范围: {start_date} ~ {end_date}")
    print(f"数据来源: {args.source}")

    if args.source == "db":
        df = query_from_db(code, start_date, end_date)
        print_dataframe(df, "本地数据库(DB)")

    elif args.source == "api":
        df = query_from_api(code, start_date, end_date)
        print_dataframe(df, "网络接口(API)")

    elif args.source == "both":
        print("\n正在查询本地数据库...")
        db_df = query_from_db(code, start_date, end_date)
        print_dataframe(db_df, "本地数据库(DB)")

        print("\n正在查询网络接口...")
        api_df = query_from_api(code, start_date, end_date)
        print_dataframe(api_df, "网络接口(API)")

        print_comparison(db_df, api_df)


if __name__ == "__main__":
    main()
