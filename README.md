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
│   ├── registry.py             # 策略注册表（插件入口）
│   └── technical/              # 技术指标策略
│       ├── ma_cross.py         # 均线交叉策略
│       ├── macd_strategy.py    # MACD 策略
│       ├── limitdown_short.py  # 跌停做空策略
│       └── overnight_long.py   # 隔夜多头策略
├── backtest/                   # 回测模块
│   ├── engine.py               # 回测引擎
│   ├── account.py              # 账户管理
│   ├── fee.py                  # 费用模型
│   ├── rules.py                # A股交易规则
│   └── metrics.py              # 绩效评估
├── trading/                    # 模拟盘执行
│   ├── paper_engine.py         # 模拟盘每日引擎
│   └── paper_account.py        # 持久化模拟账户
├── risk/                       # 风控模块（待开发）
├── api/                        # Web API（待开发）
├── scripts/
│   ├── init_db.py              # 数据库初始化
│   ├── daily_update.py         # 每日数据更新
│   ├── run_backtest.py         # 策略回测入口
│   ├── run_paper_trade.py      # 模拟盘运行入口
│   ├── run_limitdown_short.py  # 开盘做空回测策略（独立脚本）
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

`scripts/init_db.py` 用于创建表结构并初始化基础数据。首次运行建议至少完成一次交易日历、股票列表和目标标的日K拉取。

**参数说明：**

| 参数 | 含义 |
|------|------|
| `--start YYYY-MM-DD` | 历史数据起始日期，默认 `2020-01-01` |
| `--tables-only` | 仅创建表结构，不拉取任何数据 |
| `--stock-list-only` | 仅更新股票列表和交易日历 |
| `--codes CODE [CODE ...]` | 只拉取指定股票/ETF 的日K |

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

> 若指定的起止日期超出数据库已有范围，脚本会自动提示并给出补数据命令，按提示操作后重新运行即可。

`scripts/run_backtest.py` 是统一的回测入口。当前回测执行时序为：

- `execute_at="close"`：当日收盘价成交
- `execute_at="open"`：当日开盘价成交
- `execute_at="next_open"`：**真正挂到下一交易日开盘**成交

因此：

- `ma_cross` / `macd` 这类默认 `next_open` 的策略，信号在 T 日收盘后产生，成交在 T+1 日开盘
- `overnight_long` 的用户视角是：T 日 14:55 近似收盘价买入，T+1 日开盘卖出，随后 T+1 日 14:55 再买入

**参数说明：**

| 参数 | 含义 |
|------|------|
| `--strategy NAME` | 策略名称，当前支持 `ma_cross` / `macd` / `limitdown_short` / `overnight_long` |
| `--codes CODE [CODE ...]` | 回测标的列表 |
| `--start YYYY-MM-DD` | 回测开始日期 |
| `--end YYYY-MM-DD` | 回测结束日期，默认今天 |
| `--capital N` | 初始资金，默认 `1000000` |
| `--params key=value ...` | 覆盖策略参数；优先级高于 `config/strategies.yaml` |
| `--all` | 显示全部交易明细，默认仅显示最近 20 笔 |
| `--csv FILE` | 导出全部交易明细到 CSV |
| `--slippage-rate RATE` | 覆盖滑点百分比；`0` 表示无滑点，省略则读取 `settings.yaml` |

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

# 覆盖滑点（百分比，单位：小数；0 表示无滑点，默认读 settings.yaml 的 slippage_rate）
python scripts/run_backtest.py --strategy ma_cross --codes 000001 --start 2023-01-01 --slippage-rate 0.0005
```

**交易明细字段（15 列中文表头，UTF-8 BOM，Excel 可直接打开）：**

明细按**每日一行**组织（**Daily P&L Journal** 风格）：一行 = 一个交易日的所有动作。一行的"动作"列标注 **建仓 / 换仓 / 平仓** 三者之一。

| 列 | 含义 | 建仓行 | 换仓行 | 平仓行 |
|----|------|:------:|:------:|:------:|
| 代码 / 日期 / 动作 | 基础上下文 | ✓ | ✓ | ✓ |
| 开盘价 | 当日 open（bar 参考价，恒填） | ✓ | ✓ | ✓ |
| 卖出价 | 当日卖出成交价（按策略 `execute_at`，隔夜多头策略下 ≈ 开盘价） | 空 | ✓ | ✓ |
| 收盘价 | 当日 close（bar 参考价，恒填） | ✓ | ✓ | ✓ |
| 买入价 | 当日买入成交价（按策略 `execute_at`，隔夜多头策略下 ≈ 收盘价） | ✓ | ✓ | 空 |
| 卖出份额 | 当日卖出股数 | 空 | ✓ | ✓ |
| 买入份额 | 当日买入股数（连续隔夜换仓日两者可能不等，因价格变化） | ✓ | ✓ | 空 |
| 佣金 | **当日**所有成交佣金合计（ETF 无印花税/过户费） | ✓ | ✓ | ✓ |
| 净盈 | **本次卖出**完成的 round-trip 净盈 = `(卖出价 - 上次买入价) × 卖出份额 - 两端佣金` | 空 | ✓ | ✓ |
| 收益率% | `(卖出价 / 上次买入价 - 1) × 100` | 空 | ✓ | ✓ |
| 持仓天数 | 本次卖出日 − 上次买入日 | 空 | ✓ | ✓ |
| 净值 | 当日收盘后账户总资产 | ✓ | ✓ | ✓ |
| 动作备注 | 策略返回的 `reason` 字段（主要用于卖出动作） | 空 | ✓ | ✓ |

**口径说明**：
- "佣金"是**当日口径**（建仓日=买佣金；换仓日=卖佣金+新买佣金；平仓日=卖佣金）
- "净盈"是**round-trip 口径**，只扣该 round-trip 两端佣金（上次买 + 本次卖），不含当日新建仓的买入佣金
- 两者因此不严格对齐——想知道"今天一共花了多少手续费"看佣金列；想知道"这笔持仓赚了多少"看净盈列

```bash
# 隔夜多头策略（T 日 14:55 买 + T+1 日开盘卖）
python scripts/run_backtest.py --strategy overnight_long --codes 513090 --start 2023-01-01 --capital 500000

# 启用涨跌幅过滤（跌幅 ≥ 3% 才买，只作用于 BUY 分支）
python scripts/run_backtest.py --strategy overnight_long --codes 513090 --start 2023-01-01 --params min_drop_pct=3.0

# CLI 参数会覆盖 config/strategies.yaml 的默认配置
python scripts/run_backtest.py --strategy overnight_long --codes 513090 --start 2023-01-01 \
    --params min_drop_pct=3.0 max_rise_pct=2.0
```

**策略语义**：

- **用户视角**：T 日尾盘买入，T+1 日开盘卖出；若 T+1 日收盘继续满足条件，则再次买入并预约 T+2 日开盘卖出
- **信号时序**：空仓日返回 `BUY @ close + SELL @ next_open`；持仓日返回 `SELL @ next_open`
- **过滤参数** `min_drop_pct` / `max_rise_pct` 仅作用于 BUY（是否在今日尾盘建仓）
- `limit_pct` 已不再作为策略参数；次日开盘卖出能否成交由引擎按真实开盘涨跌停规则判定

### 4. 开盘做空策略回测

> 模拟"集合竞价挂跌停价卖出（实际以开盘价成交）+ 收盘前买入"的日内做空逻辑。若指定日期超出数据库范围，会自动提示补数据。

**参数说明：**

| 参数 | 含义 |
|------|------|
| `--code CODE` | 单一股票/ETF 代码 |
| `--start YYYY-MM-DD` | 回测开始日期 |
| `--end YYYY-MM-DD` | 回测结束日期，默认今天 |
| `--capital N` | 初始资金 |
| `--shares N` | 固定每笔股数；默认 `0` 表示按可用资金全仓 |
| `--all` | 显示全部交易明细 |
| `--csv FILE` | 导出全部交易明细 |

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

`scripts/query_stock.py` 用于核对本地数据库与网络接口数据。

**参数说明：**

| 参数 | 含义 |
|------|------|
| `--code, -c CODE` | 股票代码 |
| `--start, -s YYYY-MM-DD` | 起始日期，默认近 20 天 |
| `--end, -e YYYY-MM-DD` | 结束日期，默认今天 |
| `--source db|api|both` | 查询本地、网络或两者对比 |

```bash
# 从本地数据库查询
python scripts/query_stock.py -c 000001 -s 2023-01-03 -e 2023-01-10

# 从网络接口实时查询
python scripts/query_stock.py -c 000001 -s 2023-01-03 -e 2023-01-10 --source api

# 对比本地与网络数据
python scripts/query_stock.py -c 000001 -s 2023-01-03 -e 2023-01-10 --source both
```

### 7. 每日数据更新

`scripts/daily_update.py` 用于收盘后增量更新。

**参数说明：**

| 参数 | 含义 |
|------|------|
| `--codes CODE [CODE ...]` | 仅更新指定标的 |
| `--validate` | 更新后校验最近 7 天数据质量 |
| `--days N` | 从今天向前回补 N 天数据 |

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

编辑 `config/settings.yaml` 中的 `trading_rules` 节：

```yaml
trading_rules:
  commission_rate: 0.0001     # 佣金费率，万0.1 = 0.0001，万2.5 = 0.00025
  min_commission: 0.0         # 最低佣金（元），0 = 免五，5.0 = 最低5元
  stamp_tax_rate: 0.001       # 印花税（千1，仅个股卖出，ETF 自动免征）
  transfer_fee_rate: 0.00002  # 过户费（万0.2）
```

常见券商费率对照：

| 券商类型 | commission_rate | min_commission |
|---------|----------------|----------------|
| 万0.1 免五（主流互联网券商） | `0.0001` | `0.0` |
| 万1.5 最低5元（传统券商） | `0.00015` | `5.0` |
| 万2.5 最低5元（默认保守值） | `0.00025` | `5.0` |

> ETF 交易自动免除印花税，无需额外配置。

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
  overnight_long:
    min_drop_pct: null
    max_rise_pct: null
```

说明：

- `strategy/registry.py` 现在会自动读取 `config/strategies.yaml` 作为每个策略的默认参数
- 命令行 `--params key=value ...` 会覆盖 `strategies.yaml`
- `overnight_long` 当前可配参数只有：
  - `min_drop_pct`：当日跌幅至少达到该值才允许尾盘买入
  - `max_rise_pct`：当日涨幅超过该值则不在尾盘买入

## 模拟盘交易

> 每日收盘后运行一次，自动执行昨日挂单、生成明日委托，账户状态持久化到数据库。

> **前提**：模拟盘依赖本地数据库中的行情和交易日历数据。运行前请先执行 `python scripts/daily_update.py` 确保数据已更新至当日。若提示"不是交易日"或"无行情数据"，通常是数据库未更新所致。

`scripts/run_paper_trade.py` 当前会根据：

- `--strategy`
- `--codes`
- `--params`

生成稳定的 `账户ID`。这意味着：

- 相同策略 / 参数 / 标的组合会继续使用同一个模拟盘账户
- 只要参数或股票池不同，就会自动隔离为不同账户
- `--status` / `--history` 必须使用和运行时**完全相同**的 `--strategy --codes --params` 才能查到同一账户

**参数说明：**

| 参数 | 含义 |
|------|------|
| `--strategy NAME` | 策略名称 |
| `--codes CODE [CODE ...]` | 股票代码列表；会参与账户ID生成 |
| `--capital N` | 初始资金，仅首次创建该账户实例时生效 |
| `--date YYYY-MM-DD` | 指定运行日期，默认今天；可用于补跑历史 |
| `--params key=value ...` | 覆盖策略参数；会参与账户ID生成 |
| `--status` | 只查看账户状态、持仓和待执行订单 |
| `--history N` | 查看最近 N 天净值记录 |

```bash
# 0. 运行前先更新数据（每个交易日收盘后执行）
python scripts/daily_update.py

# 均线交叉策略：首次初始化账户 + 当日运行
python scripts/run_paper_trade.py --strategy ma_cross --codes 000001 600519 --capital 1000000

# 跌停做空策略（开盘卖出 + 收盘买入，当日执行）
python scripts/run_paper_trade.py --strategy limitdown_short --codes 513090 --capital 1000000

# 隔夜多头策略（尾盘买 / 次日开盘卖）
python scripts/run_paper_trade.py --strategy overnight_long --codes 513090 --capital 1000000

# 使用相同组合查看该账户状态
python scripts/run_paper_trade.py --strategy overnight_long --codes 513090 --status

# 带过滤参数时，会生成另一个独立账户
python scripts/run_paper_trade.py --strategy overnight_long --codes 513090 \
    --params min_drop_pct=3.0 max_rise_pct=2.0 --capital 1000000
python scripts/run_paper_trade.py --strategy overnight_long --codes 513090 \
    --params min_drop_pct=3.0 max_rise_pct=2.0 --status

# 查看账户当前状态、持仓、待执行订单
python scripts/run_paper_trade.py --strategy ma_cross --codes 000001 --status

# 查看最近 30 天净值记录
python scripts/run_paper_trade.py --strategy ma_cross --codes 000001 --history 30

# 自定义策略参数
python scripts/run_paper_trade.py --strategy ma_cross --codes 000001 \
    --params short_period=5 long_period=20

# 补跑历史日期（数据库中已有数据的日期）
python scripts/run_paper_trade.py --strategy ma_cross --codes 000001 --date 2024-03-15
```

**每日执行流程：**

| 步骤 | 动作 |
|------|------|
| 0 | 先运行 `daily_update.py` 更新行情和交易日历 |
| 1 | 加载账户（首次自动创建），T+1 解冻昨日买入持仓 |
| 2 | 加载今日 K 线（停牌标的自动跳过） |
| 3 | 执行昨日挂单（以今日开盘价成交，涨跌停/停牌自动取消） |
| 4 | 按今日收盘价更新持仓估值 |
| 5 | 运行策略：`execute_at="next_open"` → 明日挂单；`execute_at="open"/"close"` → 当日立即成交 |
| 6 | 记录今日净值快照 |

### overnight_long 模拟盘运行说明

`overnight_long` 在模拟盘中的用户视角是：

1. **T 日 14:55**：以收盘价近似买入
2. **T+1 日开盘**：执行昨日预约的 `SELL @ next_open`
3. **T+1 日收盘后**：若满足买入条件，再次买入并预约 T+2 日开盘卖出

建议操作流程：

```bash
# 第一次运行前，先把目标标的数据补齐
python scripts/init_db.py --codes 513090 --start 2023-01-01

# 每个交易日收盘后先更新数据
python scripts/daily_update.py --codes 513090

# 运行 overnight_long 模拟盘
python scripts/run_paper_trade.py --strategy overnight_long --codes 513090 --capital 1000000

# 查看账户状态（必须使用相同 --strategy/--codes/--params 组合）
python scripts/run_paper_trade.py --strategy overnight_long --codes 513090 --status
```

若你给 `overnight_long` 加过滤参数，例如：

```bash
python scripts/run_paper_trade.py --strategy overnight_long --codes 513090 \
    --params min_drop_pct=3.0
```

那么后续查看状态也必须带同样的参数：

```bash
python scripts/run_paper_trade.py --strategy overnight_long --codes 513090 \
    --params min_drop_pct=3.0 --status
```

否则查到的是另一套账户实例。

**cron 注册（每个工作日 16:30 先更新数据，16:35 再运行模拟盘）：**

```bash
# 先更新数据（16:30），再运行模拟盘（16:35）
30 16 * * 1-5  cd /path/to/Apex && .venv/bin/python scripts/daily_update.py
35 16 * * 1-5  cd /path/to/Apex && .venv/bin/python scripts/run_paper_trade.py \
               --strategy ma_cross --codes 000001 600519
```

## 可用策略

所有策略均已注册到 `strategy/registry.py`，可直接通过 `--strategy` 参数使用：

| 命令行名称 | 策略 | 适用场景 |
|-----------|------|---------|
| `ma_cross` | 均线交叉 | 趋势跟踪，短均线金叉/死叉长均线，次日开盘执行 |
| `macd` | MACD | 趋势动量，DIF/DEA 金叉死叉，次日开盘执行 |
| `limitdown_short` | 跌停做空 | 每日开盘卖出（集合竞价）+ 收盘买入，当日执行 |
| `overnight_long` | 隔夜多头（连续） | 日终视角为“尾盘买入并预约次日开盘卖出”；用户视角为“每日 14:55 买、次日开盘卖” |
| KDJ | — | 待开发 |
| 布林带 | — | 待开发 |

### 新增自定义策略（插件式接入）

1. 在 `strategy/technical/` 下新建策略文件，继承 `BaseStrategy`，实现 `name` 和 `on_bar() -> list[Signal]`
2. 在 `strategy/registry.py` 的 `STRATEGY_REGISTRY` 中添加一条记录：

```python
"my_strategy": {
    "class": "strategy.technical.my_strategy.MyStrategy",
    "description": "我的策略",
    "default_params": {"param1": 10},
},
```

3. 即可通过 `--strategy my_strategy` 在回测和模拟盘中使用，无需修改其他代码。

**`on_bar()` 信号的 `execute_at` 字段说明：**

| execute_at | 含义 |
|-----------|------|
| `"next_open"`（默认）| **下一交易日**开盘价执行，会先进入 pending 队列 |
| `"open"` | 当日开盘价执行（模拟集合竞价挂单） |
| `"close"` | 当日收盘价执行（模拟尾盘成交） |

## A股交易规则模拟

| 规则 | 说明 |
|------|------|
| T+1 | 当日买入次日才能卖出 |
| 涨跌停 | 主板 ±10%、创业板/科创板 ±20%、北交所 ±30%、ST ±5%、跨境ETF ±15% |
| 涨停/跌停 | 涨停无法买入，跌停无法卖出 |
| 最小单位 | 买入必须为 100 股整数倍；卖出超过 100 股时必须为 100 股整数倍，除非一次性卖出全部零股 |
| 费用 | 佣金 + 印花税（卖出）+ 过户费 |

## 开发路线图

- [x] Phase 1: 数据基础（采集 + 存储 + ETF 支持 + 增量更新）
- [x] Phase 2: 回测引擎（撮合 + 规则 + 费用 + 绩效评估）
- [x] 开盘做空回测策略（`run_limitdown_short.py`）
- [x] 插件化策略框架（`strategy/registry.py`，新策略一处注册即可接入回测+模拟盘）
- [x] 跌停做空策略接入模拟盘（`limitdown_short`，支持当日开盘/收盘执行）
- [ ] Phase 3: 策略库扩展（KDJ、布林带、RSI、多因子）
- [ ] Phase 4: 风控模块（仓位控制、止损止盈、黑名单）
- [x] Phase 5: 模拟交易（`scripts/run_paper_trade.py`）
- [ ] Phase 6: Web 可视化（FastAPI + Vue 3 + ECharts）
- [ ] Phase 7: 实盘对接（QMT/miniQMT）

## Phase 6 启动方式

当前已落地 **Phase 6A + 6B 最小闭环**：

- 后端：FastAPI 只读 Dashboard API
- 前端：Vue 3 + TypeScript + Vite 的 Dashboard 首屏

当前 Dashboard 可展示：

- 模拟盘账户列表
- 账户概览
- 当前持仓
- 待执行订单
- 最近净值曲线

### 后端启动

```bash
# 项目根目录
uvicorn api.main:app --reload
```

默认访问：

- 健康检查：`http://127.0.0.1:8000/health`
- OpenAPI 文档：`http://127.0.0.1:8000/docs`

主要接口：

- `GET /api/dashboard/accounts`
- `GET /api/dashboard`

说明：

- Dashboard API 只读，直接复用现有 `PaperRepository`
- 若数据库中还没有模拟盘账户，页面会显示“暂无模拟盘账户”
- 建议先运行至少一次 `scripts/run_paper_trade.py` 创建账户后再打开 Dashboard

### 前端启动

```bash
cd frontend
npm install
npm run dev
```

默认访问：

- `http://127.0.0.1:5173`

如需自定义后端地址，可设置环境变量：

```bash
VITE_API_BASE=http://127.0.0.1:8000 npm run dev
```

### 推荐体验顺序

```bash
# 1. 先确保数据库已有模拟盘账户
python scripts/run_paper_trade.py --strategy overnight_long --codes 513090 --capital 1000000

# 2. 启后端
uvicorn api.main:app --reload

# 3. 启前端
cd frontend
npm install
npm run dev
```

### 当前限制

- 目前只做只读 Dashboard，不包含策略管理写接口
- 暂未实现 WebSocket，页面数据默认通过 REST 获取
- 风控中心、回测中心完整页面、实时行情页仍未开始

## Phase 7A 实盘交易基座

当前已落地 **Phase 7A：实盘交易基座**，但这不是“真实券商已接通”的完成态，而是先把：

`策略信号 -> 统一订单请求 -> broker adapter -> 订单结果落库`

这条链路搭起来。

### 当前能力

- 统一 broker 抽象：
  - `trading/broker/base.py`
- Dry-run broker：
  - `trading/broker/dry_run.py`
- QMT 适配器占位：
  - `trading/broker/qmt_broker.py`
- 实盘执行引擎骨架：
  - `trading/live_engine.py`
- 实盘/准实盘持久化表：
  - `live_account`
  - `live_position`
  - `live_order`
- 实盘 CLI：
  - `scripts/run_live_trade.py`

### 当前限制

- 默认只支持 `dry_run` 模式
- `QmtBroker` 目前只是占位壳，还没有真实联调
- DryRunBroker 会把订单请求落库，但**不会模拟真实成交**
- 因此当前更适合验证：
  - 信号是否正确翻译成统一订单请求
  - live engine 与 broker 抽象是否合理
  - 后续真实券商适配是否能平滑接入

### broker 配置

编辑 `config/settings.yaml`：

```yaml
broker:
  mode: "dry_run"      # dry_run / live
  provider: "qmt"      # qmt / miniqmt / dummy
  account_id: ""
  endpoint: ""
  timeout: 5
```

说明：

- `mode`：
  - `dry_run`：当前推荐，安全验证执行链
  - `live`：预留给后续真实券商接入
- `provider`：
  - 当前仅 `dry_run` 真正可用
  - `qmt` 只是预留接口方向

### CLI 用法

`scripts/run_live_trade.py` 用于运行实盘交易基座。

**参数说明：**

| 参数 | 含义 |
|------|------|
| `--strategy NAME` | 策略名称 |
| `--codes CODE [CODE ...]` | 股票代码列表 |
| `--capital N` | 初始资金（仅 dry-run 首次建账户时生效） |
| `--date YYYY-MM-DD` | 指定运行日期，默认今天 |
| `--params key=value ...` | 覆盖策略参数 |
| `--mode dry_run|live` | broker 模式，默认读 `settings.yaml` |
| `--provider NAME` | broker 提供方，默认读 `settings.yaml` |

### 推荐使用方式（当前阶段）

```bash
# 1. 确保数据库中已有行情
python scripts/init_db.py --codes 513090 --start 2023-01-01

# 2. dry-run 跑一次实盘基座
python scripts/run_live_trade.py --strategy overnight_long --codes 513090 --capital 1000000
```

示例输出会包含：

- 实例ID
- broker 类型
- 生成信号数
- 构建订单数
- 提交成功/失败数

### dry-run 的意义

当前 `dry_run` 模式不会直接接真实券商，也不会模拟成交回报；它的作用是：

1. 验证策略信号到订单请求的翻译是否正确
2. 验证订单生命周期能否统一落库
3. 为后续 `QmtBroker` 真实实现提供稳定接口目标

### 下一阶段（Phase 7B）

后续接真实券商时，原则是：

- 不重写 `live_engine`
- 只实现真实 broker adapter
- 先接账户查询 / 持仓查询 / 下单 / 撤单
- 再逐步补成交回报、对账、风控联动、通知

## 免责声明

本项目仅供学习和研究使用。量化交易存在风险，策略的历史回测表现不代表未来收益。请勿将本系统直接用于实盘交易而不经过充分验证。投资有风险，入市需谨慎。

## 许可证

MIT License
