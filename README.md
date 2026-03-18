# A股量化炒股系统

A股量化交易系统，涵盖行情数据采集、策略引擎、回测框架，目标实现完整链路：**回测 → 模拟 → 实盘**。

## 功能特性

- **双数据源**：AKShare（主） + Tushare（备），自动故障切换
- **6张核心数据表**：股票基础信息、日K线、复权因子、交易日历、指数行情、财务指标
- **回测引擎**：真实模拟 A 股交易规则（T+1、涨跌停、最小交易单位）
- **费用模型**：佣金（万2.5）+ 印花税（千1）+ 过户费
- **15+ 绩效指标**：Sharpe、Sortino、Calmar、最大回撤、胜率、盈亏比等
- **策略框架**：统一策略接口，支持参数化配置和命令行调参
- **增量更新**：每日收盘后自动增量拉取最新数据

## 技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.11+ |
| ORM | SQLAlchemy 2.0 |
| 数据库 | SQLite（开发）/ PostgreSQL + TimescaleDB（生产） |
| 数据源 | AKShare / Tushare |
| 日志 | loguru |
| 数据处理 | pandas / numpy |

## 项目结构

```
├── config/                     # 全局配置
│   ├── __init__.py             # 配置加载器
│   ├── settings.yaml           # 系统配置（数据库、数据源、交易规则、风控）
│   └── strategies.yaml         # 策略参数 + 股票池配置
├── data/                       # 数据模块
│   ├── sources/                # 数据源适配器（AKShare / Tushare）
│   ├── storage/repository.py   # 数据库 CRUD
│   ├── models.py               # ORM 模型（6张表）
│   └── collector.py            # 数据采集调度器
├── strategy/                   # 策略模块
│   ├── base.py                 # 策略基类 + 数据结构
│   └── technical/              # 技术指标策略
│       ├── ma_cross.py         # 均线交叉策略
│       └── macd_strategy.py    # MACD 策略
├── backtest/                   # 回测模块
│   ├── engine.py               # 回测引擎
│   ├── account.py              # 账户管理
│   ├── fee.py                  # 费用模型
│   ├── rules.py                # A股交易规则
│   └── metrics.py              # 绩效评估
├── trading/                    # 交易执行（待开发）
├── risk/                       # 风控模块（待开发）
├── api/                        # Web API（待开发）
├── scripts/                    # 运行脚本
│   ├── init_db.py              # 数据库初始化
│   ├── daily_update.py         # 每日数据更新
│   ├── run_backtest.py         # 回测运行入口
│   └── query_stock.py          # 数据查询验证工具
└── requirements.txt
```

## 快速开始

### 1. 环境准备

```bash
# 克隆项目
git clone <repo-url>
cd a-stock-trading-system

# 创建虚拟环境（推荐）
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# 安装依赖
pip install -r requirements.txt
```

### 2. 初始化数据库

```bash
# 仅创建表结构（快速验证，不拉取数据）
python scripts/init_db.py --tables-only

# 创建表 + 拉取历史数据（首次运行，需要等待）
python scripts/init_db.py --start 2023-01-01

# 仅更新股票列表和交易日历
python scripts/init_db.py --stock-list-only
```

### 3. 运行回测

```bash
# 均线交叉策略 - 回测平安银行
python scripts/run_backtest.py --strategy ma_cross --codes 000001 --start 2023-01-01

# 均线交叉策略 - 多只股票
python scripts/run_backtest.py --strategy ma_cross --codes 000001 600519 --start 2023-01-01

# MACD 策略
python scripts/run_backtest.py --strategy macd --codes 000001 --start 2023-01-01

# 自定义策略参数
python scripts/run_backtest.py --strategy ma_cross --codes 000001 --start 2023-01-01 \
    --params short_period=10 long_period=30

# 指定初始资金
python scripts/run_backtest.py --strategy ma_cross --codes 000001 --start 2023-01-01 \
    --capital 500000
```

### 4. 查询验证数据

```bash
# 从本地数据库查询（默认）
python scripts/query_stock.py -c 000001 -s 2023-01-03 -e 2023-01-10

# 从网络接口实时查询
python scripts/query_stock.py -c 000001 -s 2023-01-03 -e 2023-01-10 --source api

# 对比本地与网络数据，验证正确性
python scripts/query_stock.py -c 000001 -s 2023-01-03 -e 2023-01-10 --source both
```

### 5. 每日数据更新

```bash
# 常规增量更新（每个交易日收盘后运行）
python scripts/daily_update.py

# 仅更新指定股票
python scripts/daily_update.py --codes 000001 600519

# 更新后做数据质量校验
python scripts/daily_update.py --validate

# 补近7天数据
python scripts/daily_update.py --days 7
```

## 回测报告示例

运行回测后会输出如下报告：

```
============================================================
  回测报告: MA交叉(5/20 EMA)
  区间: 2023-01-01 ~ 2024-12-31
============================================================

【收益指标】
  总收益率:          12.35%
  年化收益率:         6.18%
  基准收益率:        -5.20%
  Alpha:             11.38%

【风险指标】
  最大回撤:           8.76%
  年化波动率:        18.42%
  Sharpe 比率:        0.335

【交易统计】
  总交易次数:            15
  胜率:              46.67%
  盈亏比:              1.85
  平均持仓天数:        12.3
============================================================
```

## 配置说明

### 数据源配置

编辑 `config/settings.yaml`：

```yaml
data_sources:
  akshare:
    enabled: true              # AKShare 免费，默认开启
  tushare:
    enabled: false             # 需要注册获取 token
    token: "your_token_here"   # 填入 Tushare token
  priority: ["akshare", "tushare"]  # 优先级
```

### 交易费用配置

```yaml
trading_rules:
  commission_rate: 0.00025     # 佣金费率（万2.5）
  min_commission: 5.0          # 最低佣金（元）
  stamp_tax_rate: 0.001        # 印花税（千1，仅卖出）
  transfer_fee_rate: 0.00002   # 过户费（万0.2）
```

### 策略参数配置

编辑 `config/strategies.yaml`：

```yaml
strategies:
  ma_cross:
    short_period: 5      # 短期均线
    long_period: 20      # 长期均线
    ma_type: "EMA"       # SMA 或 EMA
  macd:
    fast_period: 12
    slow_period: 26
    signal_period: 9
```

## 可用策略

| 策略 | 命令行名称 | 说明 |
|------|-----------|------|
| 均线交叉 | `ma_cross` | 短期均线上穿/下穿长期均线产生买卖信号，支持 SMA/EMA |
| MACD | `macd` | DIF 与 DEA 金叉/死叉产生买卖信号 |
| KDJ | `kdj` | 待开发 |
| 布林带 | `bollinger` | 待开发 |
| RSI | `rsi` | 待开发 |

## A股交易规则模拟

回测引擎严格模拟以下 A 股规则：

- **T+1 交易**：当日买入次日才能卖出
- **涨跌停板**：主板 ±10%、创业板/科创板 ±20%、北交所 ±30%、ST ±5%
- **涨停无法买入、跌停无法卖出**
- **最小交易单位**：买入必须为 100 股整数倍
- **真实费用**：佣金 + 印花税 + 过户费

## 开发路线图

- [x] Phase 1: 数据基础（数据采集 + 存储 + 增量更新）
- [x] Phase 2: 回测引擎（撮合 + 规则 + 费用 + 绩效评估）
- [ ] Phase 3: 策略库扩展（KDJ、布林带、RSI、多因子）
- [ ] Phase 4: 风控模块（仓位控制、止损止盈、黑名单）
- [ ] Phase 5: 模拟交易
- [ ] Phase 6: Web 可视化（FastAPI + Vue 3 + ECharts）
- [ ] Phase 7: 实盘对接（QMT/miniQMT）

## 免责声明

本项目仅供学习和研究使用。量化交易存在风险，策略的历史回测表现不代表未来收益。请勿将本系统直接用于实盘交易而不经过充分验证。投资有风险，入市需谨慎。

## 许可证

MIT License
