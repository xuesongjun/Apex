"""
数据存储层
封装数据库 CRUD 操作，提供数据读写的统一接口
"""
from datetime import date
from typing import Optional

import pandas as pd
from loguru import logger
from sqlalchemy import select, func
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import json
import uuid

from data.models import (
    AdjFactor,
    IndexDaily,
    LiveAccount as LiveAccountORM,
    LiveOrder as LiveOrderORM,
    LivePosition as LivePositionORM,
    PaperAccount as PaperAccountORM,
    PaperNav,
    PaperOrder as PaperOrderORM,
    PaperPosition as PaperPositionORM,
    StockBasic,
    StockDaily,
    StockFinance,
    TradeCalendar,
    get_session,
)


class StockRepository:
    """股票数据仓库，封装所有数据库操作"""

    # ========== 股票基础信息 ==========

    def upsert_stock_list(self, df: pd.DataFrame) -> int:
        """
        更新或插入股票列表（批量 upsert）
        返回影响的行数
        """
        if df.empty:
            return 0

        records = [
            {
                "code": row["code"],
                "name": row.get("name", ""),
                "market": row.get("market", ""),
                "board": row.get("board", "main"),
                "industry": row.get("industry", ""),
                "list_date": row.get("list_date"),
                "is_st": bool(row.get("is_st", False)),
            }
            for _, row in df.iterrows()
        ]

        session = get_session()
        try:
            stmt = sqlite_insert(StockBasic).values(records)
            stmt = stmt.on_conflict_do_update(
                index_elements=["code"],
                set_={
                    "name": stmt.excluded.name,
                    "market": stmt.excluded.market,
                    "board": stmt.excluded.board,
                    "industry": stmt.excluded.industry,
                    "is_st": stmt.excluded.is_st,
                },
            )
            session.execute(stmt)
            session.commit()
            logger.info(f"股票列表更新完成，处理 {len(records)} 条记录")
        except Exception as e:
            session.rollback()
            logger.error(f"股票列表更新失败: {e}")
            raise
        finally:
            session.close()
        return len(records)

    def get_all_stock_codes(self, exclude_st: bool = True) -> list[str]:
        """获取所有股票代码"""
        session = get_session()
        try:
            query = session.query(StockBasic.code)
            if exclude_st:
                query = query.filter(StockBasic.is_st == False)
            return [row[0] for row in query.all()]
        finally:
            session.close()

    def get_stock_info(self, code: str) -> Optional[StockBasic]:
        """获取单只股票信息"""
        session = get_session()
        try:
            return session.query(StockBasic).filter_by(code=code).first()
        finally:
            session.close()

    # ========== 日K线数据 ==========

    def save_daily_bars(self, code: str, df: pd.DataFrame) -> int:
        """保存日K线数据（批量去重插入）"""
        if df.empty:
            return 0

        records = [
            {
                "code": code,
                "trade_date": row["trade_date"],
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "pre_close": row.get("pre_close"),
                "volume": row.get("volume"),
                "amount": row.get("amount"),
                "turnover": row.get("turnover"),
                "pct_change": row.get("pct_change"),
                "amplitude": row.get("amplitude"),
            }
            for _, row in df.iterrows()
        ]

        session = get_session()
        try:
            stmt = sqlite_insert(StockDaily).values(records).on_conflict_do_nothing()
            result = session.execute(stmt)
            session.commit()
            return result.rowcount
        except Exception as e:
            session.rollback()
            logger.error(f"保存日K线失败 {code}: {e}")
            raise
        finally:
            session.close()

    def get_daily_bars(
        self,
        code: str,
        start_date: date,
        end_date: date,
        adj: str = "none",
    ) -> pd.DataFrame:
        """
        获取日K线数据

        参数:
            adj: 复权类型 - "none"不复权, "qfq"前复权, "hfq"后复权
        """
        session = get_session()
        try:
            rows = (
                session.query(StockDaily)
                .filter(
                    StockDaily.code == code,
                    StockDaily.trade_date >= start_date,
                    StockDaily.trade_date <= end_date,
                )
                .order_by(StockDaily.trade_date)
                .all()
            )

            if not rows:
                return pd.DataFrame()

            data = []
            for r in rows:
                data.append({
                    "trade_date": r.trade_date,
                    "open": r.open,
                    "high": r.high,
                    "low": r.low,
                    "close": r.close,
                    "pre_close": r.pre_close,
                    "volume": r.volume,
                    "amount": r.amount,
                    "turnover": r.turnover,
                    "pct_change": r.pct_change,
                })
            df = pd.DataFrame(data)

            # 复权处理
            if adj in ("qfq", "hfq") and not df.empty:
                df = self._apply_adj_factor(code, df, adj)

            return df
        finally:
            session.close()

    def get_latest_trade_date(self, code: str) -> Optional[date]:
        """获取某只股票最新的交易日期（用于增量更新）"""
        session = get_session()
        try:
            result = (
                session.query(func.max(StockDaily.trade_date))
                .filter(StockDaily.code == code)
                .scalar()
            )
            return result
        finally:
            session.close()

    def get_date_range(self, code: str) -> tuple[Optional[date], Optional[date]]:
        """获取某只股票在数据库中的数据日期范围，返回 (最早日期, 最新日期)"""
        session = get_session()
        try:
            row = session.query(
                func.min(StockDaily.trade_date),
                func.max(StockDaily.trade_date),
            ).filter(StockDaily.code == code).one()
            return row[0], row[1]
        finally:
            session.close()

    def _apply_adj_factor(
        self, code: str, df: pd.DataFrame, adj: str
    ) -> pd.DataFrame:
        """应用复权因子"""
        session = get_session()
        try:
            factors = (
                session.query(AdjFactor)
                .filter(AdjFactor.code == code)
                .order_by(AdjFactor.trade_date)
                .all()
            )
            if not factors:
                return df

            factor_map = {f.trade_date: f.adj_factor for f in factors}
            adj_values = df["trade_date"].map(factor_map)

            if adj == "qfq":
                # 前复权：以最新日期的因子为基准
                latest_factor = max(factor_map.values())
                ratio = adj_values / latest_factor
            else:
                # 后复权：以最早日期的因子为基准
                earliest_factor = min(factor_map.values())
                ratio = adj_values / earliest_factor

            for col in ["open", "high", "low", "close"]:
                df[col] = (df[col] * ratio).round(2)

            return df
        finally:
            session.close()

    # ========== 复权因子 ==========

    def save_adj_factors(self, code: str, df: pd.DataFrame) -> int:
        """保存复权因子（批量 upsert，更新已有记录）"""
        if df.empty:
            return 0

        records = [
            {"code": code, "trade_date": row["trade_date"], "adj_factor": row["adj_factor"]}
            for _, row in df.iterrows()
        ]

        session = get_session()
        try:
            stmt = sqlite_insert(AdjFactor).values(records)
            stmt = stmt.on_conflict_do_update(
                index_elements=["code", "trade_date"],
                set_={"adj_factor": stmt.excluded.adj_factor},
            )
            result = session.execute(stmt)
            session.commit()
            return result.rowcount
        except Exception as e:
            session.rollback()
            logger.error(f"保存复权因子失败 {code}: {e}")
            raise
        finally:
            session.close()

    # ========== 交易日历 ==========

    def save_trade_calendar(self, df: pd.DataFrame, exchange: str = "SSE") -> int:
        """保存交易日历（批量去重插入）"""
        if df.empty:
            return 0

        records = [
            {"exchange": exchange, "cal_date": row["cal_date"], "is_open": row["is_open"]}
            for _, row in df.iterrows()
        ]

        session = get_session()
        try:
            stmt = sqlite_insert(TradeCalendar).values(records).on_conflict_do_nothing()
            result = session.execute(stmt)
            session.commit()
            logger.info(f"交易日历更新完成，新增 {result.rowcount} 条记录")
            return result.rowcount
        except Exception as e:
            session.rollback()
            logger.error(f"保存交易日历失败: {e}")
            raise
        finally:
            session.close()

    def get_trade_dates(
        self, start_date: date, end_date: date
    ) -> list[date]:
        """获取指定范围内的交易日列表"""
        session = get_session()
        try:
            rows = (
                session.query(TradeCalendar.cal_date)
                .filter(
                    TradeCalendar.is_open == True,
                    TradeCalendar.cal_date >= start_date,
                    TradeCalendar.cal_date <= end_date,
                )
                .order_by(TradeCalendar.cal_date)
                .all()
            )
            return [r[0] for r in rows]
        finally:
            session.close()

    def is_trade_date(self, check_date: date) -> bool:
        """判断是否为交易日"""
        session = get_session()
        try:
            result = session.query(TradeCalendar).filter_by(
                cal_date=check_date, is_open=True
            ).first()
            return result is not None
        finally:
            session.close()

    # ========== 指数日K线 ==========

    def save_index_daily(self, code: str, name: str, df: pd.DataFrame) -> int:
        """保存指数日K线（批量去重插入）"""
        if df.empty:
            return 0

        records = [
            {
                "code": code,
                "name": name,
                "trade_date": row["trade_date"],
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "volume": row.get("volume"),
                "amount": row.get("amount"),
                "pct_change": row.get("pct_change"),
            }
            for _, row in df.iterrows()
        ]

        session = get_session()
        try:
            stmt = sqlite_insert(IndexDaily).values(records).on_conflict_do_nothing()
            result = session.execute(stmt)
            session.commit()
            return result.rowcount
        except Exception as e:
            session.rollback()
            logger.error(f"保存指数日K线失败 {code}: {e}")
            raise
        finally:
            session.close()


class PaperRepository:
    """模拟盘数据仓库，封装模拟盘4张表的 CRUD 操作"""

    # ========== paper_account ==========

    def list_paper_accounts(self) -> list[PaperAccountORM]:
        """列出全部模拟盘账户，按最近更新时间倒序。"""
        session = get_session()
        try:
            return (
                session.query(PaperAccountORM)
                .order_by(PaperAccountORM.updated_at.desc(), PaperAccountORM.created_at.desc())
                .all()
            )
        finally:
            session.close()

    def get_paper_account(self, strategy_name: str) -> Optional[PaperAccountORM]:
        """获取模拟盘账户"""
        session = get_session()
        try:
            return session.query(PaperAccountORM).filter_by(
                strategy_name=strategy_name
            ).first()
        finally:
            session.close()

    def create_paper_account(
        self, strategy_name: str, initial_capital: float, stock_codes: list[str]
    ) -> None:
        """创建新的模拟盘账户"""
        session = get_session()
        try:
            account = PaperAccountORM(
                strategy_name=strategy_name,
                initial_capital=initial_capital,
                cash=initial_capital,
                stock_codes=json.dumps(stock_codes),
            )
            session.add(account)
            session.commit()
            logger.info(f"模拟盘账户已创建：{strategy_name}，初始资金 {initial_capital:,.2f}")
        except Exception as e:
            session.rollback()
            logger.error(f"创建模拟盘账户失败: {e}")
            raise
        finally:
            session.close()

    def update_paper_account(
        self,
        strategy_name: str,
        cash: float,
        total_commission: float,
        total_tax: float,
        stock_codes: Optional[list[str]] = None,
    ) -> None:
        """更新账户资金状态"""
        session = get_session()
        try:
            update_fields = {
                "cash": cash,
                "total_commission": total_commission,
                "total_tax": total_tax,
            }
            if stock_codes is not None:
                update_fields["stock_codes"] = json.dumps(stock_codes)
            session.query(PaperAccountORM).filter_by(
                strategy_name=strategy_name
            ).update(update_fields)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"更新账户失败 {strategy_name}: {e}")
            raise
        finally:
            session.close()

    # ========== paper_position ==========

    def get_paper_positions(self, strategy_name: str) -> list[PaperPositionORM]:
        """获取某策略的全部持仓"""
        session = get_session()
        try:
            return session.query(PaperPositionORM).filter_by(
                strategy_name=strategy_name
            ).all()
        finally:
            session.close()

    def upsert_paper_positions(
        self, strategy_name: str, positions: list[dict]
    ) -> None:
        """批量更新持仓（upsert）"""
        if not positions:
            return
        session = get_session()
        try:
            stmt = sqlite_insert(PaperPositionORM).values(positions)
            stmt = stmt.on_conflict_do_update(
                index_elements=["strategy_name", "code"],
                set_={
                    "volume": stmt.excluded.volume,
                    "available": stmt.excluded.available,
                    "cost_price": stmt.excluded.cost_price,
                    "current_price": stmt.excluded.current_price,
                    "buy_date": stmt.excluded.buy_date,
                },
            )
            session.execute(stmt)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"更新持仓失败: {e}")
            raise
        finally:
            session.close()

    def delete_paper_position(self, strategy_name: str, code: str) -> None:
        """删除已清空的持仓"""
        session = get_session()
        try:
            session.query(PaperPositionORM).filter_by(
                strategy_name=strategy_name, code=code
            ).delete()
            session.commit()
        finally:
            session.close()

    # ========== paper_order ==========

    def save_paper_order(self, order: dict) -> None:
        """保存一条新订单（通常为 pending 状态）"""
        if "order_id" not in order:
            order["order_id"] = uuid.uuid4().hex
        session = get_session()
        try:
            session.add(PaperOrderORM(**order))
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"保存订单失败: {e}")
            raise
        finally:
            session.close()

    def get_pending_orders(
        self, strategy_name: str, execute_date
    ) -> list[PaperOrderORM]:
        """获取某策略某日待执行的 pending 订单"""
        session = get_session()
        try:
            return session.query(PaperOrderORM).filter_by(
                strategy_name=strategy_name,
                execute_date=execute_date,
                status="pending",
            ).all()
        finally:
            session.close()

    def update_paper_order(
        self,
        order_id: str,
        status: str,
        filled_price: float = 0.0,
        filled_volume: int = 0,
        commission: float = 0.0,
        reason: str = "",
    ) -> None:
        """更新订单状态（成交/取消/拒绝）"""
        session = get_session()
        try:
            session.query(PaperOrderORM).filter_by(order_id=order_id).update({
                "status": status,
                "filled_price": filled_price,
                "filled_volume": filled_volume,
                "commission": commission,
                "reason": reason,
            })
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"更新订单失败 {order_id}: {e}")
            raise
        finally:
            session.close()

    def get_order_history(
        self, strategy_name: str, start_date=None, end_date=None
    ) -> list[PaperOrderORM]:
        """查询订单历史"""
        session = get_session()
        try:
            q = session.query(PaperOrderORM).filter_by(strategy_name=strategy_name)
            if start_date:
                q = q.filter(PaperOrderORM.signal_date >= start_date)
            if end_date:
                q = q.filter(PaperOrderORM.signal_date <= end_date)
            return q.order_by(PaperOrderORM.signal_date.desc()).all()
        finally:
            session.close()

    # ========== paper_nav ==========

    def nav_exists(self, strategy_name: str, trade_date) -> bool:
        """检查当日净值快照是否已存在（防重复运行）"""
        session = get_session()
        try:
            return session.query(PaperNav).filter_by(
                strategy_name=strategy_name, trade_date=trade_date
            ).first() is not None
        finally:
            session.close()

    def save_paper_nav(self, nav: dict) -> None:
        """保存每日净值快照"""
        session = get_session()
        try:
            stmt = sqlite_insert(PaperNav).values([nav]).on_conflict_do_update(
                index_elements=["strategy_name", "trade_date"],
                set_={k: v for k, v in nav.items() if k not in ("strategy_name", "trade_date")},
            )
            session.execute(stmt)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"保存净值快照失败: {e}")
            raise
        finally:
            session.close()

    def get_nav_series(
        self, strategy_name: str, start_date=None, end_date=None
    ) -> list[PaperNav]:
        """获取净值曲线（按日期升序）"""
        session = get_session()
        try:
            q = session.query(PaperNav).filter_by(strategy_name=strategy_name)
            if start_date:
                q = q.filter(PaperNav.trade_date >= start_date)
            if end_date:
                q = q.filter(PaperNav.trade_date <= end_date)
            return q.order_by(PaperNav.trade_date).all()
        finally:
            session.close()


class LiveRepository:
    """实盘/准实盘数据仓库，封装 live_* 表操作。"""

    # ========== live_account ==========

    def list_live_accounts(self) -> list[LiveAccountORM]:
        session = get_session()
        try:
            return (
                session.query(LiveAccountORM)
                .order_by(LiveAccountORM.updated_at.desc(), LiveAccountORM.created_at.desc())
                .all()
            )
        finally:
            session.close()

    def get_live_account(self, instance_id: str) -> Optional[LiveAccountORM]:
        session = get_session()
        try:
            return session.query(LiveAccountORM).filter_by(instance_id=instance_id).first()
        finally:
            session.close()

    def create_live_account(
        self,
        instance_id: str,
        strategy_key: str,
        broker_provider: str,
        broker_account_id: str,
        initial_capital: float,
        stock_codes: list[str],
        cash: float,
        total_equity: float,
    ) -> None:
        session = get_session()
        try:
            row = LiveAccountORM(
                instance_id=instance_id,
                strategy_key=strategy_key,
                broker_provider=broker_provider,
                broker_account_id=broker_account_id,
                initial_capital=initial_capital,
                cash=cash,
                total_equity=total_equity,
                stock_codes=json.dumps(stock_codes),
            )
            session.add(row)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"创建 live_account 失败 {instance_id}: {e}")
            raise
        finally:
            session.close()

    def update_live_account(
        self,
        instance_id: str,
        cash: float,
        total_equity: float,
        stock_codes: Optional[list[str]] = None,
        broker_account_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> None:
        session = get_session()
        try:
            update_fields = {
                "cash": cash,
                "total_equity": total_equity,
            }
            if stock_codes is not None:
                update_fields["stock_codes"] = json.dumps(stock_codes)
            if broker_account_id is not None:
                update_fields["broker_account_id"] = broker_account_id
            if status is not None:
                update_fields["status"] = status
            session.query(LiveAccountORM).filter_by(instance_id=instance_id).update(update_fields)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"更新 live_account 失败 {instance_id}: {e}")
            raise
        finally:
            session.close()

    # ========== live_position ==========

    def get_live_positions(self, instance_id: str) -> list[LivePositionORM]:
        session = get_session()
        try:
            return (
                session.query(LivePositionORM)
                .filter_by(instance_id=instance_id)
                .order_by(LivePositionORM.code)
                .all()
            )
        finally:
            session.close()

    def replace_live_positions(self, instance_id: str, positions: list[dict]) -> None:
        session = get_session()
        try:
            keep_codes = {p["code"] for p in positions}
            if keep_codes:
                session.query(LivePositionORM).filter(
                    LivePositionORM.instance_id == instance_id,
                    ~LivePositionORM.code.in_(keep_codes),
                ).delete(synchronize_session=False)
            else:
                session.query(LivePositionORM).filter_by(instance_id=instance_id).delete()

            if positions:
                stmt = sqlite_insert(LivePositionORM).values(positions)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["instance_id", "code"],
                    set_={
                        "volume": stmt.excluded.volume,
                        "available": stmt.excluded.available,
                        "cost_price": stmt.excluded.cost_price,
                        "current_price": stmt.excluded.current_price,
                        "source": stmt.excluded.source,
                    },
                )
                session.execute(stmt)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"替换 live_position 失败 {instance_id}: {e}")
            raise
        finally:
            session.close()

    # ========== live_order ==========

    def save_live_order(self, order: dict) -> None:
        session = get_session()
        try:
            session.add(LiveOrderORM(**order))
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"保存 live_order 失败: {e}")
            raise
        finally:
            session.close()

    def get_live_order(self, order_id: str) -> Optional[LiveOrderORM]:
        session = get_session()
        try:
            return session.query(LiveOrderORM).filter_by(order_id=order_id).first()
        finally:
            session.close()

    def update_live_order(
        self,
        order_id: str,
        status: str,
        broker_order_id: str = "",
        filled_price: float = 0.0,
        filled_volume: int = 0,
        commission: float = 0.0,
        reason: str = "",
    ) -> None:
        session = get_session()
        try:
            session.query(LiveOrderORM).filter_by(order_id=order_id).update({
                "status": status,
                "broker_order_id": broker_order_id,
                "filled_price": filled_price,
                "filled_volume": filled_volume,
                "commission": commission,
                "reason": reason,
            })
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"更新 live_order 失败 {order_id}: {e}")
            raise
        finally:
            session.close()

    def get_live_orders(
        self,
        instance_id: str,
        status: Optional[str] = None,
        start_date=None,
        end_date=None,
    ) -> list[LiveOrderORM]:
        session = get_session()
        try:
            q = session.query(LiveOrderORM).filter_by(instance_id=instance_id)
            if status:
                q = q.filter_by(status=status)
            if start_date:
                q = q.filter(LiveOrderORM.signal_date >= start_date)
            if end_date:
                q = q.filter(LiveOrderORM.signal_date <= end_date)
            return q.order_by(LiveOrderORM.created_at.desc()).all()
        finally:
            session.close()

    def get_due_live_orders(self, instance_id: str, execute_date: date) -> list[LiveOrderORM]:
        session = get_session()
        try:
            return (
                session.query(LiveOrderORM)
                .filter_by(
                    instance_id=instance_id,
                    status="planned",
                    planned_execute_date=execute_date,
                )
                .order_by(LiveOrderORM.created_at)
                .all()
            )
        finally:
            session.close()
