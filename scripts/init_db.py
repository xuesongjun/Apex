"""
数据库初始化脚本
首次运行时执行，创建表结构并拉取全量历史数据

用法:
    python scripts/init_db.py                              # 全量初始化，从 2020-01-01 开始
    python scripts/init_db.py --start 2023-01-01           # 指定起始日期
    python scripts/init_db.py --tables-only                # 仅创建表，不拉数据
    python scripts/init_db.py --stock-list-only            # 仅更新股票列表和交易日历
    python scripts/init_db.py --codes 000001 600519        # 只拉指定股票的K线
    python scripts/init_db.py --codes 000001 --start 2023-01-01
"""
import argparse
import sys
from datetime import date
from pathlib import Path

# 将项目根目录加入 sys.path
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

from loguru import logger
from config import setup_logging
from data.models import init_db


def main():
    parser = argparse.ArgumentParser(description="A股炒股系统 - 数据库初始化")
    parser.add_argument(
        "--start",
        type=str,
        default="2020-01-01",
        help="历史数据起始日期，格式 YYYY-MM-DD（默认 2020-01-01）",
    )
    parser.add_argument(
        "--tables-only",
        action="store_true",
        help="仅创建表结构，不拉取数据",
    )
    parser.add_argument(
        "--stock-list-only",
        action="store_true",
        help="仅更新股票列表和交易日历，不拉取K线",
    )
    parser.add_argument(
        "--codes",
        nargs="+",
        metavar="CODE",
        help="只拉取指定股票代码的K线，如 --codes 000001 600519",
    )
    args = parser.parse_args()

    # 初始化日志
    setup_logging()
    logger.info("=" * 60)
    logger.info("A股炒股系统 - 数据库初始化")
    logger.info("=" * 60)

    # 创建表结构
    logger.info("正在创建数据库表...")
    engine = init_db()
    logger.info(f"数据库表创建完成，引擎: {engine.url}")

    if args.tables_only:
        logger.info("仅创建表结构模式，跳过数据拉取")
        return

    # 拉取数据
    start_date = date.fromisoformat(args.start)
    logger.info(f"历史数据起始日期: {start_date}")

    from data.collector import DataCollector
    collector = DataCollector()

    if args.stock_list_only:
        collector.update_trade_calendar()
        collector.update_stock_list()
        logger.info("股票列表和交易日历更新完成")
        return

    if args.codes:
        # 只拉指定股票：先确保交易日历和股票列表存在
        logger.info(f"指定股票模式，代码: {args.codes}")
        collector.update_trade_calendar(start_date=start_date)
        collector.update_stock_list()
        collector.update_daily_bars(codes=args.codes, start_date=start_date)
        return

    # 全量初始化
    collector.init_all(start_date=start_date)


if __name__ == "__main__":
    main()
