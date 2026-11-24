"""
live rehearsal / 小资金验证入口

用途：
1. 按交易日区间并行跑 PaperEngine 与 LiveEngine(DryRunBroker)
2. 用隔离账户验证策略日级行为是否稳定
3. 在接真实 QMT / miniQMT 之前，先做小资金 rehearsal
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

from config import setup_logging
from data.models import init_db
from strategy.registry import STRATEGY_REGISTRY
from trading.live_validation import run_live_validation


def parse_params(param_strings: list[str]) -> dict:
    params = {}
    for p in (param_strings or []):
        if "=" not in p:
            continue
        key, value = p.split("=", 1)
        try:
            value = int(value)
        except ValueError:
            try:
                value = float(value)
            except ValueError:
                pass
        params[key] = value
    return params


def print_report(report: dict) -> None:
    aggregate = report["aggregate"]
    comparable_days = aggregate["comparable_days"]
    signal_match_summary = (
        f"{aggregate['signal_match_days']}/{comparable_days}"
        if comparable_days
        else "无可比较日"
    )
    paper_equity = aggregate["final_paper_total_equity"]
    live_equity = aggregate["final_live_total_equity"]
    paper_equity_label = "无数据" if paper_equity is None else f"{paper_equity:>14,.2f}"
    live_equity_label = "无数据" if live_equity is None else f"{live_equity:>14,.2f}"
    print("\n" + "=" * 72)
    print(f"  Live Rehearsal / 小资金验证：{report['strategy_key']}")
    print(f"  区间：{report['start_date']} ~ {report['end_date']}")
    print(f"  Tag：{report['tag']}")
    print("=" * 72)
    print(f"\n  Paper 账户：{report['paper_account_id']}")
    print(f"  Live 实例： {report['live_instance_id']}")
    print(f"  交易日数：  {aggregate['trade_days']}")
    print(f"  可比较日数：{comparable_days}")
    print(f"  信号一致：  {signal_match_summary}")
    print(f"  Paper 成交：{aggregate['paper_orders_filled_total']}")
    print(f"  Paper 挂单：{aggregate['paper_pending_total']}")
    print(f"  Live 建单： {aggregate['live_orders_built_total']}")
    print(f"  Live 激活： {aggregate['live_planned_activated_total']}")
    print(f"  Live 激活失败：{aggregate['live_planned_failed_total']}")
    print(f"  Paper 拒绝/取消：{aggregate['paper_rejections_total']}")
    print(f"  Live 拒绝：      {aggregate['live_rejections_total']}")
    print(f"  期末 Paper 总资产：{paper_equity_label}")
    print(f"  期末 Live 总资产： {live_equity_label}")

    print("\n  每日摘要：")
    print("  日期         Paper信号  Live信号  一致  Paper成交  Live建单  Live激活  激活失败  问题")
    print("  " + "─" * 78)
    for row in report["rows"]:
        paper_signals = str(row["paper_signals"]) if row["paper_ran"] else "跳过"
        live_signals = str(row["live_signals"]) if row["live_ran"] else "跳过"
        signal_match = row["signal_match"]
        match_label = "-" if signal_match is None else ("Y" if signal_match else "N")
        print(
            "  "
            f"{row['trade_date']}  "
            f"{paper_signals:>9s}  "
            f"{live_signals:>8s}  "
            f"{match_label:>4s}  "
            f"{row['paper_orders_filled']:>9d}  "
            f"{row['live_orders_built']:>8d}  "
            f"{row['live_planned_activated']:>8d}  "
            f"{row['live_planned_failed']:>8d}  "
            f"{'Y' if row['has_issue'] else '-':>4s}"
        )

    issue_days = aggregate["issue_days"]
    if issue_days:
        print("\n  发现问题日：")
        for row in issue_days:
            paper_status = "完成" if row["paper_ran"] else "跳过"
            live_status = "完成" if row["live_ran"] else "跳过"
            signal_match = row["signal_match"]
            match_label = "不可比较" if signal_match is None else str(signal_match)
            print(
                "  "
                f"{row['trade_date']} | Paper={paper_status} | Live={live_status} | "
                f"signal_match={match_label} | "
                f"paper_rejections={row['paper_rejections']} | "
                f"live_rejections={row['live_rejections']} | "
                f"planned_failed={row['live_planned_failed']}"
            )
    else:
        print("\n  发现问题日：无")
    print("=" * 72)


def main():
    parser = argparse.ArgumentParser(description="A股 live rehearsal / 小资金验证")
    parser.add_argument("--strategy", "-s", required=True,
                        help=f"策略名称：{', '.join(STRATEGY_REGISTRY.keys())}")
    parser.add_argument("--codes", "-c", nargs="+", required=True,
                        help="股票代码（空格分隔）")
    parser.add_argument("--start", required=True,
                        help="起始日期 YYYY-MM-DD")
    parser.add_argument("--end", required=True,
                        help="结束日期 YYYY-MM-DD")
    parser.add_argument("--capital", type=float, default=10_000,
                        help="验证资金（默认 10000）")
    parser.add_argument("--params", nargs="*",
                        help="策略参数 key=value 格式")
    parser.add_argument("--tag", default="validation",
                        help="验证标签，用于生成隔离账户/实例 ID")
    parser.add_argument("--reset", action="store_true",
                        help="删除同 tag 的历史验证状态后重跑")
    args = parser.parse_args()

    setup_logging()
    init_db()

    report = run_live_validation(
        strategy_key=args.strategy,
        codes=args.codes,
        params=parse_params(args.params),
        start_date=datetime.strptime(args.start, "%Y-%m-%d").date(),
        end_date=datetime.strptime(args.end, "%Y-%m-%d").date(),
        capital=args.capital,
        tag=args.tag,
        reset=args.reset,
    )
    print_report(report)


if __name__ == "__main__":
    main()
