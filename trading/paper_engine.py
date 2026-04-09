"""
模拟盘每日运行引擎

每个交易日收盘后运行一次，完整流程：
    步骤1  加载/初始化账户，T+1 解冻
    步骤2  加载今日 K 线
    步骤3  执行昨日挂单（以今日开盘价成交）
    步骤4  更新持仓价格（今日收盘价）
    步骤5  保存账户状态
    步骤6  重建策略历史 K 线缓存，运行策略生成信号
    步骤7  将信号转为明日 pending 订单
    步骤8  记录今日净值快照
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Optional

from loguru import logger

from backtest.rules import TradingRules
from data.storage.repository import PaperRepository, StockRepository
from strategy.base import BarData, BaseStrategy, Direction, OrderData, Signal
from trading.paper_account import PaperAccount

# 策略重建历史缓存时，最多加载多少个交易日（足够大以覆盖所有指标周期）
_LOOKBACK_DAYS = 120


class PaperEngine:
    """
    模拟盘每日运行引擎

    用法（每日收盘后调用一次）：
        engine = PaperEngine(strategy, codes, initial_capital=1_000_000)
        summary = engine.run_daily()
    """

    def __init__(
        self,
        strategy: BaseStrategy,
        stock_codes: list[str],
        initial_capital: float = 1_000_000.0,
        run_date: Optional[date] = None,
    ):
        self.strategy = strategy
        self.stock_codes = stock_codes
        self.initial_capital = initial_capital
        self.run_date = run_date or date.today()

        self._repo = StockRepository()
        self._paper_repo = PaperRepository()
        # 账户名 = 策略名（同策略实例可共享同一账户，跨日恢复状态）
        self.strategy_name = strategy.name

    # ── 主入口 ────────────────────────────────────────────────────────────

    def run_daily(self) -> dict:
        """
        执行当日模拟盘流程，返回运行摘要字典。

        若当日不是交易日，或已经运行过（nav_exists），则跳过并返回空字典。
        """
        run_date = self.run_date

        # ── 守卫：非交易日跳过 ──
        if not self._repo.is_trade_date(run_date):
            logger.info(f"{run_date} 不是交易日，跳过")
            return {}

        # ── 守卫：防重复运行 ──
        if self._paper_repo.nav_exists(self.strategy_name, run_date):
            logger.warning(f"{run_date} 已运行过（{self.strategy_name}），跳过")
            return {}

        logger.info(f"=== 模拟盘运行 [{self.strategy_name}] {run_date} ===")

        # ── 步骤1：初始化账户，T+1 解冻 ──
        account = PaperAccount(self.strategy_name, self.initial_capital)
        account.load_or_create()
        account.new_trading_day(run_date)

        # ── 步骤2：加载今日 K 线 ──
        bar_map = self._load_bars(run_date)
        if not bar_map:
            logger.warning(f"{run_date} 所有标的均无行情数据，跳过")
            return {}

        # ── 步骤3：执行 pending 订单 ──
        exec_result = self._execute_pending_orders(account, bar_map, run_date)

        # ── 步骤4：更新持仓价格（收盘价） ──
        account.update_prices({code: bar.close for code, bar in bar_map.items()})

        # ── 步骤5：保存账户状态 ──
        account.save()

        # ── 步骤6：重建历史缓存，运行策略 ──
        self._rebuild_bar_history(run_date)
        signals = self._run_strategy(bar_map, account)

        # ── 步骤7a：当日执行（execute_at="open"/"close"）──
        intraday_signals = [s for s in signals if s.execute_at in ("open", "close")]
        pending_signals  = [s for s in signals if s.execute_at not in ("open", "close")]
        intraday_result  = self._execute_intraday_signals(intraday_signals, bar_map, account, run_date)

        # ── 步骤5b：当日信号执行后再保存一次 ──
        if intraday_signals:
            account.update_prices({code: bar.close for code, bar in bar_map.items()})
            account.save()

        # ── 步骤7b：生成明日 pending 订单（execute_at="next_open"）──
        next_date = self._next_trade_date(run_date)
        pending_count = self._create_pending_orders(pending_signals, bar_map, account, run_date, next_date)

        # ── 步骤8：记录净值快照 ──
        account.record_nav(run_date)

        total_filled = exec_result["filled"] + intraday_result["filled"]
        total_rejected = exec_result["rejected"] + intraday_result["rejected"]
        summary = {
            "run_date": run_date,
            "strategy": self.strategy_name,
            "orders_executed": exec_result["total"],
            "orders_filled": total_filled,
            "orders_cancelled": exec_result["cancelled"],
            "orders_rejected": total_rejected,
            "signals_generated": len(signals),
            "pending_for_tomorrow": pending_count,
            "cash": account.cash,
            "market_value": account.total_market_value,
            "total_equity": account.total_equity,
            "nav": account.total_equity / account.initial_capital,
            "position_count": len(account.positions),
        }
        logger.info(
            f"运行完成 | 执行订单 {total_filled}/{exec_result['total']} 笔成交 | "
            f"当日信号成交 {intraday_result['filled']} 笔 | "
            f"生成信号 {len(signals)} 个 | 明日挂单 {pending_count} 笔 | "
            f"总资产 {account.total_equity:,.2f}"
        )
        return summary

    # ── 步骤2：加载当日 K 线 ─────────────────────────────────────────────

    def _load_bars(self, trade_date: date) -> dict[str, BarData]:
        """加载各标的当日 K 线，返回 {code: BarData}，停牌标的不在其中"""
        bar_map: dict[str, BarData] = {}
        for code in self.stock_codes:
            df = self._repo.get_daily_bars(code, trade_date, trade_date)
            if df.empty:
                logger.debug(f"{code} {trade_date} 无数据（可能停牌）")
                continue
            row = df.iloc[0]
            bar_map[code] = BarData(
                code=code,
                trade_date=row["trade_date"],
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                pre_close=row.get("pre_close") or row["close"],
                volume=int(row.get("volume") or 0),
                amount=float(row.get("amount") or 0.0),
            )
        return bar_map

    # ── 步骤3：执行 pending 订单 ─────────────────────────────────────────

    def _execute_pending_orders(
        self,
        account: PaperAccount,
        bar_map: dict[str, BarData],
        run_date: date,
    ) -> dict:
        """
        以今日开盘价执行昨日策略生成的 pending 订单。

        拒绝条件：停牌 / 涨停买入 / 跌停卖出 / 资金不足 / T+1 违规
        """
        pending = self._paper_repo.get_pending_orders(self.strategy_name, run_date)
        result = {"total": len(pending), "filled": 0, "cancelled": 0, "rejected": 0}

        for order_row in pending:
            bar = bar_map.get(order_row.code)

            # 停牌
            if bar is None:
                self._paper_repo.update_paper_order(
                    order_row.order_id, "cancelled", reason="停牌，无法成交"
                )
                result["cancelled"] += 1
                continue

            exec_price = bar.open
            direction = Direction.BUY if order_row.direction == "BUY" else Direction.SELL
            limit_rate = TradingRules.get_price_limit(order_row.code)

            # 涨跌停检查（用 pre_close 计算理论涨跌停价）
            if bar.pre_close and bar.pre_close > 0:
                up_limit = round(bar.pre_close * (1 + limit_rate), 2)
                dn_limit = round(bar.pre_close * (1 - limit_rate), 2)
                if direction == Direction.BUY and abs(exec_price - up_limit) < 0.001:
                    self._paper_repo.update_paper_order(
                        order_row.order_id, "cancelled", reason="开盘涨停，买入无法成交"
                    )
                    result["cancelled"] += 1
                    continue
                if direction == Direction.SELL and abs(exec_price - dn_limit) < 0.001:
                    self._paper_repo.update_paper_order(
                        order_row.order_id, "cancelled", reason="开盘跌停，卖出无法成交"
                    )
                    result["cancelled"] += 1
                    continue

            # 构建 OrderData 并交给 account 处理
            od = OrderData(
                code=order_row.code,
                direction=direction,
                price=exec_price,
                volume=order_row.req_volume,
                trade_date=run_date,
                order_id=order_row.order_id,
            )
            if direction == Direction.BUY:
                od = account.process_buy(od)
            else:
                od = account.process_sell(od)

            self._paper_repo.update_paper_order(
                order_row.order_id,
                status=od.status,
                filled_price=od.filled_price,
                filled_volume=od.filled_volume,
                commission=od.commission,
                reason=od.reason,
            )
            if od.status == "filled":
                result["filled"] += 1
            else:
                result["rejected"] += 1

        return result

    # ── 步骤7a：当日执行信号（execute_at="open"/"close"）────────────────

    def _execute_intraday_signals(
        self,
        signals: list,
        bar_map: dict[str, BarData],
        account,
        run_date: date,
    ) -> dict:
        """
        立即执行 execute_at="open" 或 "close" 的信号（不生成 pending 订单）。

        execute_at="open"  → 以今日开盘价成交
        execute_at="close" → 以今日收盘价成交
        """
        result = {"total": len(signals), "filled": 0, "rejected": 0}

        # 先处理卖出，再处理买入（释放资金）
        for direction_filter in (Direction.SELL, Direction.BUY):
            for signal in signals:
                if signal.direction != direction_filter:
                    continue
                bar = bar_map.get(signal.code)
                if bar is None:
                    result["rejected"] += 1
                    continue

                exec_price = bar.open if signal.execute_at == "open" else bar.close

                # 解析委托量
                volume = self._resolve_volume(signal, account, bar_map)
                if volume <= 0:
                    logger.debug(f"当日信号跳过 {signal.code}：量为0")
                    result["rejected"] += 1
                    continue

                # T+1 检查（卖出）
                if signal.direction == Direction.SELL:
                    pos = account.positions.get(signal.code)
                    if not pos or pos.available <= 0:
                        logger.debug(f"当日卖出信号跳过 {signal.code}：T+1 限制")
                        result["rejected"] += 1
                        continue

                od = OrderData(
                    code=signal.code,
                    direction=signal.direction,
                    price=exec_price,
                    volume=volume,
                    trade_date=run_date,
                    order_id=uuid.uuid4().hex,
                    reason=signal.reason or "",
                )
                if signal.direction == Direction.BUY:
                    od = account.process_buy(od)
                else:
                    od = account.process_sell(od)

                # 持久化订单记录
                self._paper_repo.save_paper_order({
                    "order_id": od.order_id,
                    "strategy_name": self.strategy_name,
                    "code": signal.code,
                    "direction": signal.direction.value,
                    "signal_date": run_date,
                    "execute_date": run_date,
                    "status": od.status,
                    "req_volume": volume,
                    "reason": signal.reason or "",
                })
                if od.status == "filled":
                    self._paper_repo.update_paper_order(
                        od.order_id,
                        status="filled",
                        filled_price=od.filled_price,
                        filled_volume=od.filled_volume,
                        commission=od.commission,
                    )
                    result["filled"] += 1
                    logger.info(
                        f"当日信号成交 [{signal.execute_at}] "
                        f"{signal.direction.value} {signal.code} "
                        f"{od.filled_volume}股 @ {od.filled_price:.3f}"
                    )
                else:
                    result["rejected"] += 1

        return result

    # ── 步骤6：重建历史缓存，运行策略 ────────────────────────────────────

    def _rebuild_bar_history(self, run_date: date) -> None:
        """
        重建策略的 _bar_history 缓存（程序重启后内存清空，需从数据库重新加载）。
        只推送历史 K 线到缓存，不调用 on_bar()（不产生信号）。
        """
        from datetime import timedelta
        history_start = run_date - timedelta(days=_LOOKBACK_DAYS * 2)
        # 加载到昨天（run_date 的 K 线在 _run_strategy 中单独推送）
        history_end = run_date - timedelta(days=1)

        for code in self.stock_codes:
            df = self._repo.get_daily_bars(code, history_start, history_end)
            if df.empty:
                continue
            for _, row in df.iterrows():
                bar = BarData(
                    code=code,
                    trade_date=row["trade_date"],
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    pre_close=row.get("pre_close") or row["close"],
                    volume=int(row.get("volume") or 0),
                    amount=float(row.get("amount") or 0.0),
                )
                self.strategy._update_bar(bar)

    def _run_strategy(
        self, bar_map: dict[str, BarData], account: PaperAccount
    ) -> list[Signal]:
        """同步账户状态，推送今日 K 线，收集信号"""
        self.strategy._sync_account(
            account.positions, account.cash, account.total_equity
        )
        signals: list[Signal] = []
        for code in self.stock_codes:
            bar = bar_map.get(code)
            if bar is None:
                continue  # 停牌，不推送
            self.strategy._update_bar(bar)
            signal = self.strategy.on_bar(bar)
            if signal:
                signals.append(signal)
                logger.debug(f"信号：{signal.direction.value} {signal.code} 原因：{signal.reason}")
        return signals

    # ── 步骤7：生成明日 pending 订单 ─────────────────────────────────────

    def _create_pending_orders(
        self,
        signals: list[Signal],
        bar_map: dict[str, BarData],
        account: PaperAccount,
        signal_date: date,
        execute_date: Optional[date],
    ) -> int:
        """将今日信号转为明日 pending 订单，返回创建的订单数"""
        count = 0
        for signal in signals:
            volume = self._resolve_volume(signal, account, bar_map)
            if volume <= 0:
                logger.debug(f"跳过信号 {signal.code}：量为0（资金不足或无可卖持仓）")
                continue

            # 卖出 T+1 检查：available=0 的持仓不能挂卖单
            if signal.direction == Direction.SELL:
                pos = account.positions.get(signal.code)
                if not pos or pos.available <= 0:
                    logger.debug(f"跳过卖出信号 {signal.code}：T+1 限制，无可卖持仓")
                    continue

            self._paper_repo.save_paper_order({
                "order_id": uuid.uuid4().hex,
                "strategy_name": self.strategy_name,
                "code": signal.code,
                "direction": signal.direction.value,
                "signal_date": signal_date,
                "execute_date": execute_date,
                "status": "pending",
                "req_volume": volume,
                "reason": signal.reason or "",
            })
            count += 1
            logger.info(
                f"挂单 [{signal.direction.value}] {signal.code} {volume}股"
                f"，计划执行日：{execute_date}"
            )
        return count

    def _resolve_volume(
        self,
        signal: Signal,
        account: PaperAccount,
        bar_map: dict[str, BarData],
    ) -> int:
        """
        解析委托数量：
        - signal.volume > 0：使用策略指定量（四舍五入到100股整数倍）
        - signal.volume == 0 且买入：用账户 95% 可用现金估算最大量
        - signal.volume == 0 且卖出：默认全部可卖持仓
        """
        if signal.volume > 0:
            return TradingRules.round_volume(signal.volume, signal.direction)

        if signal.direction == Direction.BUY:
            bar = bar_map.get(signal.code)
            if bar is None or bar.close <= 0:
                return 0
            available_cash = account.cash * 0.95
            max_vol = int(available_cash / bar.close)
            return TradingRules.round_volume(max_vol, Direction.BUY)
        else:
            pos = account.positions.get(signal.code)
            return pos.available if pos else 0

    # ── 工具 ──────────────────────────────────────────────────────────────

    def _next_trade_date(self, current_date: date) -> Optional[date]:
        """获取 current_date 之后的第一个交易日"""
        # 向后最多查30个自然日，找到第一个交易日
        check = current_date + timedelta(days=1)
        for _ in range(30):
            if self._repo.is_trade_date(check):
                return check
            check += timedelta(days=1)
        return None
