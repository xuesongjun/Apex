# A股量化炒股系统

A股量化交易系统，涵盖行情数据采集、策略引擎、回测框架，目标实现完整链路：**回测 → 模拟 → 实盘**。

## 功能特性

- **双数据源**：AKShare（主） + Tushare（备），自动故障切换
- **ETF 支持**：个股 + 普通 ETF + 跨境 ETF（自动识别涨跌停幅度）
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
├── scripts/
│   ├── init_db.py              # 数据库初始化
│   ├── daily_update.py         # 每日数据更新
│   ├── run_backtest.py         # 策略回测入口
│   ├── run_limitdown_short.py  # 开盘做空回测策略
│   └── query_stock.py          # 数据查询验证工具
└── requirements.txt
```

## 快速开始

### 1. 环境准备

```bash
git clone <repo-url>
cd Apex

python -m venv .venv
source .venv/bin/activate   # Linux/Mac
# .venv\Scripts\activate    # Windows

pip install -r requirements.txt
```

### 2. 初始化数据库

```bash
# 仅创建表结构（快速验证）
python scripts/init_db.py --tables-only

# 只拉取指定股票/ETF（推荐首次使用）
python scripts/init_db.py --codes 000001 600519 --start 2023-01-01

# 拉取全市场数据（5000+ 只，耗时较长）
python scripts/init_db.py --start 2023-01-01

# 仅更新股票列表和交易日历
python scripts/init_db.py --stock-list-only
```

### 3. 策略回测

```bash
# 均线交叉策略
python scripts/run_backtest.py --strategy ma_cross --codes 000001 --start 2023-01-01

# 多只股票
python scripts/run_backtest.py --strategy ma_cross --codes 000001 600519 --start 2023-01-01

# MACD 策略
python scripts/run_backtest.py --strategy macd --codes 000001 --start 2023-01-01

# 自定义参数
python scripts/run_backtest.py --strategy ma_cross --codes 000001 --start 2023-01-01 \
    --params short_period=10 long_period=30

# 指定初始资金
python scripts/run_backtest.py --strategy ma_cross --codes 000001 --start 2023-01-01 \
    --capital 500000

# 显示全部交易明细（默认只显示最近20笔）
python scripts/run_backtest.py --strategy ma_cross --codes 000001 --start 2023-01-01 --all

# 导出全部交易明细到 CSV
python scripts/run_backtest.py --strategy ma_cross --codes 000001 --start 2023-01-01 --csv trades.csv
```

### 4. 开盘做空策略回测

> 模拟"集合竞价挂跌停价卖出（实际以开盘价成交）+ 收盘前买入"的日内做空逻辑。

```bash
# 基本用法（以开盘价卖出，收盘价买回，每日必然触发）
python scripts/run_limitdown_short.py --code 000001 --start 2023-01-01

# 指定初始资金
python scripts/run_limitdown_short.py --code 000001 --start 2023-01-01 --capital 500000

# 指定结束日期
python scripts/run_limitdown_short.py --code 513090 --start 2023-01-01 --end 2024-12-31

# 固定每笔手数（而非全仓）
python scripts/run_limitdown_short.py --code 600519 --start 2023-01-01 --shares 100

# 支持 ETF（含跨境 ETF）
python scripts/run_limitdown_short.py --code 513090 --start 2023-01-01 --capital 500000
python scripts/run_limitdown_short.py --code 510300 --start 2023-01-01 --capital 500000

# 显示全部每日明细（默认只显示最近10笔）
python scripts/run_limitdown_short.py --code 513090 --start 2023-01-01 --all

# 导出全部明细到 CSV（Excel 直接打开不乱码）
python scripts/run_limitdown_short.py --code 513090 --start 2023-01-01 --csv result.csv

# 同时显示全部 + 导出 CSV
python scripts/run_limitdown_short.py --code 513090 --start 2023-01-01 --all --csv result.csv
```

**策略原理：**

在集合竞价阶段（9:15–9:25），以"竞价参考价 × (1 - 跌停幅度)"挂限价卖出委托。
由于竞价阶段采用统一清算价撮合，限价 ≤ 清算价时委托以**开盘价**成交，
而非以限价本身成交。因此实际效果等价于每日开盘价卖出、收盘价买入。

| 情形 | 结果 |
|------|------|
| 开盘价 > 收盘价（当日下跌） | 空头盈利 |
| 开盘价 < 收盘价（当日上涨） | 空头亏损 |

> 注意：A 股实盘不支持个股卖空，本策略为纯理论回测。

### 5. ETF 数据拉取

```bash
# 常见 ETF 代码
python scripts/init_db.py --codes 510050 510300 510500 --start 2023-01-01  # 沪市宽基ETF
python scripts/init_db.py --codes 159915 159919 --start 2023-01-01         # 深市ETF
python scripts/init_db.py --codes 513090 513100 --start 2023-01-01         # 跨境ETF
```

| 代码 | 名称 | 类型 |
|------|------|------|
| 510050 | 上证50 ETF | 普通 ±10% |
| 510300 | 沪深300 ETF | 普通 ±10% |
| 510500 | 中证500 ETF | 普通 ±10% |
| 159915 | 创业板 ETF | 普通 ±10% |
| 513090 | 恒生互联网科技 ETF | 跨境 ±15% |
| 513100 | 纳斯达克100 ETF | 跨境 ±15% |

### 6. 查询验证数据

```bash
# 从本地数据库查询
python scripts/query_stock.py -c 000001 -s 2023-01-03 -e 2023-01-10

# 从网络接口实时查询
python scripts/query_stock.py -c 000001 -s 2023-01-03 -e 2023-01-10 --source api

# 对比本地与网络数据
python scripts/query_stock.py -c 000001 -s 2023-01-03 -e 2023-01-10 --source both
```

### 7. 每日数据更新

```bash
# 增量更新所有股票（每个交易日收盘后运行）
python scripts/daily_update.py

# 仅更新指定股票
python scripts/daily_update.py --codes 000001 600519

# 更新后做数据质量校验
python scripts/daily_update.py --validate

# 补近7天数据
python scripts/daily_update.py --days 7
```

## 回测报告示例

```
==================================================================
  回测报告：开盘卖出 + 尾盘买入（理论做空）
  股票: 513090 恒生互联网科技ETF  |  2023-01-01 ~ 2026-04-07
==================================================================

【资金概览】
  初始资金              500,000.00
  期末资金              310,982.71
  总盈亏               -189,017.29
  总收益率                  -37.80%

【交易统计】
  总交易日                     787
  胜率                       44.98%
  盈利天数                     354  （开盘 > 收盘）
  亏损天数                     433  （开盘 ≤ 收盘）

【最近 10 笔交易明细】
  日期            开盘价    收盘价      价差%        手数          盈亏        累计资金
  ──────────────────────────────────────────────────────────────────────────────
  2026-03-24        1.74      1.76     -0.92%     166,600     -3,113.26      302,449.24
  2026-03-26        1.79      1.74     +2.69%     159,900     +7,237.23      308,112.01
==================================================================
```

## 配置说明

### 数据源

编辑 `config/settings.yaml`：

```yaml
data_sources:
  akshare:
    enabled: true
  tushare:
    enabled: false
    token: "your_token_here"
  priority: ["akshare", "tushare"]
```

### 交易费用

```yaml
trading_rules:
  commission_rate: 0.00025    # 佣金（万2.5）
  min_commission: 5.0         # 最低佣金（元）
  stamp_tax_rate: 0.001       # 印花税（千1，仅卖出）
  transfer_fee_rate: 0.00002  # 过户费（万0.2）
```

### 策略参数

编辑 `config/strategies.yaml`：

```yaml
strategies:
  ma_cross:
    short_period: 5
    long_period: 20
    ma_type: "EMA"      # SMA 或 EMA
  macd:
    fast_period: 12
    slow_period: 26
    signal_period: 9
```

## 可用策略

| 策略 | 命令行名称 | 说明 |
|------|-----------|------|
| 均线交叉 | `ma_cross` | 短期均线上穿/下穿长期均线，支持 SMA/EMA |
| MACD | `macd` | DIF 与 DEA 金叉/死叉 |
| 开盘做空 | `run_limitdown_short.py` | 开盘卖出 + 尾盘买入，每日必然触发 |
| KDJ | — | 待开发 |
| 布林带 | — | 待开发 |
| RSI | — | 待开发 |

## A股交易规则模拟

| 规则 | 说明 |
|------|------|
| T+1 | 当日买入次日才能卖出 |
| 涨跌停 | 主板 ±10%、创业板/科创板 ±20%、北交所 ±30%、ST ±5%、跨境ETF ±15% |
| 涨停/跌停 | 涨停无法买入，跌停无法卖出 |
| 最小单位 | 买入必须为 100 股整数倍 |
| 费用 | 佣金 + 印花税（卖出）+ 过户费 |

## 开发路线图

- [x] Phase 1: 数据基础（采集 + 存储 + ETF 支持 + 增量更新）
- [x] Phase 2: 回测引擎（撮合 + 规则 + 费用 + 绩效评估）
- [x] 开盘做空回测策略（`run_limitdown_short.py`）
- [ ] Phase 3: 策略库扩展（KDJ、布林带、RSI、多因子）
- [ ] Phase 4: 风控模块（仓位控制、止损止盈、黑名单）
- [ ] Phase 5: 模拟交易
- [ ] Phase 6: Web 可视化（FastAPI + Vue 3 + ECharts）
- [ ] Phase 7: 实盘对接（QMT/miniQMT）

## 免责声明

本项目仅供学习和研究使用。量化交易存在风险，策略的历史回测表现不代表未来收益。请勿将本系统直接用于实盘交易而不经过充分验证。投资有风险，入市需谨慎。

## 许可证

MIT License
