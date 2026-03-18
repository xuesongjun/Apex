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
        更新或插入股票列表
        返回影响的行数
        """
        if df.empty:
            return 0

        session = get_session()
        count = 0
        try:
            for _, row in df.iterrows():
                existing = session.query(StockBasic).filter_by(
                    code=row["code"]
                ).first()
                if existing:
                    existing.name = row.get("name", existing.name)
                    existing.market = row.get("market", existing.market)
                    existing.board = row.get("board", existing.board)
                    existing.industry = row.get("industry", existing.industry)
                    if row.get("is_st") is not None:
                        existing.is_st = bool(row["is_st"])
                else:
                    stock = StockBasic(
                        code=row["code"],
                        name=row.get("name", ""),
                        market=row.get("market", ""),
                        board=row.get("board", "main"),
                        industry=row.get("industry", ""),
                        list_date=row.get("list_date"),
                        is_st=bool(row.get("is_st", False)),
                    )
                    session.add(stock)
                count += 1
            session.commit()
            logger.info(f"股票列表更新完成，处理 {count} 条记录")
        except Exception as e:
            session.rollback()
            logger.error(f"股票列表更新失败: {e}")
            raise
        finally:
            session.close()
        return count

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
        """保存日K线数据（去重插入）"""
        if df.empty:
            return 0

        session = get_session()
        count = 0
        try:
            for _, row in df.iterrows():
                existing = session.query(StockDaily).filter_by(
                    code=code, trade_date=row["trade_date"]
                ).first()
                if existing:
                    continue  # 已存在则跳过

                bar = StockDaily(
                    code=code,
                    trade_date=row["trade_date"],
                    open=row.get("open"),
                    high=row.get("high"),
                    low=row.get("low"),
                    close=row.get("close"),
                    pre_close=row.get("pre_close"),
                    volume=row.get("volume"),
                    amount=row.get("amount"),
                    turnover=row.get("turnover"),
                    pct_change=row.get("pct_change"),
                    amplitude=row.get("amplitude"),
                )
                session.add(bar)
                count += 1
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"保存日K线失败 {code}: {e}")
            raise
        finally:
            session.close()
        return count

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
        """保存复权因子"""
        if df.empty:
            return 0

        session = get_session()
        count = 0
        try:
            for _, row in df.iterrows():
                existing = session.query(AdjFactor).filter_by(
                    code=code, trade_date=row["trade_date"]
                ).first()
                if existing:
                    existing.adj_factor = row["adj_factor"]
                else:
                    session.add(AdjFactor(
                        code=code,
                        trade_date=row["trade_date"],
                        adj_factor=row["adj_factor"],
                    ))
                    count += 1
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"保存复权因子失败 {code}: {e}")
            raise
        finally:
            session.close()
        return count

    # ========== 交易日历 ==========

    def save_trade_calendar(self, df: pd.DataFrame, exchange: str = "SSE") -> int:
        """保存交易日历"""
        if df.empty:
            return 0

        session = get_session()
        count = 0
        try:
            for _, row in df.iterrows():
                existing = session.query(TradeCalendar).filter_by(
                    exchange=exchange, cal_date=row["cal_date"]
                ).first()
                if not existing:
                    session.add(TradeCalendar(
                        exchange=exchange,
                        cal_date=row["cal_date"],
                        is_open=row["is_open"],
                    ))
                    count += 1
            session.commit()
            logger.info(f"交易日历更新完成，新增 {count} 条记录")
        except Exception as e:
            session.rollback()
            logger.error(f"保存交易日历失败: {e}")
            raise
        finally:
            session.close()
        return count

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
        """保存指数日K线"""
        if df.empty:
            return 0

        session = get_session()
        count = 0
        try:
            for _, row in df.iterrows():
                existing = session.query(IndexDaily).filter_by(
                    code=code, trade_date=row["trade_date"]
                ).first()
                if not existing:
                    session.add(IndexDaily(
                        code=code,
                        name=name,
                        trade_date=row["trade_date"],
                        open=row.get("open"),
                        high=row.get("high"),
                        low=row.get("low"),
                        close=row.get("close"),
                        volume=row.get("volume"),
                        amount=row.get("amount"),
                        pct_change=row.get("pct_change"),
                    ))
                    count += 1
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"保存指数日K线失败 {code}: {e}")
            raise
        finally:
            session.close()
        return count
