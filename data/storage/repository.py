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

from data.models import (
    AdjFactor,
    IndexDaily,
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
