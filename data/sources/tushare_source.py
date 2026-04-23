"""
Tushare 数据源适配器
需要注册获取 token，免费版有限额
文档：https://tushare.pro/
"""
import time
from datetime import date

import pandas as pd
from loguru import logger

from config import DataSourceConfig
from data.sources.base import BaseDataSource

try:
    import tushare as ts
except ImportError:
    ts = None


class TushareSource(BaseDataSource):
    """Tushare 数据源"""

    def __init__(self):
        if ts is None:
            raise ImportError("请安装 tushare: pip install tushare")
        token = DataSourceConfig.tushare_token
        if not token:
            raise ValueError("Tushare token 未配置，请在 config/settings.yaml 中设置")
        ts.set_token(token)
        self._pro = ts.pro_api()

    @property
    def name(self) -> str:
        return "tushare"

    def _request_with_retry(self, func, **kwargs) -> pd.DataFrame:
        """带重试的请求封装"""
        for attempt in range(DataSourceConfig.tushare_retry):
            try:
                time.sleep(0.3)  # tushare 限频
                result = func(**kwargs)
                return result if result is not None else pd.DataFrame()
            except Exception as e:
                logger.warning(
                    f"Tushare 请求失败 (第{attempt + 1}次): {e}"
                )
                if attempt < DataSourceConfig.tushare_retry - 1:
                    time.sleep(2 * (attempt + 1))
        logger.error(f"Tushare 请求最终失败")
        return pd.DataFrame()

    def _code_to_ts(self, code: str) -> str:
        """将纯数字代码转为 tushare 格式（如 000001 → 000001.SZ）"""
        if code.startswith("6"):
            return f"{code}.SH"
        elif code.startswith("8") or code.startswith("4"):
            return f"{code}.BJ"
        else:
            return f"{code}.SZ"

    def _detect_board(self, code: str) -> str:
        """根据代码前缀判断板块"""
        if code.startswith("688"):
            return "star"
        elif code.startswith("300") or code.startswith("301"):
            return "gem"
        elif code.startswith("8") or code.startswith("4"):
            return "bse"
        return "main"

    def get_stock_list(self) -> pd.DataFrame:
        """获取A股股票列表"""
        logger.info("Tushare: 获取A股股票列表...")

        df = self._request_with_retry(
            self._pro.stock_basic,
            exchange="",
            list_status="L",
            fields="ts_code,symbol,name,area,industry,market,list_date",
        )
        if df.empty:
            return df

        result = pd.DataFrame()
        result["code"] = df["symbol"]
        result["name"] = df["name"]
        result["market"] = df["ts_code"].apply(
            lambda x: x.split(".")[1] if "." in x else "SZ"
        )
        result["board"] = result["code"].apply(self._detect_board)
        result["industry"] = df["industry"].fillna("")
        result["list_date"] = pd.to_datetime(df["list_date"]).dt.date
        result["is_st"] = result["name"].str.contains(
            r"ST|退市", case=False, na=False
        )

        logger.info(f"Tushare: 获取到 {len(result)} 只股票")
        return result

    def get_daily_bars(
        self, code: str, start_date: date, end_date: date
    ) -> pd.DataFrame:
        """获取股票日K线数据"""
        ts_code = self._code_to_ts(code)
        logger.debug(f"Tushare: 获取日K线 {ts_code}")

        df = self._request_with_retry(
            self._pro.daily,
            ts_code=ts_code,
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
        )
        if df.empty:
            return df

        result = pd.DataFrame()
        result["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
        result["open"] = df["open"].astype(float)
        result["high"] = df["high"].astype(float)
        result["low"] = df["low"].astype(float)
        result["close"] = df["close"].astype(float)
        result["pre_close"] = df["pre_close"].astype(float)
        result["volume"] = (df["vol"] * 100).astype(int)  # tushare vol 单位是手
        result["amount"] = (df["amount"] * 1000).astype(float)  # tushare amount 单位是千元
        result["pct_change"] = df["pct_chg"].astype(float)
        result["turnover"] = 0.0
        result["amplitude"] = 0.0

        # tushare 默认按日期降序，需要升序排列
        result = result.sort_values("trade_date").reset_index(drop=True)
        return result

    def get_adj_factor(
        self, code: str, start_date: date, end_date: date
    ) -> pd.DataFrame:
        """获取复权因子"""
        ts_code = self._code_to_ts(code)
        logger.debug(f"Tushare: 获取复权因子 {ts_code}")

        df = self._request_with_retry(
            self._pro.adj_factor,
            ts_code=ts_code,
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
        )
        if df.empty:
            return df

        result = pd.DataFrame()
        result["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
        result["adj_factor"] = df["adj_factor"].astype(float)
        result = result.sort_values("trade_date").reset_index(drop=True)
        return result

    def get_trade_calendar(
        self, start_date: date, end_date: date
    ) -> pd.DataFrame:
        """获取交易日历"""
        logger.info("Tushare: 获取交易日历...")

        df = self._request_with_retry(
            self._pro.trade_cal,
            exchange="SSE",
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
        )
        if df.empty:
            return df

        result = pd.DataFrame()
        result["cal_date"] = pd.to_datetime(df["cal_date"]).dt.date
        result["is_open"] = df["is_open"].astype(bool)
        result = result.sort_values("cal_date").reset_index(drop=True)

        logger.info(f"Tushare: 获取到 {len(result)} 条日历数据")
        return result

    def get_index_daily(
        self, code: str, start_date: date, end_date: date
    ) -> pd.DataFrame:
        """获取指数日K线"""
        # tushare 指数代码格式：
        # - 上交所指数常见为 000xxx.SH
        # - 深交所指数常见为 399xxx.SZ
        if code.startswith("399"):
            ts_code = f"{code}.SZ"
        else:
            ts_code = f"{code}.SH"
        logger.debug(f"Tushare: 获取指数日K线 {ts_code}")

        df = self._request_with_retry(
            self._pro.index_daily,
            ts_code=ts_code,
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
        )
        if df.empty:
            return df

        result = pd.DataFrame()
        result["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
        result["open"] = df["open"].astype(float)
        result["high"] = df["high"].astype(float)
        result["low"] = df["low"].astype(float)
        result["close"] = df["close"].astype(float)
        result["volume"] = df["vol"].astype(int)
        result["amount"] = df["amount"].astype(float)
        result["pct_change"] = df["pct_chg"].astype(float)
        result = result.sort_values("trade_date").reset_index(drop=True)
        return result
