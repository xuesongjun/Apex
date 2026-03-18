# A股量化炒股系统

## 项目简介

A股量化交易系统，涵盖行情数据采集、策略引擎、回测框架、模拟/实盘交易、风控管理及可视化监控。

- **数据源:** AKShare（主） + Tushare（备）
- **策略方向:** 技术指标策略优先
- **最终目标:** 完整链路（回测 → 模拟 → 实盘）
- **技术栈:** 纯 Python

## 目录结构

```
a-stock-trading-system/
├── config/                     # 全局配置
│   ├── __init__.py             # 配置加载器（DatabaseConfig, DataSourceConfig 等）
│   ├── settings.yaml           # 系统配置（数据库、数据源、交易规则、风控）
│   └── strategies.yaml         # 策略参数配置 + 股票池配置
├── data/                       # 数据模块
│   ├── sources/                # 数据源适配器
│   │   ├── base.py             # 抽象基类 BaseDataSource
│   │   ├── akshare_source.py   # AKShare 适配器
│   │   └── tushare_source.py   # Tushare 适配器
│   ├── storage/
│   │   └── repository.py       # 数据库 CRUD（StockRepository）
│   ├── models.py               # ORM 模型（6张表）
│   └── collector.py            # 数据采集调度器（DataCollector）
├── strategy/                   # 策略模块
│   ├── base.py                 # 策略基类 BaseStrategy + 数据结构
│   └── technical/              # 技术指标策略
│       ├── ma_cross.py         # 均线交叉策略 MACrossStrategy
│       └── macd_strategy.py    # MACD 策略 MACDStrategy
├── backtest/                   # 回测模块
│   ├── engine.py               # 回测引擎 BacktestEngine + BacktestResult
│   ├── account.py              # 账户管理 Account
│   ├── fee.py                  # 费用模型 FeeModel
│   ├── rules.py                # A股交易规则 TradingRules
│   └── metrics.py              # 绩效评估 BacktestMetrics
├── trading/                    # 交易执行模块（待开发）
├── risk/                       # 风控模块（待开发）
├── api/                        # Web API（待开发）
├── scripts/
│   ├── init_db.py              # 数据库初始化脚本
│   ├── daily_update.py         # 每日数据更新脚本
│   ├── run_backtest.py         # 回测运行入口
│   └── query_stock.py          # 数据查询验证工具
├── requirements.txt
└── plan.md                     # 完整设计规划文档
```

## 技术栈

- Python 3.11+
- SQLAlchemy 2.0（ORM）
- SQLite（开发）/ PostgreSQL + TimescaleDB（生产）
- AKShare / Tushare（行情数据）
- FastAPI（Web API，待开发）
- loguru（日志）
- pandas / numpy（数据处理）

## 常用命令

```bash
# 安装依赖
pip install -r requirements.txt

# 初始化数据库 + 拉取历史数据（首次运行）
python scripts/init_db.py --start 2023-01-01

# 仅创建表结构（不拉数据）
python scripts/init_db.py --tables-only

# 仅更新股票列表和交易日历
python scripts/init_db.py --stock-list-only

# 每日增量更新（收盘后运行）
python scripts/daily_update.py

# 运行回测 - 均线交叉策略
python scripts/run_backtest.py --strategy ma_cross --codes 000001 600519 --start 2023-01-01

# 运行回测 - MACD策略
python scripts/run_backtest.py --strategy macd --codes 000001 --start 2023-01-01

# 自定义策略参数
python scripts/run_backtest.py --strategy ma_cross --codes 000001 --start 2023-01-01 --params short_period=10 long_period=30

# 查询股票数据 - 从本地数据库（默认）
python scripts/query_stock.py -c 000001 -s 2023-01-03 -e 2023-01-10

# 查询股票数据 - 从网络接口
python scripts/query_stock.py -c 000001 -s 2023-01-03 -e 2023-01-10 --source api

# 查询股票数据 - 对比本地和网络
python scripts/query_stock.py -c 000001 -s 2023-01-03 -e 2023-01-10 --source both
```

## 代码风格

- 中文注释，复杂逻辑必须附带说明
- 类型注解：函数参数和返回值使用类型提示
- 配置外置：关键参数定义在 `settings.yaml` / `strategies.yaml`
- 日志统一使用 `loguru`

## 开发进度

### 已完成功能

- [x] Phase 1: 数据基础
  - [x] 全局配置加载器（`config/__init__.py`）
  - [x] 数据模型定义（6张 ORM 表）
  - [x] AKShare 数据源适配器
  - [x] Tushare 数据源适配器
  - [x] 数据存储层（StockRepository CRUD）
  - [x] 数据采集调度器（全量初始化 + 增量更新 + 数据校验）
  - [x] 数据库初始化脚本 + 每日更新脚本
- [x] Phase 2: 回测引擎
  - [x] 策略基类 + 数据结构（BarData/Signal/Position/OrderData）
  - [x] 回测引擎（数据加载 → K线回放 → 信号撮合 → 结果输出）
  - [x] 账户管理（资金/持仓/T+1解冻）
  - [x] A股交易规则模拟（T+1、涨跌停、最小交易单位）
  - [x] 费用模型（佣金+印花税+过户费）
  - [x] 绩效评估（15+ 指标：Sharpe/最大回撤/胜率等）
  - [x] 均线交叉策略（MACrossStrategy）
  - [x] MACD 策略（MACDStrategy）
  - [x] 回测命令行运行入口

### 待开发

- [ ] Phase 3: 更多策略（KDJ、布林带、RSI、多因子）
- [ ] Phase 4: 风控模块（仓位控制、止损止盈、黑名单、告警）
- [ ] Phase 5: 模拟交易（接入模拟盘）
- [ ] Phase 6: Web 可视化（FastAPI + Vue 3 + ECharts）
- [ ] Phase 7: 实盘对接（QMT/miniQMT）

### 已知问题

- AKShare 东方财富(eastmoney)系列接口在部分网络环境下不可用，已全部替换为新浪源接口
- 数据库默认使用 SQLite（开发阶段），大数据量场景需切换 PostgreSQL

### 2026-03-18 进度记录

#### 本次完成
- 完成系统整体架构设计，生成 `plan.md` 规划文档
- 从零搭建项目结构，创建全部目录和模块 `__init__.py`
- 实现 Phase 1 数据基础：配置加载、6张 ORM 表、AKShare/Tushare 双数据源适配器、数据存储层、数据采集调度器
- 实现 Phase 2 回测引擎：策略基类、回测撮合引擎（含 A 股 T+1/涨跌停规则）、账户管理、费用模型、15+ 绩效指标
- 实现两个技术指标策略：均线交叉（MACrossStrategy）、MACD（MACDStrategy）
- 编写三个运行脚本：`init_db.py`、`daily_update.py`、`run_backtest.py`

#### 关键变更
| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `config/__init__.py` | 新功能 | 全局配置加载器，包含 DatabaseConfig/DataSourceConfig 等 6 个配置类 |
| `config/settings.yaml` | 新功能 | 数据库、数据源、交易规则、风控、回测、日志、通知全局配置 |
| `config/strategies.yaml` | 新功能 | 策略参数配置 + 股票池配置 |
| `data/models.py` | 新功能 | 6 张 ORM 表：StockBasic/StockDaily/AdjFactor/TradeCalendar/IndexDaily/StockFinance |
| `data/sources/base.py` | 新功能 | 数据源抽象基类 BaseDataSource |
| `data/sources/akshare_source.py` | 新功能 | AKShare 适配器，含重试/限频机制 |
| `data/sources/tushare_source.py` | 新功能 | Tushare 适配器，含代码格式转换 |
| `data/storage/repository.py` | 新功能 | StockRepository 数据库 CRUD，支持复权处理 |
| `data/collector.py` | 新功能 | DataCollector 采集调度器：全量初始化/增量更新/数据校验 |
| `strategy/base.py` | 新功能 | BaseStrategy 基类 + BarData/Signal/Position/OrderData 数据结构 |
| `strategy/technical/ma_cross.py` | 新功能 | 均线交叉策略（支持 SMA/EMA，可配参数） |
| `strategy/technical/macd_strategy.py` | 新功能 | MACD 策略（DIF/DEA/MACD柱金叉死叉） |
| `backtest/engine.py` | 新功能 | 回测引擎 BacktestEngine + BacktestResult |
| `backtest/account.py` | 新功能 | 账户管理（资金/持仓/T+1解冻/资产快照） |
| `backtest/rules.py` | 新功能 | A股交易规则（T+1/涨跌停/最小单位/订单验证） |
| `backtest/fee.py` | 新功能 | 费用模型（佣金万2.5/印花税千1/过户费） |
| `backtest/metrics.py` | 新功能 | 15+ 绩效指标计算 |
| `scripts/init_db.py` | 新功能 | 数据库初始化脚本（支持 --tables-only/--stock-list-only） |
| `scripts/daily_update.py` | 新功能 | 每日增量更新脚本（支持 --validate/--codes） |
| `scripts/run_backtest.py` | 新功能 | 回测运行入口（支持策略选择/参数覆盖） |

#### 断点 / 待续
- 下次从 **Phase 3（策略库扩展）** 开始，在 `strategy/technical/` 目录下新增 KDJ、布林带、RSI 策略
- 或者先做 **Phase 4（风控模块）**，在 `risk/rules/` 下实现仓位控制、止损规则
- 数据拉取中（5490 只股票），支持断点续传，中断后重新运行 `init_db.py` 会自动跳过已入库股票

#### 运行命令 / 备忘
```bash
pip install -r requirements.txt
python scripts/init_db.py --tables-only        # 先创建表验证 ORM
python scripts/init_db.py --start 2023-01-01   # 拉取历史数据（支持断点续传）
python scripts/run_backtest.py --strategy ma_cross --codes 000001 --start 2023-01-01
python scripts/query_stock.py -c 000001 -s 2026-03-15  # 查询验证数据
```

### 2026-03-18 第二次进度记录

#### 本次完成
- 修复 AKShare 数据源：东方财富接口在公司网络环境下全部不可用，替换为新浪源接口
- 为请求增加 30 秒超时控制（`concurrent.futures.ThreadPoolExecutor`），防止卡死
- 新增数据查询验证脚本 `scripts/query_stock.py`，支持从本地数据库/网络接口/对比查询

#### 关键变更
| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `data/sources/akshare_source.py` | 修复 | 全部接口从东财源替换为新浪源：`stock_zh_a_spot_em`→`stock_info_a_code_name`、`stock_zh_a_hist`→`stock_zh_a_daily`、`stock_zh_index_daily_em`→`stock_zh_index_daily`；新增 30s 超时控制 |
| `scripts/query_stock.py` | 新功能 | 数据查询验证工具，支持 `--source db/api/both` 三种模式 |

#### AKShare 接口映射（新浪源）
| 用途 | 接口函数 | 数据源 |
|------|---------|--------|
| 股票列表 | `stock_info_a_code_name` | 新浪 |
| 个股日K线 | `stock_zh_a_daily` | 新浪 |
| 指数日K线 | `stock_zh_index_daily` | 新浪 |
| 交易日历 | `tool_trade_date_hist_sina` | 新浪 |
