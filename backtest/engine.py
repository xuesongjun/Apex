"""
回测引擎
核心模块：加载历史数据 → 按时间回放 → 驱动策略产生信号 → 撮合成交 → 记录结果
"""
from datetime import date, timedelta
from typing import Optional

import pandas as pd
from loguru import logger

from backtest.account import Account
from backtest.fee import FeeModel
from backtest.metrics import BacktestMetrics, calculate_metrics
from backtest.rules import TradingRules
from config import BacktestConfig
from data.storage.repository import StockRepository
from strategy.base import BarData, BaseStrategy, Direction, OrderData, Signal


class BacktestEngine:
    """
    回测引擎

    用法:
        engine = BacktestEngine(
            strategy=MyStrategy(config),
            stock_codes=["000001", "600519"],
            start_date=date(2023, 1, 1),
            end_date=date(2024, 12, 31),
        )
        result = engine.run()
        result.print_summary()
    """

    def __init__(
        self,
        strategy: BaseStrategy,
        stock_codes: list[str],
        start_date: date,
        end_date: date,
        initial_capital: float = None,
        slippage: float = None,
    ):
        self.strategy = strategy
        self.stock_codes = stock_codes
        self.start_date = start_date
        self.end_date = end_date
        self.slippage = slippage or BacktestConfig.slippage

        capital = initial_capital or BacktestConfig.initial_capital
        self.account = Account(capital)
        self.repo = StockRepository()

        # 交易记录
        self._trades: list[dict] = []
        self._orders: list[OrderData] = []
        # 买入记录（用于计算卖出盈亏）
        self._buy_records: dict[str, list[dict]] = {}

    def run(self) -> "BacktestResult":
        """
        运行回测

        流程：
        1. 加载历史数据
        2. 按交易日遍历
        3. 每个交易日：更新持仓价格 → 推送K线给策略 → 处理信号 → 记录资产
        """
        logger.info("=" * 60)
        logger.info(f"回测开始: {self.strategy.name}")
        logger.info(f"股票池: {len(self.stock_codes)} 只")
        logger.info(f"区间: {self.start_date} ~ {self.end_date}")
        logger.info(f"初始资金: {self.account.initial_capital:,.0f}")
        logger.info("=" * 60)

        # 加载数据
        all_bars = self._load_data()
        if not all_bars:
            logger.error("无可用的历史数据")
            return BacktestResult.empty(self.strategy.name)

        # 获取所有交易日
        trade_dates = sorted(all_bars.keys())
        logger.info(f"共 {len(trade_dates)} 个交易日")

        # 策略启动
        self.strategy.on_start()

        # 按交易日回放
        for i, td in enumerate(trade_dates):
            # 新交易日：T+1 解冻
            self.account.new_trading_day(td)

            bars_today = all_bars[td]
            signals: list[Signal] = []

            # 构建当日 K 线字典（code → bar），price_map 顺带生成
            bar_map: dict[str, BarData] = {bar.code: bar for bar in bars_today}
            self.account.update_prices({code: bar.close for code, bar in bar_map.items()})

            # 同步账户状态给策略
            self.strategy._sync_account(
                self.account.positions.copy(),
                self.account.cash,
                self.account.total_equity,
            )

            # 推送K线给策略，收集信号
            for bar in bars_today:
                self.strategy._update_bar(bar)
                signal = self.strategy.on_bar(bar)
                if signal is not None:
                    signals.append(signal)

            # 处理信号（先卖后买，释放资金）
            sell_signals = [s for s in signals if s.direction == Direction.SELL]
            buy_signals = [s for s in signals if s.direction == Direction.BUY]

            for signal in sell_signals:
                self._process_signal(signal, bar_map)
            for signal in buy_signals:
                self._process_signal(signal, bar_map)

            # 记录当日资产
            self.account.record_equity(td)

            # 进度日志
            if (i + 1) % 100 == 0:
                logger.info(
                    f"回测进度: {i + 1}/{len(trade_dates)}, "
                    f"资产: {self.account.total_equity:,.0f}"
                )

        # 策略停止
        self.strategy.on_stop()

        # 生成结果
        result = self._build_result(trade_dates)
        logger.info("=" * 60)
        logger.info("回测完成!")
        logger.info("=" * 60)
        return result

    def _load_data(self) -> dict[date, list[BarData]]:
        """
        加载所有股票的历史数据，按交易日分组

        返回:
            {交易日: [该日所有股票的BarData]}
        """
        all_bars: dict[date, list[BarData]] = {}

        for code in self.stock_codes:
            df = self.repo.get_daily_bars(code, self.start_date, self.end_date)
            if df.empty:
                logger.warning(f"股票 {code} 无历史数据，跳过")
                continue

            for _, row in df.iterrows():
                bar = BarData(
                    code=code,
                    trade_date=row["trade_date"],
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    pre_close=row.get("pre_close", 0),
                    volume=row.get("volume", 0),
                    amount=row.get("amount", 0),
                    turnover=row.get("turnover", 0),
                    pct_change=row.get("pct_change", 0),
                )
                td = row["trade_date"]
                if td not in all_bars:
                    all_bars[td] = []
                all_bars[td].append(bar)

        return all_bars

    def _process_signal(self, signal: Signal, bar_map: dict[str, BarData]):
        """处理交易信号：验证 → 撮合 → 成交"""
        bar = bar_map.get(signal.code)
        if bar is None:
            return

        # 确定成交价格（模拟以开盘价成交 + 滑点）
        if signal.price <= 0:
            exec_price = bar.open
        else:
            exec_price = signal.price

        # 加入滑点
        if signal.direction == Direction.BUY:
            exec_price += self.slippage
        else:
            exec_price -= self.slippage
        exec_price = max(exec_price, 0.01)

        # 确定交易量
        volume = signal.volume
        if signal.direction == Direction.BUY and volume <= 0:
            # 自动计算买入量：用总资产的一定比例
            available = self.account.cash * 0.95  # 预留5%资金
            max_volume = int(available / exec_price)
            volume = TradingRules.round_volume(max_volume, Direction.BUY)
        elif signal.direction == Direction.SELL and volume <= 0:
            # 默认全部卖出
            pos = self.account.get_position(signal.code)
            volume = pos.available if pos else 0

        if volume <= 0:
            return

        # 获取持仓信息
        pos = self.account.get_position(signal.code)
        pos_volume = pos.volume if pos else 0
        pos_available = pos.available if pos else 0

        # 验证订单合法性
        valid, reason = TradingRules.validate_order(
            Signal(
                code=signal.code,
                direction=signal.direction,
                trade_date=signal.trade_date,
                price=exec_price,
                volume=volume,
            ),
            bar,
            self.account.cash,
            pos_volume,
            pos_available,
        )

        if not valid:
            logger.debug(f"订单拒绝: {signal.code} {signal.direction.value} - {reason}")
            return

        # 创建订单并成交
        order = OrderData(
            code=signal.code,
            direction=signal.direction,
            price=exec_price,
            volume=volume,
            trade_date=signal.trade_date,
        )

        if signal.direction == Direction.BUY:
            order = self.account.process_buy(order)
            if order.status == "filled":
                # 记录买入
                if signal.code not in self._buy_records:
                    self._buy_records[signal.code] = []
                self._buy_records[signal.code].append({
                    "date": signal.trade_date,
                    "price": exec_price,
                    "volume": volume,
                })
        else:
            # 计算卖出盈亏
            buy_info = self._buy_records.get(signal.code, [{}])
            buy_price = buy_info[-1].get("price", 0) if buy_info else 0
            buy_date = buy_info[-1].get("date", signal.trade_date) if buy_info else signal.trade_date

            order = self.account.process_sell(order)
            if order.status == "filled":
                profit = (exec_price - buy_price) * volume - order.commission
                holding_days = (signal.trade_date - buy_date).days
                self._trades.append({
                    "code": signal.code,
                    "direction": "SELL",
                    "buy_price": buy_price,
                    "sell_price": exec_price,
                    "volume": volume,
                    "profit": round(profit, 2),
                    "profit_pct": round((exec_price / buy_price - 1) * 100, 2) if buy_price > 0 else 0,
                    "holding_days": holding_days,
                    "buy_date": buy_date,
                    "sell_date": signal.trade_date,
                    "reason": signal.reason,
                })
                # 清除买入记录
                if signal.code in self._buy_records:
                    self._buy_records[signal.code].pop()

        self._orders.append(order)
        self.strategy.on_order(order)

    def _build_result(self, trade_dates: list[date]) -> "BacktestResult":
        """构建回测结果"""
        # 获取基准数据
        benchmark_returns = None
        benchmark_code = BacktestConfig.benchmark
        if benchmark_code:
            bench_df = self.repo.get_daily_bars(
                benchmark_code, self.start_date, self.end_date
            )
            if not bench_df.empty:
                benchmark_returns = bench_df["close"].pct_change().dropna()

        metrics = calculate_metrics(
            equity_curve=self.account.equity_curve,
            trades=self._trades,
            benchmark_returns=benchmark_returns,
            total_commission=self.account.total_commission,
            total_tax=self.account.total_tax,
        )

        return BacktestResult(
            strategy_name=self.strategy.name,
            start_date=self.start_date,
            end_date=self.end_date,
            metrics=metrics,
            equity_curve=self.account.equity_curve,
            trades=self._trades,
            orders=self._orders,
        )


class BacktestResult:
    """回测结果封装"""

    def __init__(
        self,
        strategy_name: str,
        start_date: date,
        end_date: date,
        metrics: BacktestMetrics,
        equity_curve: list[dict],
        trades: list[dict],
        orders: list[OrderData],
    ):
        self.strategy_name = strategy_name
        self.start_date = start_date
        self.end_date = end_date
        self.metrics = metrics
        self.equity_curve = equity_curve
        self.trades = trades
        self.orders = orders

    def print_summary(self):
        """打印回测摘要报告"""
        m = self.metrics

        # 获取期末账户数据
        final = self.equity_curve[-1] if self.equity_curve else {}
        initial_capital = self.equity_curve[0]["total_equity"] if self.equity_curve else 0
        final_equity = final.get("total_equity", 0)
        final_cash = final.get("cash", 0)
        final_market_value = final.get("market_value", 0)

        print("\n" + "=" * 60)
        print(f"  回测报告: {self.strategy_name}")
        print(f"  区间: {self.start_date} ~ {self.end_date}")
        print("=" * 60)

        print("\n【账户概览】")
        print(f"  初始资金:      {initial_capital:>14,.2f}")
        print(f"  期末总资产:    {final_equity:>14,.2f}")
        print(f"  期末现金:      {final_cash:>14,.2f}")
        print(f"  期末持仓市值:  {final_market_value:>14,.2f}")
        print(f"  总盈亏:        {final_equity - initial_capital:>+14,.2f}")

        print("\n【收益指标】")
        print(f"  总收益率:      {m.total_return:>10.2f}%")
        print(f"  年化收益率:    {m.annual_return:>10.2f}%")
        print(f"  基准收益率:    {m.benchmark_return:>10.2f}%")
        print(f"  Alpha:         {m.alpha:>10.2f}%")
        print(f"  Beta:          {m.beta:>10.3f}")

        print("\n【风险指标】")
        print(f"  最大回撤:      {m.max_drawdown:>10.2f}%")
        print(f"  回撤持续:      {m.max_drawdown_duration:>10d} 天")
        print(f"  年化波动率:    {m.annual_volatility:>10.2f}%")
        print(f"  Sharpe 比率:   {m.sharpe_ratio:>10.3f}")
        print(f"  Sortino 比率:  {m.sortino_ratio:>10.3f}")
        print(f"  Calmar 比率:   {m.calmar_ratio:>10.3f}")

        print("\n【交易统计】")
        print(f"  总交易次数:    {m.total_trades:>10d}")
        print(f"  盈利次数:      {m.win_count:>10d}")
        print(f"  亏损次数:      {m.lose_count:>10d}")
        print(f"  胜率:          {m.win_rate:>10.2f}%")
        print(f"  盈亏比:        {m.profit_loss_ratio:>10.2f}")
        print(f"  平均持仓天数:  {m.avg_holding_days:>10.1f}")
        print(f"  最大连盈:      {m.max_consecutive_wins:>10d}")
        print(f"  最大连亏:      {m.max_consecutive_losses:>10d}")

        print("\n【费用统计】")
        print(f"  总手续费:      {m.total_commission:>14,.2f}")
        print(f"  总印花税:      {m.total_tax:>14,.2f}")
        print(f"  费用合计:      {m.total_commission + m.total_tax:>14,.2f}")
        print("=" * 60 + "\n")

    def get_equity_df(self) -> pd.DataFrame:
        """获取资产曲线 DataFrame"""
        return pd.DataFrame(self.equity_curve)

    def get_trades_df(self) -> pd.DataFrame:
        """获取交易记录 DataFrame"""
        return pd.DataFrame(self.trades)

    @classmethod
    def empty(cls, strategy_name: str) -> "BacktestResult":
        """返回空结果"""
        from backtest.metrics import _empty_metrics
        return cls(
            strategy_name=strategy_name,
            start_date=date.today(),
            end_date=date.today(),
            metrics=_empty_metrics(0, 0),
            equity_curve=[],
            trades=[],
            orders=[],
        )
