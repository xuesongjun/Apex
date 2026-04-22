"""
实盘交易基座运行入口（Phase 7A）

当前默认通过 DryRunBroker 验证执行链，不直接连接真实券商。
"""
import argparse
import sys
from datetime import date, datetime
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

from loguru import logger

from config import BrokerConfig, setup_logging
from data.models import init_db
from strategy.registry import STRATEGY_REGISTRY, load_strategy
from trading.account_id import build_account_id
from trading.broker import DryRunBroker, QmtBroker
from trading.live_engine import LiveEngine


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


def print_summary(summary: dict):
    if not summary:
        return

    print("\n" + "=" * 64)
    print(f"  实盘交易基座日报：{summary['strategy']}  {summary['run_date']}")
    print(f"  实例ID：{summary['instance_id']}")
    print(f"  Broker：{summary['broker']}")
    print("=" * 64)
    print(f"\n  生成信号：{summary['signals_generated']} 个")
    print(f"  构建委托：{summary['orders_built']} 笔")
    print(f"  提交成功：{summary['orders_submitted']} 笔")
    print(f"  提交失败：{summary['orders_rejected']} 笔")
    print(f"\n  账户总资产：{summary['total_equity']:>14,.2f}")
    print(f"  可用现金：  {summary['cash']:>14,.2f}")
    print(f"  持仓数量：  {summary['position_count']:>14d}")
    print("=" * 64)


def build_broker(
    mode: str,
    provider: str,
    instance_id: str,
    strategy_key: str,
    stock_codes: list[str],
    initial_capital: float,
):
    if mode == "dry_run":
        return DryRunBroker(
            instance_id=instance_id,
            strategy_key=strategy_key,
            stock_codes=stock_codes,
            initial_capital=initial_capital,
            broker_account_id=BrokerConfig.account_id,
        )

    if provider == "qmt":
        return QmtBroker()

    raise ValueError(f"未知 broker 组合: mode={mode}, provider={provider}")


def main():
    parser = argparse.ArgumentParser(description="A股实盘交易基座（Phase 7A）")
    parser.add_argument("--strategy", "-s", required=True,
                        help=f"策略名称：{', '.join(STRATEGY_REGISTRY.keys())}")
    parser.add_argument("--codes", "-c", nargs="+", required=True,
                        help="股票代码（空格分隔）")
    parser.add_argument("--capital", type=float, default=1_000_000,
                        help="初始资金（dry-run 首次创建账户时生效）")
    parser.add_argument("--date", default=None,
                        help="指定运行日期（默认今天），格式 YYYY-MM-DD")
    parser.add_argument("--params", nargs="*",
                        help="策略参数 key=value 格式")
    parser.add_argument("--mode", default=BrokerConfig.mode,
                        help="broker 模式：dry_run / live（默认读 settings.yaml）")
    parser.add_argument("--provider", default=BrokerConfig.provider,
                        help="broker 提供方：qmt / miniqmt / dummy（默认读 settings.yaml）")
    args = parser.parse_args()

    setup_logging()
    init_db()

    params = parse_params(args.params)
    strategy = load_strategy(args.strategy, params)
    instance_id = build_account_id(args.strategy, args.codes, params)
    run_date = (
        datetime.strptime(args.date, "%Y-%m-%d").date()
        if args.date else date.today()
    )

    logger.info(
        f"启动实盘交易基座 strategy={args.strategy} "
        f"instance={instance_id} mode={args.mode} provider={args.provider}"
    )

    broker = build_broker(
        mode=args.mode,
        provider=args.provider,
        instance_id=instance_id,
        strategy_key=args.strategy,
        stock_codes=args.codes,
        initial_capital=args.capital,
    )

    engine = LiveEngine(
        strategy=strategy,
        stock_codes=args.codes,
        broker=broker,
        instance_id=instance_id,
        strategy_key=args.strategy,
        run_date=run_date,
    )
    summary = engine.run_daily()
    print_summary(summary)


if __name__ == "__main__":
    main()
