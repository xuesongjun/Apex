"""
A股炒股系统 - 全局配置加载器
"""
import os
from pathlib import Path

import yaml
from loguru import logger

# 项目根目录
ROOT_DIR = Path(__file__).parent.parent
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"
LOG_DIR = ROOT_DIR / "logs"


def load_yaml(file_path: str | Path) -> dict:
    """加载 YAML 配置文件"""
    file_path = Path(file_path)
    if not file_path.exists():
        logger.warning(f"配置文件不存在: {file_path}")
        return {}
    with open(file_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# 加载全局配置
_settings = load_yaml(CONFIG_DIR / "settings.yaml")
_strategies = load_yaml(CONFIG_DIR / "strategies.yaml")


# ========== 数据库配置 ==========
class DatabaseConfig:
    engine: str = _settings.get("database", {}).get("engine", "sqlite")
    url: str = _settings.get("database", {}).get("url", "")
    sqlite_url: str = _settings.get("database", {}).get(
        "sqlite_url", f"sqlite:///{DATA_DIR / 'stock_trading.db'}"
    )
    echo: bool = _settings.get("database", {}).get("echo", False)

    @classmethod
    def get_url(cls) -> str:
        """根据 engine 配置返回对应的数据库 URL"""
        if cls.engine == "sqlite":
            return cls.sqlite_url
        return cls.url


# ========== 数据源配置 ==========
class DataSourceConfig:
    _ds = _settings.get("data_sources", {})
    akshare_enabled: bool = _ds.get("akshare", {}).get("enabled", True)
    akshare_retry: int = _ds.get("akshare", {}).get("retry_times", 3)
    akshare_interval: float = _ds.get("akshare", {}).get("request_interval", 0.5)
    tushare_enabled: bool = _ds.get("tushare", {}).get("enabled", False)
    tushare_token: str = _ds.get("tushare", {}).get("token", "")
    tushare_retry: int = _ds.get("tushare", {}).get("retry_times", 3)
    priority: list = _ds.get("priority", ["akshare", "tushare"])


# ========== 交易规则配置 ==========
class TradingRulesConfig:
    _tr = _settings.get("trading_rules", {})
    commission_rate: float = _tr.get("commission_rate", 0.00025)
    min_commission: float = _tr.get("min_commission", 5.0)
    stamp_tax_rate: float = _tr.get("stamp_tax_rate", 0.001)
    transfer_fee_rate: float = _tr.get("transfer_fee_rate", 0.00002)
    min_trade_unit: int = _tr.get("min_trade_unit", 100)
    price_limit: dict = _tr.get("price_limit", {
        "main_board": 0.10,
        "gem": 0.20,
        "star": 0.20,
        "bse": 0.30,
        "st": 0.05,
    })


# ========== 风控配置 ==========
class RiskControlConfig:
    _rc = _settings.get("risk_control", {})
    max_single_position: float = _rc.get("max_single_position", 0.20)
    max_sector_position: float = _rc.get("max_sector_position", 0.30)
    max_total_position: float = _rc.get("max_total_position", 0.80)
    stop_loss_pct: float = _rc.get("stop_loss_pct", -0.07)
    take_profit_pct: float = _rc.get("take_profit_pct", 0.20)
    max_daily_loss: float = _rc.get("max_daily_loss", -0.03)
    max_drawdown: float = _rc.get("max_drawdown", -0.10)


# ========== 回测配置 ==========
class BacktestConfig:
    _bt = _settings.get("backtest", {})
    initial_capital: float = _bt.get("initial_capital", 1000000.0)
    benchmark: str = _bt.get("benchmark", "000300")
    slippage: float = _bt.get("slippage", 0.01)


# ========== 策略配置 ==========
STRATEGY_CONFIG = _strategies.get("strategies", {})
STOCK_POOL_CONFIG = _strategies.get("stock_pool", {})


def setup_logging():
    """初始化日志配置"""
    log_cfg = _settings.get("logging", {})
    level = log_cfg.get("level", "INFO")
    log_dir = ROOT_DIR / log_cfg.get("log_dir", "logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.add(
        log_dir / "system_{time:YYYY-MM-DD}.log",
        level=level,
        rotation=log_cfg.get("rotation", "10 MB"),
        retention=log_cfg.get("retention", "30 days"),
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{function}:{line} | {message}",
    )
