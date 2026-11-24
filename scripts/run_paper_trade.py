"""
模拟盘运行入口

用法：
    # 首次初始化 + 每日运行（收盘后执行）
    python scripts/run_paper_trade.py --strategy ma_cross --codes 000001 600519 --capital 1000000

    # 查看账户当前状态（不运行策略）
    python scripts/run_paper_trade.py --strategy ma_cross --codes 000001 --status

    # 查看最近净值记录
    python scripts/run_paper_trade.py --strategy ma_cross --codes 000001 --history 30

    # 补跑历史日期
    python scripts/run_paper_trade.py --strategy ma_cross --codes 000001 --date 2024-03-15

    # 自定义策略参数
    python scripts/run_paper_trade.py --strategy ma_cross --codes 000001 \\
        --params short_period=5 long_period=20

cron 注册示例（每个工作日 15:30 运行）：
    30 15 * * 1-5  cd /path/to/Apex && .venv/bin/python scripts/run_paper_trade.py \\
                   --strategy ma_cross --codes 000001 600519
"""
import argparse
import sys
from datetime import date, datetime
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

from loguru import logger
from config import setup_logging
from data.models import init_db
from data.storage.repository import PaperRepository, StockRepository
from strategy.base import Direction
from strategy.registry import STRATEGY_REGISTRY, load_strategy
from trading.account_id import build_account_id
from trading.paper_account import PaperAccount
from trading.paper_engine import PaperEngine


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



# ── 输出工具（中文对齐）──────────────────────────────────────────────────

def _cw(s: str) -> int:
    w = 0
    for c in s:
        cp = ord(c)
        if (0x1100 <= cp <= 0x115F or 0x2E80 <= cp <= 0x9FFF
                or 0xAC00 <= cp <= 0xD7AF or 0xF900 <= cp <= 0xFAFF
                or 0xFE10 <= cp <= 0xFE6F or 0xFF00 <= cp <= 0xFF60
                or 0xFFE0 <= cp <= 0xFFE6):
            w += 2
        else:
            w += 1
    return w

def _ljust(s: str, width: int) -> str:
    return s + ' ' * max(0, width - _cw(s))

def _rjust(s: str, width: int) -> str:
    return ' ' * max(0, width - _cw(s)) + s


# ── 状态查看 ─────────────────────────────────────────────────────────────

def print_status(account_id: str, strategy_label: str):
    """打印账户当前状态、持仓和待执行订单"""
    repo = PaperRepository()
    stock_repo = StockRepository()

    account_row = repo.get_paper_account(account_id)
    if account_row is None:
        print(f"\n[错误] 账户 '{account_id}' 不存在，请先用相同策略/参数/股票列表运行一次")
        return

    positions = repo.get_paper_positions(account_id)
    pending = [o for o in repo.get_order_history(account_id) if o.status == "pending"]

    total_market_value = sum(
        p.volume * p.current_price for p in positions
    )
    total_equity = account_row.cash + total_market_value
    nav = total_equity / account_row.initial_capital

    W = 60
    print("\n" + "=" * W)
    print(f"  模拟盘账户状态：{strategy_label}")
    print(f"  账户ID：{account_id}")
    print("=" * W)

    print("\n【账户概览】")
    for label, value in [
        ("初始资金",   f"{account_row.initial_capital:>16,.2f}"),
        ("可用现金",   f"{account_row.cash:>16,.2f}"),
        ("持仓市值",   f"{total_market_value:>16,.2f}"),
        ("总资产",     f"{total_equity:>16,.2f}"),
        ("单位净值",   f"{nav:>16.4f}"),
        ("累计收益率", f"{(nav - 1) * 100:>+15.2f}%"),
        ("累计佣金",   f"{account_row.total_commission:>16,.2f}"),
    ]:
        print(f"  {_ljust(label, 10)}{value}")

    if positions:
        print(f"\n【当前持仓】（{len(positions)} 只）")
        C = [10, 8, 9, 9, 10, 12, 10]
        SEP = "  "
        header = SEP.join([
            _ljust("代码", C[0]), _rjust("份数", C[1]),
            _rjust("成本价", C[2]), _rjust("现价", C[3]),
            _rjust("可卖量", C[4]), _rjust("市值", C[5]),
            _rjust("浮动盈亏", C[6]),
        ])
        print(f"  {header}")
        print(f"  {'─' * (sum(C) + len(SEP) * (len(C) - 1))}")
        for pos in positions:
            mv = pos.volume * pos.current_price
            pnl = (pos.current_price - pos.cost_price) * pos.volume
            pnl_pct = (pos.current_price / pos.cost_price - 1) * 100 if pos.cost_price > 0 else 0
            line = SEP.join([
                _ljust(pos.code,                      C[0]),
                _rjust(f"{pos.volume:,}",             C[1]),
                _rjust(f"{pos.cost_price:.3f}",       C[2]),
                _rjust(f"{pos.current_price:.3f}",    C[3]),
                _rjust(f"{pos.available:,}",          C[4]),
                _rjust(f"{mv:,.2f}",                  C[5]),
                _rjust(f"{pnl:+,.2f}({pnl_pct:+.1f}%)", C[6]),
            ])
            print(f"  {line}")
    else:
        print("\n【当前持仓】无持仓")

    if pending:
        print(f"\n【待执行订单】（{len(pending)} 笔，下一交易日开盘执行）")
        for o in pending:
            print(f"  {o.direction:4s}  {o.code}  {o.req_volume:,}股  "
                  f"执行日：{o.execute_date}  原因：{o.reason or '-'}")
    else:
        print("\n【待执行订单】无")

    print("=" * W)


def print_history(account_id: str, strategy_label: str, days: int):
    """打印最近 N 天的净值记录"""
    repo = PaperRepository()
    nav_series = repo.get_nav_series(account_id)
    if not nav_series:
        print(f"\n账户 '{account_id}' 无净值记录")
        return

    rows = nav_series[-days:]
    account_row = repo.get_paper_account(account_id)
    initial = account_row.initial_capital if account_row else 1.0

    W = 72
    print(f"\n净值记录：{strategy_label}（最近 {len(rows)} 条，共 {len(nav_series)} 条）")
    print(f"账户ID：{account_id}")
    print("─" * W)
    C = [12, 12, 12, 10, 10, 10, 8]
    SEP = "  "
    header = SEP.join([
        _ljust("日期", C[0]), _rjust("总资产", C[1]),
        _rjust("可用现金", C[2]), _rjust("持仓市值", C[3]),
        _rjust("单位净值", C[4]), _rjust("当日盈亏", C[5]),
        _rjust("持仓数", C[6]),
    ])
    print(f"  {header}")
    print(f"  {'─' * (sum(C) + len(SEP) * (len(C) - 1))}")
    for r in rows:
        line = SEP.join([
            _ljust(str(r.trade_date),          C[0]),
            _rjust(f"{r.total_equity:,.2f}",   C[1]),
            _rjust(f"{r.cash:,.2f}",           C[2]),
            _rjust(f"{r.market_value:,.2f}",   C[3]),
            _rjust(f"{r.nav:.4f}",             C[4]),
            _rjust(f"{r.daily_pnl:+,.2f}",     C[5]),
            _rjust(str(r.position_count),      C[6]),
        ])
        print(f"  {line}")
    print("─" * W)


def print_summary(summary: dict):
    """打印每日运行摘要"""
    if not summary:
        return
    W = 60
    nav = summary.get("nav", 1.0)
    print("\n" + "=" * W)
    print(f"  模拟盘日报：{summary['strategy']}  {summary['run_date']}")
    print(f"  账户ID：{summary['account_id']}")
    print("=" * W)
    print(f"\n  今日执行：{summary['orders_filled']} 笔成交 / "
          f"{summary['orders_cancelled']} 笔取消 / "
          f"{summary['orders_rejected']} 笔拒绝")
    print(f"  生成信号：{summary['signals_generated']} 个  "
          f"明日挂单：{summary['pending_for_tomorrow']} 笔")
    print(f"\n  总资产：  {summary['total_equity']:>14,.2f}")
    print(f"  可用现金：{summary['cash']:>14,.2f}")
    print(f"  持仓市值：{summary['market_value']:>14,.2f}")
    print(f"  单位净值：{nav:>14.4f}   累计收益：{(nav-1)*100:>+.2f}%")
    print("=" * W)


# ── 主函数 ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="A股模拟盘交易")
    parser.add_argument("--strategy", "-s", required=True,
                        help=f"策略名称：{', '.join(STRATEGY_REGISTRY.keys())}")
    parser.add_argument("--codes", "-c", nargs="+", required=True,
                        help="股票代码（空格分隔）")
    parser.add_argument("--capital", type=float, default=1_000_000,
                        help="初始资金（仅首次创建账户时有效，默认 100 万）")
    parser.add_argument("--date", default=None,
                        help="指定运行日期（默认今天），格式 YYYY-MM-DD，可用于补跑历史")
    parser.add_argument("--params", nargs="*",
                        help="策略参数 key=value 格式")
    parser.add_argument("--status", action="store_true",
                        help="只查看账户状态，不运行策略")
    parser.add_argument("--history", type=int, default=0, metavar="N",
                        help="查看最近 N 天净值记录")
    args = parser.parse_args()

    setup_logging()
    init_db()  # 确保含新增的4张模拟盘表都已建好

    params = parse_params(args.params)
    strategy = load_strategy(args.strategy, params)
    account_id = build_account_id(args.strategy, args.codes, params)

    if args.status:
        print_status(account_id, strategy.name)
        return

    if args.history > 0:
        print_history(account_id, strategy.name, args.history)
        return

    run_date = (
        datetime.strptime(args.date, "%Y-%m-%d").date()
        if args.date else date.today()
    )

    engine = PaperEngine(
        strategy=strategy,
        stock_codes=args.codes,
        initial_capital=args.capital,
        run_date=run_date,
        account_id=account_id,
    )
    summary = engine.run_daily()
    print_summary(summary)


if __name__ == "__main__":
    main()
