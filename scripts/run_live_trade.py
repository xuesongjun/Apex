"""
实盘交易基座运行入口（Phase 7A）

当前默认通过 DryRunBroker 验证执行链，不直接连接真实券商。
"""
import argparse
import sys
import uuid
from datetime import date, datetime
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

from loguru import logger

from config import BrokerConfig, setup_logging
from data.models import init_db
from notification import EmailNotifier
from strategy.base import Direction
from strategy.registry import STRATEGY_REGISTRY, load_strategy
from trading.account_id import build_account_id
from trading.broker.base import BrokerOrderRequest
from trading.broker import DryRunBroker, QmtBroker
from trading.live_engine import LiveEngine
from trading.live_reconcile import reconcile_live_state


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
    print(f"  激活计划单：{summary['planned_orders_activated']} 笔")
    print(f"  计划单失败：{summary['planned_orders_failed']} 笔")
    print(f"  构建委托：{summary['orders_built']} 笔")
    print(f"  风控拦截：{summary.get('orders_risk_rejected', 0)} 笔")
    print(f"  提交成功：{summary['orders_submitted']} 笔")
    print(f"  提交失败：{summary.get('orders_broker_rejected', summary['orders_rejected'])} 笔")
    print(f"\n  账户总资产：{summary['total_equity']:>14,.2f}")
    print(f"  可用现金：  {summary['cash']:>14,.2f}")
    print(f"  持仓数量：  {summary['position_count']:>14d}")
    print("=" * 64)


def print_broker_check_summary(result: dict):
    print("\n" + "=" * 64)
    print(f"  QMT 联调诊断：{result['provider']}")
    print(f"  账户ID：{result['account_id']}")
    print("=" * 64)
    print(f"\n  xtquant 导入：{'OK' if result['xtquant_imported'] else 'FAILED'}")
    print(f"  connect：      {'OK' if result['connected'] else 'FAILED'}")
    print(f"  subscribe：    {'OK' if result['subscribed'] else 'FAILED'}")
    print(f"  账户总资产：{result['account']['total_equity']:>14,.2f}")
    print(f"  可用现金：  {result['account']['cash']:>14,.2f}")
    print(f"  持仓数量：  {result['positions_count']:>14d}")
    print(f"  订单数量：  {result['orders_count']:>14d}")

    test_order = result.get("test_order")
    if test_order:
        print("\n  测试单：")
        print(f"  - 代码：{test_order['code']}")
        print(f"  - 方向：{test_order['direction']}")
        print(f"  - 价格：{test_order['req_price']}")
        print(f"  - 数量：{test_order['req_volume']}")
        print(f"  - 提交状态：{test_order['submit_status']}")
        print(f"  - 查询状态：{test_order['query_status'] or 'unknown'}")
        print(f"  - 撤单状态：{test_order['cancel_status']}")
    else:
        print("\n  测试单：未执行（只读诊断模式）")
    print("=" * 64)


def print_reconcile_summary(report: dict):
    print("\n" + "=" * 64)
    print(f"  Live 对账报告：{report['broker']}")
    print(f"  实例ID：{report['instance_id']}")
    print(f"  结果：{'发现差异' if report['has_diff'] else '一致'}")
    print("=" * 64)

    account = report["account"]
    print(f"\n  账户：{'一致' if account['matched'] else '有差异'}")
    for diff in account["differences"]:
        print(f"  - {diff['field']}: local={diff['local']} | broker={diff['broker']}")

    positions = report["positions"]
    print(
        f"\n  持仓：{'一致' if positions['matched'] else '有差异'} "
        f"(local={positions['local_count']}, broker={positions['broker_count']})"
    )
    for item in positions["missing_in_local"]:
        print(f"  - broker_only position: {item['code']} volume={item['volume']}")
    for item in positions["missing_in_broker"]:
        print(f"  - local_only position: {item['code']} volume={item['volume']}")
    for item in positions["mismatched"]:
        fields = ", ".join(diff["field"] for diff in item["differences"])
        print(f"  - mismatch position {item['code']}: {fields}")

    orders = report["orders"]
    print(
        f"\n  订单：{'一致' if orders['matched'] else '有差异'} "
        f"(local={orders['local_count']}, broker={orders['broker_count']}, comparable={orders['comparable_local_count']})"
    )
    if orders["local_planned_pending"]:
        print(f"  - local planned 未上券商: {len(orders['local_planned_pending'])} 笔")
    for item in orders["local_unlinked"]:
        print(f"  - local unlinked order: {item['order_id']} status={item['status']}")
    for item in orders["missing_in_local"]:
        print(f"  - broker_only order: {item['broker_order_id']} {item['code']} {item['status']}")
    for item in orders["missing_in_broker"]:
        print(f"  - local_only order: {item['broker_order_id']} {item['code']} {item['status']}")
    for item in orders["mismatched"]:
        fields = ", ".join(diff["field"] for diff in item["differences"])
        print(f"  - mismatch order {item['broker_order_id']}: {fields}")
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

    if mode == "live" and provider in {"qmt", "miniqmt"}:
        return QmtBroker(
            instance_id=instance_id,
            strategy_key=strategy_key,
            stock_codes=stock_codes,
            initial_capital=initial_capital,
            provider_name=provider,
            account_id=BrokerConfig.account_id,
            userdata_path=BrokerConfig.qmt_userdata_path,
            session_id=BrokerConfig.qmt_session_id,
            account_type=BrokerConfig.qmt_account_type,
            dynamic_price_type=BrokerConfig.qmt_dynamic_price_type,
            strategy_name=BrokerConfig.qmt_strategy_name,
            order_remark_prefix=BrokerConfig.qmt_order_remark_prefix,
        )

    raise ValueError(f"未知 broker 组合: mode={mode}, provider={provider}")


def build_broker_check_request(
    args,
    instance_id: str,
    strategy_key: str,
    run_date: date,
) -> BrokerOrderRequest | None:
    has_order_args = any(
        [
            args.check_order_code is not None,
            args.check_order_price is not None,
            args.check_order_volume is not None,
        ]
    )
    if not has_order_args:
        return None

    missing_fields = [
        field_name
        for field_name, value in [
            ("check_order_code", args.check_order_code),
            ("check_order_price", args.check_order_price),
            ("check_order_volume", args.check_order_volume),
        ]
        if value is None
    ]
    if missing_fields:
        raise ValueError(
            "broker-check 测试单参数不完整，缺少："
            + ", ".join(missing_fields)
        )
    if args.check_order_price <= 0:
        raise ValueError("broker-check 测试单必须提供大于 0 的限价 price")
    if args.check_order_volume <= 0:
        raise ValueError("broker-check 测试单必须提供大于 0 的 volume")

    return BrokerOrderRequest(
        order_id=f"broker-check-{uuid.uuid4().hex}",
        instance_id=instance_id,
        strategy_key=strategy_key,
        code=args.check_order_code,
        direction=Direction(args.check_order_direction),
        signal_date=run_date,
        execute_at="open",
        planned_execute_date=run_date,
        price=args.check_order_price,
        volume=args.check_order_volume,
        reason=args.check_order_reason,
    )


def run_broker_check(
    broker,
    args,
    instance_id: str,
    strategy_key: str,
    run_date: date,
) -> dict:
    if not isinstance(broker, QmtBroker):
        raise ValueError("broker-check 目前只支持 QMT / miniQMT broker")

    test_order_request = build_broker_check_request(
        args=args,
        instance_id=instance_id,
        strategy_key=strategy_key,
        run_date=run_date,
    )
    return broker.run_diagnostics(test_order_request=test_order_request)


def run_reconcile(
    broker,
    instance_id: str,
) -> dict:
    return reconcile_live_state(
        instance_id=instance_id,
        broker=broker,
    )


def send_email_safe(notifier, subject: str, body: str):
    if not notifier:
        return
    try:
        notifier.notify(subject, body)
    except Exception as e:
        logger.error(f"邮件通知发送失败: {e}")


def format_summary_email(summary: dict) -> tuple[str, str]:
    subject = f"[Apex][Live][Summary] {summary['strategy']} {summary['run_date']}"
    body = (
        f"实例ID: {summary['instance_id']}\n"
        f"策略: {summary['strategy']}\n"
        f"Broker: {summary['broker']}\n"
        f"运行日期: {summary['run_date']}\n"
        f"激活计划单: {summary['planned_orders_activated']}\n"
        f"计划单失败: {summary['planned_orders_failed']}\n"
        f"生成信号: {summary['signals_generated']}\n"
        f"构建委托: {summary['orders_built']}\n"
        f"风控拦截: {summary.get('orders_risk_rejected', 0)}\n"
        f"提交成功: {summary['orders_submitted']}\n"
        f"提交失败: {summary.get('orders_broker_rejected', summary['orders_rejected'])}\n"
        f"账户总资产: {summary['total_equity']:.2f}\n"
        f"可用现金: {summary['cash']:.2f}\n"
        f"持仓数量: {summary['position_count']}\n"
    )
    return subject, body


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
    parser.add_argument("--broker-check", action="store_true",
                        help="只执行 QMT / miniQMT 联调诊断，不进入策略执行")
    parser.add_argument("--reconcile", action="store_true",
                        help="只执行 live 本地状态与 broker 状态只读对账，不进入策略执行")
    parser.add_argument("--check-order-code", default=None,
                        help="可选：broker-check 测试单股票代码")
    parser.add_argument("--check-order-price", type=float, default=None,
                        help="可选：broker-check 测试单限价")
    parser.add_argument("--check-order-volume", type=int, default=None,
                        help="可选：broker-check 测试单数量")
    parser.add_argument("--check-order-direction", default="BUY", choices=["BUY", "SELL"],
                        help="可选：broker-check 测试单方向")
    parser.add_argument("--check-order-reason", default="broker-check",
                        help="可选：broker-check 测试单备注")
    args = parser.parse_args()

    setup_logging()
    init_db()
    notifier = EmailNotifier.from_config()

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

    if args.broker_check and args.reconcile:
        raise ValueError("--broker-check 与 --reconcile 不能同时使用")

    if args.broker_check:
        result = run_broker_check(
            broker=broker,
            args=args,
            instance_id=instance_id,
            strategy_key=args.strategy,
            run_date=run_date,
        )
        print_broker_check_summary(result)
        return

    if args.reconcile:
        report = run_reconcile(
            broker=broker,
            instance_id=instance_id,
        )
        print_reconcile_summary(report)
        return

    engine = LiveEngine(
        strategy=strategy,
        stock_codes=args.codes,
        broker=broker,
        instance_id=instance_id,
        strategy_key=args.strategy,
        notifier=notifier,
        run_date=run_date,
    )
    try:
        summary = engine.run_daily()
    except Exception as e:
        send_email_safe(
            notifier,
            subject=f"[Apex][Live][Fatal] {args.strategy} {run_date}",
            body=(
                f"实例ID: {instance_id}\n"
                f"策略: {args.strategy}\n"
                f"Broker: mode={args.mode}, provider={args.provider}\n"
                f"运行日期: {run_date}\n"
                f"错误: {e}\n"
            ),
        )
        raise

    print_summary(summary)
    if summary:
        subject, body = format_summary_email(summary)
        send_email_safe(notifier, subject, body)


if __name__ == "__main__":
    main()
