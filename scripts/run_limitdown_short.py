#!/usr/bin/env python3
"""
跌停价卖出 + 尾盘买入策略回测

策略逻辑：
  在集合竞价阶段（9:15-9:25），以"竞价参考价 × (1-跌停幅度)"挂限价卖出委托。
  此挂单价格远低于当前竞价参考价，在集合竞价撮合规则下（限价≤清算价即成交），
  实际以竞价清算价（即开盘价）成交，而非以限价成交。
  本质上等价于：每日以开盘价卖出，以收盘价（模拟尾盘5分钟）买入。
  每个交易日必然产生一笔交易。

注意：
  本策略为纯理论回测，A股实盘不支持个股卖空操作。
  每笔交易的量以当前可用资金全仓计算（可通过 --shares 指定固定手数）。

用法：
  python scripts/run_limitdown_short.py --code 000001 --start 2023-01-01 --end 2024-12-31
  python scripts/run_limitdown_short.py --code 600519 --start 2023-01-01 --shares 1000
"""
import argparse
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── 终端对齐工具（中文字符占2列）─────────────────────────────────────
def _cw(s: str) -> int:
    """计算字符串的终端显示宽度（中文/全角占2列，ASCII占1列）"""
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

import numpy as np
import pandas as pd
from loguru import logger

from backtest.fee import FeeModel
from backtest.rules import TradingRules
from config import BacktestConfig, setup_logging
from data.storage.repository import StockRepository
from strategy.base import Direction


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def run_backtest(
    code: str,
    start_date: date,
    end_date: date,
    initial_capital: float = 1_000_000.0,
    fixed_shares: int = 0,
    show_all: bool = False,
    csv_path: str = "",
) -> dict:
    """
    执行跌停价卖出 + 尾盘买入策略回测

    成交条件：当日最低价 <= 跌停价，卖出委托才会成交。
    成交价格：卖出 = 跌停价；买入 = 收盘价（近似尾盘价）。

    参数：
        code          股票代码
        start_date    回测开始日期
        end_date      回测结束日期
        initial_capital 初始资金
        fixed_shares  固定每笔手数（股），0 表示全仓（按当日可用资金计算）
    """
    repo = StockRepository()
    fee_model = FeeModel()

    # 加载日K线数据
    df = repo.get_daily_bars(code, start_date, end_date)
    if df.empty:
        logger.error(f"股票 {code} 在 {start_date} ~ {end_date} 无数据，请先运行 init_db.py 拉取数据")
        return {}

    # 获取股票信息（用于判断涨跌停幅度和 ST 状态）
    stock_info = repo.get_stock_info(code)
    is_st = stock_info.is_st if stock_info else False
    stock_name = stock_info.name if stock_info else code

    # 去掉没有昨收价的行（通常是第一行）
    df = df.dropna(subset=["pre_close"])
    df = df[df["pre_close"] > 0].reset_index(drop=True)

    if df.empty:
        logger.error("清洗后无有效数据")
        return {}

    capital = initial_capital
    trades = []

    for _, bar in df.iterrows():
        open_price: float = bar["open"]
        close: float = bar["close"]
        trade_date = bar["trade_date"]

        # 集合竞价撮合规则：限价卖单（价格 = 竞价参考价的跌停价）在竞价阶段
        # 以清算价（开盘价）成交，因此实际卖出价 = 开盘价
        sell_price = open_price
        # 收盘前5分钟买入，以收盘价近似
        buy_price = close

        # 计算本次交易手数
        if fixed_shares > 0:
            volume = TradingRules.round_volume(fixed_shares, Direction.BUY)
        else:
            # 全仓：以跌停价估算最大可买手数（保留 5% 备用金）
            max_vol = int(capital * 0.95 / sell_price)
            volume = TradingRules.round_volume(max_vol, Direction.BUY)

        if volume <= 0:
            continue

        # 计算费用
        # 卖出（空头开仓）：佣金 + 印花税 + 过户费
        sell_fees = fee_model.calculate(sell_price, volume, Direction.SELL)
        # 买入（空头平仓）：佣金 + 过户费（无印花税）
        buy_fees = fee_model.calculate(buy_price, volume, Direction.BUY)
        total_fees = sell_fees.total + buy_fees.total

        # 单笔盈亏 = (卖价 - 买价) × 股数 - 总费用
        raw_pnl = (sell_price - buy_price) * volume
        pnl = raw_pnl - total_fees
        pnl_pct = (sell_price - buy_price) / sell_price * 100

        capital += pnl

        trades.append({
            "date": trade_date,
            "sell_price": sell_price,
            "buy_price": buy_price,
            "spread": round(sell_price - buy_price, 2),
            "spread_pct": round(pnl_pct, 2),
            "volume": volume,
            "total_fees": round(total_fees, 2),
            "raw_pnl": round(raw_pnl, 2),
            "pnl": round(pnl, 2),
            "capital": round(capital, 2),
        })

    # ————— 生成报告 —————
    result = _build_result(
        code=code,
        stock_name=stock_name,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        final_capital=capital,
        trades=trades,
        total_bars=len(df),
    )
    _print_report(result, show_all=show_all)
    if csv_path and result.get("trade_count", 0) > 0:
        _export_csv(result["trades_df"], csv_path)
    return result


def _build_result(
    code, stock_name, start_date, end_date,
    initial_capital, final_capital, trades, total_bars,
) -> dict:
    """计算回测统计指标"""
    if not trades:
        return {
            "code": code, "name": stock_name,
            "start_date": start_date, "end_date": end_date,
            "initial_capital": initial_capital, "final_capital": initial_capital,
            "total_bars": total_bars, "trade_count": 0,
        }

    tdf = pd.DataFrame(trades)
    wins = tdf[tdf["pnl"] > 0]
    losses = tdf[tdf["pnl"] <= 0]

    # 资产曲线日收益率（无交易日收益为 0）
    equity = [initial_capital] + tdf["capital"].tolist()
    equity_arr = np.array(equity)
    daily_returns = np.diff(equity_arr) / equity_arr[:-1]

    # 最大回撤
    peak = equity_arr[0]
    max_dd = 0.0
    for v in equity_arr[1:]:
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100
        if dd > max_dd:
            max_dd = dd

    # 年化收益（以交易次数估算）
    trading_days = total_bars
    total_return = (final_capital - initial_capital) / initial_capital * 100
    years = trading_days / 242
    annual_return = (pow(final_capital / initial_capital, 1 / years) - 1) * 100 if years > 0 else 0.0

    # Sharpe（无风险利率 2.5%）
    if len(daily_returns) > 1 and daily_returns.std() > 0:
        annual_vol = daily_returns.std() * np.sqrt(242) * 100
        sharpe = (annual_return - 2.5) / annual_vol
    else:
        annual_vol = 0.0
        sharpe = 0.0

    return {
        "code": code,
        "name": stock_name,
        "start_date": start_date,
        "end_date": end_date,
        "initial_capital": initial_capital,
        "final_capital": round(final_capital, 2),
        "total_return": round(total_return, 2),
        "annual_return": round(annual_return, 2),
        "max_drawdown": round(max_dd, 2),
        "annual_volatility": round(annual_vol, 2),
        "sharpe_ratio": round(sharpe, 3),
        "total_bars": total_bars,
        "trade_count": len(trades),
        "win_count": len(wins),
        "lose_count": len(losses),
        "win_rate": round(len(wins) / len(trades) * 100, 2),
        "avg_pnl": round(tdf["pnl"].mean(), 2),
        "avg_pnl_pct": round(tdf["spread_pct"].mean(), 2),
        "max_win": round(tdf["pnl"].max(), 2),
        "max_loss": round(tdf["pnl"].min(), 2),
        "total_fees": round(tdf["total_fees"].sum(), 2),
        # 开盘 > 收盘（当日下跌，空头盈利）
        "open_gt_close_days": int((tdf["sell_price"] > tdf["buy_price"]).sum()),
        # 开盘 < 收盘（当日上涨，空头亏损）
        "open_lt_close_days": int((tdf["sell_price"] <= tdf["buy_price"]).sum()),
        "avg_spread": round((tdf["sell_price"] - tdf["buy_price"]).mean(), 4),
        "trades_df": tdf,
    }


def _export_csv(tdf: pd.DataFrame, path: str):
    """导出每日交易明细到 CSV"""
    out = tdf[["date", "sell_price", "buy_price", "spread_pct", "volume",
               "total_fees", "raw_pnl", "pnl", "capital"]].copy()
    out.columns = ["日期", "开盘价(卖出)", "收盘价(买入)", "价差%",
                   "手数", "手续费", "毛盈亏", "净盈亏", "累计资金"]
    out.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"\n[已导出] 全部 {len(out)} 笔交易明细 → {path}")


def _print_report(r: dict, show_all: bool = False):
    if r.get("trade_count", 0) == 0:
        print(f"\n股票 {r['code']}（{r.get('name', '')}）")
        print(f"区间 {r['start_date']} ~ {r['end_date']} 共 {r['total_bars']} 个交易日")
        print("未触及任何跌停，策略无交易发生。\n")
        return

    W = 66
    print("\n" + "=" * W)
    print(f"  回测报告：开盘卖出 + 尾盘买入（理论做空）")
    print(f"  股票: {r['code']} {r['name']}  |  {r['start_date']} ~ {r['end_date']}")
    print("=" * W)

    # 标签统一用 _ljust 对齐（显示宽度14）
    LW, VW = 14, 14
    def kv(label, value):
        print(f"  {_ljust(label, LW)}{value}")

    print("\n【资金概览】")
    kv("初始资金",      f"{r['initial_capital']:>{VW},.2f}")
    kv("期末资金",      f"{r['final_capital']:>{VW},.2f}")
    kv("总盈亏",        f"{r['final_capital'] - r['initial_capital']:>+{VW},.2f}")
    kv("总收益率",      f"{r['total_return']:>+{VW-4}.2f}%")
    kv("年化收益率",    f"{r['annual_return']:>+{VW-4}.2f}%")
    kv("最大回撤",      f"{r['max_drawdown']:>{VW-4}.2f}%")
    kv("年化波动率",    f"{r['annual_volatility']:>{VW-4}.2f}%")
    kv("Sharpe 比率",   f"{r['sharpe_ratio']:>{VW-4}.3f}")

    print("\n【交易统计】")
    kv("总交易日",      f"{r['total_bars']:>{VW}d}")
    kv("胜率",          f"{r['win_rate']:>{VW-4}.2f}%")
    kv("盈利天数",      f"{r['win_count']:>{VW}d}  （开盘 > 收盘）")
    kv("亏损天数",      f"{r['lose_count']:>{VW}d}  （开盘 ≤ 收盘）")
    kv("平均单笔盈亏",  f"{r['avg_pnl']:>+{VW},.2f}")
    kv("平均开收价差",  f"{r['avg_pnl_pct']:>+{VW-4}.2f}%")
    kv("最大单笔盈利",  f"{r['max_win']:>+{VW},.2f}")
    kv("最大单笔亏损",  f"{r['max_loss']:>+{VW},.2f}")
    kv("总手续费",      f"{r['total_fees']:>{VW},.2f}")

    print("\n【开收价差分析】")
    kv("当日下跌天数",  f"{r['open_gt_close_days']:>{VW}d}  （开 > 收，空头盈利）")
    kv("当日上涨天数",  f"{r['open_lt_close_days']:>{VW}d}  （开 ≤ 收，空头亏损）")
    kv("平均开收价差",  f"{r['avg_spread']:>+{VW}.4f} 元")

    # 明细表（列宽均为终端显示宽度）
    # 列：日期12  开盘8  收盘8  价差%9  手数10  盈亏12  累计资金14
    C = [12, 8, 8, 9, 10, 12, 14]
    SEP = "  "
    tdf: pd.DataFrame = r["trades_df"]
    display_rows = tdf if show_all else tdf.tail(10)
    label = f"全部 {len(tdf)}" if show_all else f"最近 {min(10, len(tdf))}"
    print(f"\n【{label} 笔交易明细】")
    header = SEP.join([
        _ljust("日期",   C[0]),
        _rjust("开盘价", C[1]),
        _rjust("收盘价", C[2]),
        _rjust("价差%",  C[3]),
        _rjust("手数",   C[4]),
        _rjust("盈亏",   C[5]),
        _rjust("累计资金", C[6]),
    ])
    total_w = sum(C) + len(SEP) * (len(C) - 1)
    print(f"  {header}")
    print(f"  {'─' * total_w}")
    for _, row in display_rows.iterrows():
        line = SEP.join([
            _ljust(str(row['date']),                   C[0]),
            _rjust(f"{row['sell_price']:.2f}",         C[1]),
            _rjust(f"{row['buy_price']:.2f}",          C[2]),
            _rjust(f"{row['spread_pct']:+.2f}%",       C[3]),
            _rjust(f"{row['volume']:,}",               C[4]),
            _rjust(f"{row['pnl']:+,.2f}",              C[5]),
            _rjust(f"{row['capital']:,.2f}",           C[6]),
        ])
        print(f"  {line}")

    print("=" * W + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="跌停价卖出 + 尾盘买入策略回测"
    )
    parser.add_argument("--code", required=True, help="股票代码，如 000001")
    parser.add_argument("--start", required=True, help="开始日期，格式 YYYY-MM-DD")
    parser.add_argument(
        "--end",
        default=date.today().strftime("%Y-%m-%d"),
        help="结束日期，默认今天",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=BacktestConfig.initial_capital,
        help=f"初始资金（默认 {BacktestConfig.initial_capital:,.0f}）",
    )
    parser.add_argument(
        "--shares",
        type=int,
        default=0,
        help="固定每笔手数（股），默认 0 = 全仓",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="show_all",
        help="显示全部交易日明细（默认只显示最近10笔）",
    )
    parser.add_argument(
        "--csv",
        default="",
        metavar="FILE",
        help="导出全部交易明细到 CSV 文件，如 --csv result.csv",
    )
    args = parser.parse_args()

    setup_logging()

    run_backtest(
        code=args.code,
        start_date=_parse_date(args.start),
        end_date=_parse_date(args.end),
        initial_capital=args.capital,
        fixed_shares=args.shares,
        show_all=args.show_all,
        csv_path=args.csv,
    )


if __name__ == "__main__":
    main()
