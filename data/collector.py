"""
数据采集调度器
负责协调数据源和存储层，实现全量初始化和增量更新
"""
from datetime import date, timedelta
from typing import Optional

from loguru import logger

from config import DataSourceConfig
from data.sources.base import BaseDataSource
from data.sources.akshare_source import AKShareSource
from data.storage.repository import StockRepository


class DataCollector:
    """
    数据采集调度器

    功能：
    1. 自动选择可用数据源（按优先级）
    2. 全量初始化：首次运行时拉取所有历史数据
    3. 增量更新：每日更新最新数据
    4. 数据质量校验
    """

    def __init__(self):
        self.repo = StockRepository()
        self._sources: list[BaseDataSource] = []
        self._init_sources()

    def _init_sources(self):
        """按优先级初始化数据源"""
        for source_name in DataSourceConfig.priority:
            try:
                if source_name == "akshare" and DataSourceConfig.akshare_enabled:
                    self._sources.append(AKShareSource())
                    logger.info("数据源已启用: AKShare")
                elif source_name == "tushare" and DataSourceConfig.tushare_enabled:
                    from data.sources.tushare_source import TushareSource
                    self._sources.append(TushareSource())
                    logger.info("数据源已启用: Tushare")
            except Exception as e:
                logger.warning(f"数据源 {source_name} 初始化失败: {e}")

        if not self._sources:
            raise RuntimeError("没有可用的数据源！请检查配置")

    def _get_data(self, method_name: str, *args, **kwargs):
        """
        按优先级从数据源获取数据
        如果第一个数据源失败，自动回退到下一个
        """
        for source in self._sources:
            try:
                method = getattr(source, method_name)
                result = method(*args, **kwargs)
                if result is not None and not result.empty:
                    return result
                logger.warning(f"{source.name}.{method_name} 返回空数据，尝试下一个数据源")
            except Exception as e:
                logger.warning(f"{source.name}.{method_name} 失败: {e}")
        logger.error(f"所有数据源的 {method_name} 均失败")
        return None

    # ========== 采集任务 ==========

    def update_stock_list(self):
        """更新股票列表"""
        logger.info("="*50)
        logger.info("开始更新股票列表...")
        df = self._get_data("get_stock_list")
        if df is not None:
            count = self.repo.upsert_stock_list(df)
            logger.info(f"股票列表更新完成: {count} 条")
        else:
            logger.error("股票列表更新失败：无法获取数据")

    def update_trade_calendar(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ):
        """更新交易日历"""
        if start_date is None:
            start_date = date(2015, 1, 1)
        if end_date is None:
            end_date = date.today()

        logger.info(f"开始更新交易日历 [{start_date} ~ {end_date}]...")
        df = self._get_data("get_trade_calendar", start_date, end_date)
        if df is not None:
            count = self.repo.save_trade_calendar(df)
            logger.info(f"交易日历更新完成: 新增 {count} 条")

    def update_daily_bars(
        self,
        codes: Optional[list[str]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ):
        """
        更新日K线数据

        参数:
            codes: 股票代码列表，为空则更新所有股票
            start_date: 开始日期，为空则自动增量更新
            end_date: 结束日期，默认今天
        """
        if end_date is None:
            end_date = date.today()

        # 获取要更新的股票列表
        if codes is None:
            codes = self.repo.get_all_stock_codes(exclude_st=False)
        if not codes:
            logger.warning("没有需要更新的股票")
            return

        total = len(codes)
        success = 0
        fail = 0

        logger.info(f"开始更新日K线数据，共 {total} 只股票...")

        for i, code in enumerate(codes, 1):
            try:
                # 确定起始日期（增量更新）
                if start_date is None:
                    latest = self.repo.get_latest_trade_date(code)
                    if latest:
                        code_start = latest + timedelta(days=1)
                    else:
                        code_start = date(2020, 1, 1)  # 默认从2020年开始
                else:
                    code_start = start_date

                if code_start > end_date:
                    continue  # 已是最新，跳过

                # 获取K线数据
                df = self._get_data(
                    "get_daily_bars", code, code_start, end_date
                )
                if df is not None and not df.empty:
                    count = self.repo.save_daily_bars(code, df)
                    if count > 0:
                        logger.debug(f"[{i}/{total}] {code} 新增 {count} 条K线")
                    success += 1
                else:
                    fail += 1

                # 进度日志
                if i % 100 == 0:
                    logger.info(f"K线更新进度: {i}/{total} (成功:{success} 失败:{fail})")

            except Exception as e:
                logger.error(f"更新K线失败 {code}: {e}")
                fail += 1

        logger.info(f"日K线更新完成: 成功 {success}, 失败 {fail}, 总计 {total}")

    def update_adj_factors(
        self,
        codes: Optional[list[str]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ):
        """更新复权因子"""
        if end_date is None:
            end_date = date.today()
        if start_date is None:
            start_date = date(2020, 1, 1)

        if codes is None:
            codes = self.repo.get_all_stock_codes(exclude_st=False)

        total = len(codes)
        logger.info(f"开始更新复权因子，共 {total} 只股票...")

        for i, code in enumerate(codes, 1):
            try:
                df = self._get_data("get_adj_factor", code, start_date, end_date)
                if df is not None and not df.empty:
                    self.repo.save_adj_factors(code, df)

                if i % 100 == 0:
                    logger.info(f"复权因子更新进度: {i}/{total}")
            except Exception as e:
                logger.error(f"更新复权因子失败 {code}: {e}")

        logger.info(f"复权因子更新完成")

    def update_index_daily(
        self,
        index_codes: Optional[dict[str, str]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ):
        """
        更新指数日K线

        参数:
            index_codes: {代码: 名称} 字典，默认更新常用指数
        """
        if index_codes is None:
            index_codes = {
                "000001": "上证指数",
                "000300": "沪深300",
                "000905": "中证500",
                "399001": "深证成指",
                "399006": "创业板指",
            }
        if start_date is None:
            start_date = date(2020, 1, 1)
        if end_date is None:
            end_date = date.today()

        logger.info("开始更新指数日K线...")
        for code, name in index_codes.items():
            try:
                df = self._get_data("get_index_daily", code, start_date, end_date)
                if df is not None and not df.empty:
                    count = self.repo.save_index_daily(code, name, df)
                    logger.info(f"指数 {name}({code}) 新增 {count} 条")
            except Exception as e:
                logger.error(f"更新指数K线失败 {name}({code}): {e}")

    # ========== 一键操作 ==========

    def init_all(self, start_date: Optional[date] = None):
        """
        全量初始化：首次运行时调用
        按顺序执行所有数据采集任务
        """
        logger.info("=" * 60)
        logger.info("开始全量数据初始化...")
        logger.info("=" * 60)

        # 1. 交易日历（最先执行）
        self.update_trade_calendar()

        # 2. 股票列表
        self.update_stock_list()

        # 3. 指数日K线
        self.update_index_daily(start_date=start_date)

        # 4. 个股日K线（耗时最长）
        self.update_daily_bars(start_date=start_date)

        # 5. 复权因子
        self.update_adj_factors(start_date=start_date)

        logger.info("=" * 60)
        logger.info("全量数据初始化完成！")
        logger.info("=" * 60)

    def daily_update(self):
        """
        每日增量更新：每个交易日收盘后调用
        """
        today = date.today()
        logger.info(f"开始每日增量更新 [{today}]...")

        # 更新股票列表（处理新上市/退市/ST变动）
        self.update_stock_list()

        # 增量更新日K线（自动从上次更新的位置开始）
        self.update_daily_bars()

        # 更新复权因子
        self.update_adj_factors(start_date=today - timedelta(days=7))

        # 更新指数
        self.update_index_daily(start_date=today - timedelta(days=7))

        logger.info(f"每日增量更新完成")

    # ========== 数据校验 ==========

    def validate_data(self, code: str, start_date: date, end_date: date) -> dict:
        """
        数据质量校验

        返回校验报告：
            total_bars: 总K线数
            missing_dates: 缺失的交易日列表
            anomalies: 异常数据列表
        """
        report = {
            "code": code,
            "total_bars": 0,
            "missing_dates": [],
            "anomalies": [],
        }

        # 获取交易日列表
        trade_dates = set(self.repo.get_trade_dates(start_date, end_date))

        # 获取已有K线
        df = self.repo.get_daily_bars(code, start_date, end_date)
        if df.empty:
            report["missing_dates"] = list(trade_dates)
            return report

        report["total_bars"] = len(df)
        existing_dates = set(df["trade_date"])

        # 检查缺失交易日
        report["missing_dates"] = sorted(trade_dates - existing_dates)

        # 检查异常数据
        for _, row in df.iterrows():
            issues = []
            if row["high"] < row["low"]:
                issues.append("最高价 < 最低价")
            if row["close"] <= 0:
                issues.append("收盘价 <= 0")
            if row["volume"] < 0:
                issues.append("成交量 < 0")
            if issues:
                report["anomalies"].append({
                    "date": row["trade_date"],
                    "issues": issues,
                })

        return report
