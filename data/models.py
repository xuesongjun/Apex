"""
A股炒股系统 - 数据模型定义（SQLAlchemy ORM）

包含以下核心表：
- StockBasic: 股票基础信息
- StockDaily: 日K线数据
- AdjFactor: 复权因子
- TradeCalendar: 交易日历
- IndexDaily: 指数日K线
- StockFinance: 核心财务指标
"""
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config import DatabaseConfig


class Base(DeclarativeBase):
    """ORM 基类"""
    pass


# ========== 股票基础信息 ==========
class StockBasic(Base):
    """
    股票基础信息表
    记录所有A股股票的基本资料
    """
    __tablename__ = "stock_basic"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False, unique=True, comment="股票代码，如 000001")
    name = Column(String(20), nullable=False, comment="股票名称")
    market = Column(String(10), comment="市场：SH=上海 SZ=深圳 BJ=北京")
    board = Column(String(20), comment="板块：main=主板 gem=创业板 star=科创板 bse=北交所")
    industry = Column(String(30), comment="所属行业")
    list_date = Column(Date, comment="上市日期")
    delist_date = Column(Date, comment="退市日期（未退市为空）")
    is_st = Column(Boolean, default=False, comment="是否为 ST 股票")
    status = Column(String(10), default="active", comment="状态：active=正常 suspended=停牌 delisted=退市")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    def __repr__(self):
        return f"<StockBasic {self.code} {self.name}>"


# ========== 日K线数据 ==========
class StockDaily(Base):
    """
    股票日K线数据表
    存储每日开高低收量额等行情数据
    """
    __tablename__ = "stock_daily"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False, comment="股票代码")
    trade_date = Column(Date, nullable=False, comment="交易日期")
    open = Column(Float, comment="开盘价")
    high = Column(Float, comment="最高价")
    low = Column(Float, comment="最低价")
    close = Column(Float, comment="收盘价")
    pre_close = Column(Float, comment="昨收价")
    volume = Column(BigInteger, comment="成交量（股）")
    amount = Column(Float, comment="成交额（元）")
    turnover = Column(Float, comment="换手率（%）")
    pct_change = Column(Float, comment="涨跌幅（%）")
    amplitude = Column(Float, comment="振幅（%）")

    __table_args__ = (
        UniqueConstraint("code", "trade_date", name="uix_daily_code_date"),
        Index("ix_daily_code", "code"),
        Index("ix_daily_date", "trade_date"),
    )

    def __repr__(self):
        return f"<StockDaily {self.code} {self.trade_date} C:{self.close}>"


# ========== 复权因子 ==========
class AdjFactor(Base):
    """
    复权因子表
    用于计算前复权/后复权价格
    """
    __tablename__ = "adj_factor"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False, comment="股票代码")
    trade_date = Column(Date, nullable=False, comment="交易日期")
    adj_factor = Column(Float, nullable=False, comment="复权因子")

    __table_args__ = (
        UniqueConstraint("code", "trade_date", name="uix_adj_code_date"),
        Index("ix_adj_code", "code"),
    )


# ========== 交易日历 ==========
class TradeCalendar(Base):
    """
    交易日历表
    标记每个自然日是否为交易日
    """
    __tablename__ = "trade_calendar"

    id = Column(Integer, primary_key=True, autoincrement=True)
    exchange = Column(String(10), nullable=False, comment="交易所：SSE=上交所 SZSE=深交所")
    cal_date = Column(Date, nullable=False, comment="日期")
    is_open = Column(Boolean, nullable=False, comment="是否为交易日")

    __table_args__ = (
        UniqueConstraint("exchange", "cal_date", name="uix_cal_exchange_date"),
        Index("ix_cal_date", "cal_date"),
    )


# ========== 指数日K线 ==========
class IndexDaily(Base):
    """
    指数日K线数据表
    存储上证指数、沪深300等指数行情，用于基准对比
    """
    __tablename__ = "index_daily"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False, comment="指数代码，如 000300")
    name = Column(String(30), comment="指数名称")
    trade_date = Column(Date, nullable=False, comment="交易日期")
    open = Column(Float, comment="开盘价")
    high = Column(Float, comment="最高价")
    low = Column(Float, comment="最低价")
    close = Column(Float, comment="收盘价")
    volume = Column(BigInteger, comment="成交量")
    amount = Column(Float, comment="成交额")
    pct_change = Column(Float, comment="涨跌幅（%）")

    __table_args__ = (
        UniqueConstraint("code", "trade_date", name="uix_index_code_date"),
        Index("ix_index_code", "code"),
        Index("ix_index_date", "trade_date"),
    )


# ========== 核心财务指标 ==========
class StockFinance(Base):
    """
    股票核心财务指标表
    存储估值和盈利能力等关键数据
    """
    __tablename__ = "stock_finance"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False, comment="股票代码")
    report_date = Column(Date, nullable=False, comment="报告期（如 2024-12-31）")
    pe_ttm = Column(Float, comment="市盈率（TTM）")
    pb = Column(Float, comment="市净率")
    ps_ttm = Column(Float, comment="市销率（TTM）")
    total_mv = Column(Float, comment="总市值（万元）")
    circ_mv = Column(Float, comment="流通市值（万元）")
    roe = Column(Float, comment="净资产收益率（%）")
    revenue = Column(Float, comment="营业收入（万元）")
    net_profit = Column(Float, comment="净利润（万元）")
    revenue_yoy = Column(Float, comment="营收同比增长率（%）")
    profit_yoy = Column(Float, comment="净利润同比增长率（%）")

    __table_args__ = (
        UniqueConstraint("code", "report_date", name="uix_fin_code_report"),
        Index("ix_fin_code", "code"),
    )


# ========== 数据库引擎与会话 ==========

def get_engine():
    """获取数据库引擎"""
    db_url = DatabaseConfig.get_url()
    return create_engine(db_url, echo=DatabaseConfig.echo)


def get_session_factory():
    """获取数据库会话工厂"""
    engine = get_engine()
    return sessionmaker(bind=engine)


def init_db():
    """初始化数据库：创建所有表"""
    engine = get_engine()
    Base.metadata.create_all(engine)
    return engine


def get_session() -> Session:
    """获取一个新的数据库会话"""
    factory = get_session_factory()
    return factory()
