"""
数据源基类
定义统一的数据获取接口，所有数据源适配器必须实现这些方法
"""
from abc import ABC, abstractmethod
from datetime import date

import pandas as pd


class BaseDataSource(ABC):
    """数据源抽象基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """数据源名称"""
        ...

    @abstractmethod
    def get_stock_list(self) -> pd.DataFrame:
        """
        获取A股股票列表

        返回 DataFrame 列：
            code: 股票代码（纯数字，如 000001）
            name: 股票名称
            market: 市场（SH/SZ/BJ）
            board: 板块（main/gem/star/bse）
            industry: 行业
            list_date: 上市日期
        """
        ...

    @abstractmethod
    def get_daily_bars(
        self, code: str, start_date: date, end_date: date
    ) -> pd.DataFrame:
        """
        获取股票日K线数据

        参数:
            code: 股票代码（纯数字）
            start_date: 开始日期
            end_date: 结束日期

        返回 DataFrame 列：
            trade_date, open, high, low, close, pre_close,
            volume, amount, turnover, pct_change, amplitude
        """
        ...

    @abstractmethod
    def get_adj_factor(
        self, code: str, start_date: date, end_date: date
    ) -> pd.DataFrame:
        """
        获取复权因子

        返回 DataFrame 列：
            trade_date, adj_factor
        """
        ...

    @abstractmethod
    def get_trade_calendar(
        self, start_date: date, end_date: date
    ) -> pd.DataFrame:
        """
        获取交易日历

        返回 DataFrame 列：
            cal_date, is_open
        """
        ...

    @abstractmethod
    def get_index_daily(
        self, code: str, start_date: date, end_date: date
    ) -> pd.DataFrame:
        """
        获取指数日K线

        返回 DataFrame 列：
            trade_date, open, high, low, close, volume, amount, pct_change
        """
        ...
