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


# ========== 模拟盘账户 ==========
class PaperAccount(Base):
    """
    模拟盘账户表
    每个策略实例对应一行，记录资金状态
    """
    __tablename__ = "paper_account"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    strategy_name    = Column(String(50), nullable=False, unique=True, comment="策略名称（唯一标识）")
    initial_capital  = Column(Float, nullable=False, comment="初始资金（不可变）")
    cash             = Column(Float, nullable=False, comment="当前可用现金")
    total_commission = Column(Float, default=0.0, comment="累计佣金")
    total_tax        = Column(Float, default=0.0, comment="累计印花税")
    stock_codes      = Column(Text, comment="标的列表（JSON 序列化）")
    created_at       = Column(DateTime, default=datetime.now)
    updated_at       = Column(DateTime, default=datetime.now, onupdate=datetime.now)


# ========== 模拟盘持仓 ==========
class PaperPosition(Base):
    """
    模拟盘持仓表
    记录每个策略对每只股票的实时持仓状态
    """
    __tablename__ = "paper_position"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    strategy_name = Column(String(50), nullable=False, comment="策略名称")
    code          = Column(String(10), nullable=False, comment="股票代码")
    volume        = Column(Integer, nullable=False, default=0, comment="总持仓量（股）")
    available     = Column(Integer, nullable=False, default=0, comment="可卖量（T+1 规则）")
    cost_price    = Column(Float, nullable=False, default=0.0, comment="持仓均价")
    current_price = Column(Float, default=0.0, comment="最新收盘价（每日更新）")
    buy_date      = Column(Date, comment="最近一次买入日（T+1 判断用）")
    updated_at    = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        UniqueConstraint("strategy_name", "code", name="uix_paper_pos_strategy_code"),
        Index("ix_paper_pos_strategy", "strategy_name"),
    )


# ========== 模拟盘订单 ==========
class PaperOrder(Base):
    """
    模拟盘订单表
    每笔委托的完整生命周期记录（pending → filled/cancelled/rejected）
    """
    __tablename__ = "paper_order"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    order_id      = Column(String(32), nullable=False, unique=True, comment="UUID 订单号")
    strategy_name = Column(String(50), nullable=False, comment="策略名称")
    code          = Column(String(10), nullable=False, comment="股票代码")
    direction     = Column(String(4), nullable=False, comment="BUY / SELL")
    signal_date   = Column(Date, nullable=False, comment="信号产生日（收盘后）")
    execute_date  = Column(Date, comment="计划执行日（下一交易日，以开盘价成交）")
    status        = Column(String(10), nullable=False, default="pending",
                           comment="pending / filled / cancelled / rejected")
    req_volume    = Column(Integer, nullable=False, comment="委托数量（策略请求）")
    filled_price  = Column(Float, default=0.0, comment="实际成交价")
    filled_volume = Column(Integer, default=0, comment="实际成交量")
    commission    = Column(Float, default=0.0, comment="手续费")
    reason        = Column(Text, comment="信号原因 / 拒绝原因")
    created_at    = Column(DateTime, default=datetime.now)
    updated_at    = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index("ix_paper_order_strategy_status", "strategy_name", "status"),
        Index("ix_paper_order_execute_date", "execute_date"),
    )


# ========== 模拟盘净值 ==========
class PaperNav(Base):
    """
    模拟盘每日净值快照
    用于绩效分析和净值曲线绘制
    """
    __tablename__ = "paper_nav"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    strategy_name  = Column(String(50), nullable=False, comment="策略名称")
    trade_date     = Column(Date, nullable=False, comment="交易日")
    cash           = Column(Float, comment="可用现金")
    market_value   = Column(Float, comment="持仓市值（收盘价）")
    total_equity   = Column(Float, comment="总资产 = 现金 + 市值")
    nav            = Column(Float, comment="单位净值 = 总资产 / 初始资金")
    daily_pnl      = Column(Float, comment="当日盈亏")
    position_count = Column(Integer, comment="持仓标的数量")

    __table_args__ = (
        UniqueConstraint("strategy_name", "trade_date", name="uix_paper_nav_strategy_date"),
        Index("ix_paper_nav_strategy", "strategy_name"),
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
