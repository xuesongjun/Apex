"""
AKShare 数据源适配器
免费开源，无需注册，数据覆盖面广
文档：https://akshare.akfamily.xyz/
"""
import time
import concurrent.futures
from datetime import date

import akshare as ak
import pandas as pd
from loguru import logger

from config import DataSourceConfig
from data.sources.base import BaseDataSource

# 单次请求超时时间（秒）
REQUEST_TIMEOUT = 30


class RequestTimeoutError(Exception):
    """请求超时异常"""
    pass


class AKShareSource(BaseDataSource):
    """AKShare 数据源"""

    @property
    def name(self) -> str:
        return "akshare"

    def _run_with_timeout(self, func, timeout, *args, **kwargs):
        """在子线程中执行函数，超时则放弃"""
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(func, *args, **kwargs)
            return future.result(timeout=timeout)

    def _request_with_retry(self, func, *args, **kwargs) -> pd.DataFrame:
        """带重试、限频和超时控制的请求封装"""
        for attempt in range(DataSourceConfig.akshare_retry):
            try:
                time.sleep(DataSourceConfig.akshare_interval)
                result = self._run_with_timeout(
                    func, REQUEST_TIMEOUT, *args, **kwargs
                )
                return result if result is not None else pd.DataFrame()
            except concurrent.futures.TimeoutError:
                logger.warning(
                    f"AKShare 请求超时 (第{attempt + 1}次, {REQUEST_TIMEOUT}s): {func.__name__}"
                )
            except Exception as e:
                logger.warning(
                    f"AKShare 请求失败 (第{attempt + 1}次): {func.__name__} - {e}"
                )
            if attempt < DataSourceConfig.akshare_retry - 1:
                time.sleep(DataSourceConfig.akshare_interval * (attempt + 1))
        logger.error(f"AKShare 请求最终失败: {func.__name__}")
        return pd.DataFrame()

    def _detect_board(self, code: str, name: str) -> str:
        """根据代码前缀判断板块"""
        if code.startswith("688"):
            return "star"       # 科创板
        elif code.startswith("300") or code.startswith("301"):
            return "gem"        # 创业板
        elif code.startswith("8") or code.startswith("4"):
            return "bse"        # 北交所
        else:
            return "main"       # 主板

    def _detect_market(self, code: str) -> str:
        """根据代码前缀判断市场"""
        if code.startswith("6"):
            return "SH"
        elif code.startswith("0") or code.startswith("3"):
            return "SZ"
        elif code.startswith("8") or code.startswith("4"):
            return "BJ"
        return "SZ"

    def get_stock_list(self) -> pd.DataFrame:
        """获取A股股票列表
        使用 stock_info_a_code_name 接口（轻量、稳定），
        替代 stock_zh_a_spot_em（数据量大，容易被限流断连）
        """
        logger.info("AKShare: 获取A股股票列表...")

        df = self._request_with_retry(ak.stock_info_a_code_name)
        if df.empty:
            return df

        result = pd.DataFrame()
        result["code"] = df["code"].astype(str)
        result["name"] = df["name"]
        result["market"] = result["code"].apply(self._detect_market)
        result["board"] = result["code"].apply(
            lambda c: self._detect_board(c, "")
        )
        result["industry"] = ""
        result["list_date"] = None

        # 标记 ST 股票
        result["is_st"] = result["name"].str.contains(
            r"ST|退市", case=False, na=False
        )

        logger.info(f"AKShare: 获取到 {len(result)} 只股票")
        return result

    def _code_to_sina_symbol(self, code: str) -> str:
        """将纯数字代码转为新浪格式（如 sz000001、sh600519）"""
        market = self._detect_market(code)
        prefix = {"SH": "sh", "SZ": "sz", "BJ": "bj"}.get(market, "sz")
        return f"{prefix}{code}"

    def get_daily_bars(
        self, code: str, start_date: date, end_date: date
    ) -> pd.DataFrame:
        """获取股票日K线数据（新浪源，避免东财限流）"""
        logger.debug(f"AKShare: 获取日K线 {code} [{start_date} ~ {end_date}]")

        symbol = self._code_to_sina_symbol(code)

        df = self._request_with_retry(
            ak.stock_zh_a_daily,
            symbol=symbol,
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
            adjust="",  # 不复权
        )
        if df.empty:
            return df

        result = pd.DataFrame()
        result["trade_date"] = pd.to_datetime(df["date"]).dt.date
        result["open"] = df["open"].astype(float)
        result["high"] = df["high"].astype(float)
        result["low"] = df["low"].astype(float)
        result["close"] = df["close"].astype(float)
        # 新浪源无昨收字段，用前一天收盘价
        result["pre_close"] = result["close"].shift(1)
        result["volume"] = df["volume"].astype(int)
        result["amount"] = df["amount"].astype(float) if "amount" in df.columns else 0.0
        result["turnover"] = df["turnover"].astype(float) if "turnover" in df.columns else 0.0
        # 计算涨跌幅
        result["pct_change"] = result["close"].pct_change() * 100
        result["amplitude"] = 0.0

        return result

    def get_adj_factor(
        self, code: str, start_date: date, end_date: date
    ) -> pd.DataFrame:
        """
        获取复权因子（新浪源）
        通过对比前复权和不复权数据计算
        """
        logger.debug(f"AKShare: 获取复权因子 {code}")

        symbol = self._code_to_sina_symbol(code)

        # 获取前复权数据
        df_qfq = self._request_with_retry(
            ak.stock_zh_a_daily,
            symbol=symbol,
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
            adjust="qfq",
        )
        # 获取不复权数据
        df_raw = self._request_with_retry(
            ak.stock_zh_a_daily,
            symbol=symbol,
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
            adjust="",
        )

        if df_qfq.empty or df_raw.empty:
            return pd.DataFrame()

        result = pd.DataFrame()
        result["trade_date"] = pd.to_datetime(df_raw["date"]).dt.date
        # 复权因子 = 前复权收盘价 / 不复权收盘价
        raw_close = df_raw["close"].astype(float)
        qfq_close = df_qfq["close"].astype(float)
        result["adj_factor"] = (qfq_close / raw_close).round(6)

        return result

    def get_trade_calendar(
        self, start_date: date, end_date: date
    ) -> pd.DataFrame:
        """获取交易日历"""
        logger.info("AKShare: 获取交易日历...")

        df = self._request_with_retry(ak.tool_trade_date_hist_sina)
        if df.empty:
            return df

        result = pd.DataFrame()
        result["cal_date"] = pd.to_datetime(df["trade_date"]).dt.date
        result["is_open"] = True  # 返回的都是交易日

        # 过滤日期范围
        result = result[
            (result["cal_date"] >= start_date) & (result["cal_date"] <= end_date)
        ].reset_index(drop=True)

        logger.info(f"AKShare: 获取到 {len(result)} 个交易日")
        return result

    def get_index_daily(
        self, code: str, start_date: date, end_date: date
    ) -> pd.DataFrame:
        """获取指数日K线（新浪源，避免东财限流）"""
        logger.debug(f"AKShare: 获取指数日K线 {code}")

        df = self._request_with_retry(
            ak.stock_zh_index_daily,
            symbol=f"sh{code}" if code.startswith("0") else f"sz{code}",
        )
        if df.empty:
            return df

        result = pd.DataFrame()
        result["trade_date"] = pd.to_datetime(df["date"]).dt.date
        result["open"] = df["open"].astype(float)
        result["high"] = df["high"].astype(float)
        result["low"] = df["low"].astype(float)
        result["close"] = df["close"].astype(float)
        result["volume"] = df["volume"].astype(int)
        result["amount"] = 0.0  # 新浪源部分指数无成交额数据
        # 计算涨跌幅
        result["pct_change"] = result["close"].pct_change() * 100

        # 过滤日期范围
        result = result[
            (result["trade_date"] >= start_date) & (result["trade_date"] <= end_date)
        ].reset_index(drop=True)

        return result
