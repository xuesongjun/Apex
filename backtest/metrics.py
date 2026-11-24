"""
回测绩效评估指标
计算各类收益、风险、交易统计指标
"""
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class BacktestMetrics:
    """回测绩效指标"""
    # 收益指标
    total_return: float          # 总收益率 (%)
    annual_return: float         # 年化收益率 (%)
    benchmark_return: float      # 基准收益率 (%)
    alpha: float                 # Alpha（超额收益）
    beta: float                  # Beta

    # 风险指标
    max_drawdown: float          # 最大回撤 (%)
    max_drawdown_duration: int   # 最大回撤持续天数
    annual_volatility: float     # 年化波动率 (%)
    sharpe_ratio: float          # Sharpe 比率
    sortino_ratio: float         # Sortino 比率
    calmar_ratio: float          # Calmar 比率

    # 交易指标
    total_trades: int            # 总交易次数
    win_count: int               # 盈利次数
    lose_count: int              # 亏损次数
    win_rate: float              # 胜率 (%)
    profit_loss_ratio: float     # 盈亏比
    avg_holding_days: float      # 平均持仓天数
    max_consecutive_wins: int    # 最大连续盈利次数
    max_consecutive_losses: int  # 最大连续亏损次数

    # 费用
    total_commission: float      # 总手续费
    total_tax: float             # 总印花税


# A股年交易日数量（用于年化计算）
ANNUAL_TRADING_DAYS = 242
# 无风险利率（十年期国债收益率，近似值）
RISK_FREE_RATE = 0.025


def calculate_metrics(
    equity_curve: list[dict],
    trades: list[dict],
    benchmark_returns: pd.Series = None,
    total_commission: float = 0.0,
    total_tax: float = 0.0,
    initial_capital: float | None = None,
) -> BacktestMetrics:
    """
    计算回测绩效指标

    参数:
        equity_curve: 每日资产记录 [{"date": ..., "total_equity": ...}, ...]
        trades: 交易记录 [{"code": ..., "direction": ..., "profit": ..., "holding_days": ...}, ...]
        benchmark_returns: 基准日收益率序列
        total_commission: 总手续费
        total_tax: 总印花税
    """
    if not equity_curve:
        return _empty_metrics(total_commission, total_tax)

    df = pd.DataFrame(equity_curve)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    equity = df["total_equity"].values
    initial = initial_capital if initial_capital and initial_capital > 0 else equity[0]
    final = equity[-1]
    trading_days = len(equity)

    # ========== 收益指标 ==========
    total_return = (final - initial) / initial * 100

    # 年化收益率
    years = trading_days / ANNUAL_TRADING_DAYS
    if years > 0 and final > 0:
        annual_return = (pow(final / initial, 1 / years) - 1) * 100
    else:
        annual_return = 0.0

    # 日收益率序列
    daily_returns = pd.Series(equity).pct_change().dropna()

    # 基准相关指标
    benchmark_return = 0.0
    alpha = 0.0
    beta = 0.0
    if benchmark_returns is not None and len(benchmark_returns) > 0:
        benchmark_return = (
            (1 + benchmark_returns).prod() - 1
        ) * 100
        # Beta = Cov(策略, 基准) / Var(基准)
        if len(daily_returns) == len(benchmark_returns):
            cov = np.cov(daily_returns, benchmark_returns)
            if cov.shape == (2, 2) and cov[1, 1] > 0:
                beta = cov[0, 1] / cov[1, 1]
        alpha = annual_return - (
            RISK_FREE_RATE * 100 + beta * (benchmark_return - RISK_FREE_RATE * 100)
        )

    # ========== 风险指标 ==========

    # 最大回撤
    max_drawdown, max_dd_duration = _calc_max_drawdown(equity)

    # 年化波动率
    if len(daily_returns) > 1:
        annual_volatility = daily_returns.std() * math.sqrt(ANNUAL_TRADING_DAYS) * 100
    else:
        annual_volatility = 0.0

    # Sharpe 比率
    daily_rf = RISK_FREE_RATE / ANNUAL_TRADING_DAYS
    if annual_volatility > 0:
        sharpe_ratio = (annual_return / 100 - RISK_FREE_RATE) / (annual_volatility / 100)
    else:
        sharpe_ratio = 0.0

    # Sortino 比率（只看下行波动率）
    downside = daily_returns[daily_returns < daily_rf]
    if len(downside) > 0:
        downside_std = downside.std() * math.sqrt(ANNUAL_TRADING_DAYS)
        sortino_ratio = (annual_return / 100 - RISK_FREE_RATE) / downside_std if downside_std > 0 else 0.0
    else:
        sortino_ratio = 0.0

    # Calmar 比率
    calmar_ratio = annual_return / abs(max_drawdown) if max_drawdown != 0 else 0.0

    # ========== 交易指标 ==========
    sell_trades = [t for t in trades if t.get("profit") is not None]
    total_trades = len(sell_trades)
    wins = [t for t in sell_trades if t.get("profit", 0) > 0]
    losses = [t for t in sell_trades if t.get("profit", 0) <= 0]
    win_count = len(wins)
    lose_count = len(losses)
    win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0.0

    # 盈亏比
    avg_win = np.mean([t["profit"] for t in wins]) if wins else 0.0
    avg_loss = abs(np.mean([t["profit"] for t in losses])) if losses else 1.0
    profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0

    # 平均持仓天数
    holding_days_list = [t.get("holding_days", 0) for t in sell_trades]
    avg_holding_days = np.mean(holding_days_list) if holding_days_list else 0.0

    # 连续盈亏
    max_consec_wins, max_consec_losses = _calc_consecutive(sell_trades)

    return BacktestMetrics(
        total_return=round(total_return, 2),
        annual_return=round(annual_return, 2),
        benchmark_return=round(benchmark_return, 2),
        alpha=round(alpha, 2),
        beta=round(beta, 3),
        max_drawdown=round(max_drawdown, 2),
        max_drawdown_duration=max_dd_duration,
        annual_volatility=round(annual_volatility, 2),
        sharpe_ratio=round(sharpe_ratio, 3),
        sortino_ratio=round(sortino_ratio, 3),
        calmar_ratio=round(calmar_ratio, 3),
        total_trades=total_trades,
        win_count=win_count,
        lose_count=lose_count,
        win_rate=round(win_rate, 2),
        profit_loss_ratio=round(profit_loss_ratio, 2),
        avg_holding_days=round(avg_holding_days, 1),
        max_consecutive_wins=max_consec_wins,
        max_consecutive_losses=max_consec_losses,
        total_commission=round(total_commission, 2),
        total_tax=round(total_tax, 2),
    )


def _calc_max_drawdown(equity: np.ndarray) -> tuple[float, int]:
    """
    计算最大回撤及持续天数

    返回:
        (最大回撤百分比, 持续天数)
    """
    if len(equity) < 2:
        return 0.0, 0

    peak = equity[0]
    max_dd = 0.0
    dd_start = 0
    max_dd_duration = 0
    current_dd_start = 0

    for i in range(1, len(equity)):
        if equity[i] > peak:
            peak = equity[i]
            current_dd_start = i
        else:
            dd = (peak - equity[i]) / peak * 100
            if dd > max_dd:
                max_dd = dd
                max_dd_duration = i - current_dd_start

    return max_dd, max_dd_duration


def _calc_consecutive(trades: list[dict]) -> tuple[int, int]:
    """计算最大连续盈利和连续亏损次数"""
    if not trades:
        return 0, 0

    max_wins = 0
    max_losses = 0
    current_wins = 0
    current_losses = 0

    for t in trades:
        if t.get("profit", 0) > 0:
            current_wins += 1
            current_losses = 0
            max_wins = max(max_wins, current_wins)
        else:
            current_losses += 1
            current_wins = 0
            max_losses = max(max_losses, current_losses)

    return max_wins, max_losses


def _empty_metrics(commission: float, tax: float) -> BacktestMetrics:
    """返回空的绩效指标"""
    return BacktestMetrics(
        total_return=0, annual_return=0, benchmark_return=0,
        alpha=0, beta=0, max_drawdown=0, max_drawdown_duration=0,
        annual_volatility=0, sharpe_ratio=0, sortino_ratio=0, calmar_ratio=0,
        total_trades=0, win_count=0, lose_count=0, win_rate=0,
        profit_loss_ratio=0, avg_holding_days=0,
        max_consecutive_wins=0, max_consecutive_losses=0,
        total_commission=commission, total_tax=tax,
    )
