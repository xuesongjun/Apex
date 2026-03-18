"""
每日数据更新脚本
建议在每个交易日收盘后（15:30之后）执行

用法:
    python scripts/daily_update.py                # 常规增量更新
    python scripts/daily_update.py --validate     # 更新后做数据校验
    python scripts/daily_update.py --codes 000001 600519  # 仅更新指定股票
"""
import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

from loguru import logger
from config import setup_logging
from data.models import init_db


def main():
    parser = argparse.ArgumentParser(description="A股炒股系统 - 每日数据更新")
    parser.add_argument(
        "--codes",
        nargs="*",
        help="仅更新指定股票代码（空格分隔）",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="更新后对近7日数据做质量校验",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=0,
        help="回溯天数（用于补数据，如 --days 7 补近7天）",
    )
    args = parser.parse_args()

    setup_logging()
    logger.info("=" * 60)
    logger.info(f"A股炒股系统 - 每日数据更新 [{date.today()}]")
    logger.info("=" * 60)

    # 确保表存在
    init_db()

    from data.collector import DataCollector
    collector = DataCollector()

    if args.codes:
        # 仅更新指定股票
        start = date.today() - timedelta(days=max(args.days, 7))
        collector.update_daily_bars(
            codes=args.codes,
            start_date=start,
        )
    else:
        # 全量增量更新
        if args.days > 0:
            start = date.today() - timedelta(days=args.days)
            collector.update_daily_bars(start_date=start)
            collector.update_adj_factors(start_date=start)
            collector.update_index_daily(start_date=start)
        else:
            collector.daily_update()

    # 数据校验
    if args.validate:
        logger.info("开始数据质量校验...")
        codes = args.codes or collector.repo.get_all_stock_codes()[:50]  # 校验前50只
        start = date.today() - timedelta(days=7)
        end = date.today()
        issues_count = 0
        for code in codes:
            report = collector.validate_data(code, start, end)
            if report["missing_dates"] or report["anomalies"]:
                issues_count += 1
                logger.warning(
                    f"{code}: 缺失{len(report['missing_dates'])}天, "
                    f"异常{len(report['anomalies'])}条"
                )
        if issues_count == 0:
            logger.info("数据校验通过，未发现问题")
        else:
            logger.warning(f"数据校验完成，{issues_count} 只股票存在数据问题")


if __name__ == "__main__":
    main()
