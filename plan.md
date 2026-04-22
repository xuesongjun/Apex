# A股炒股系统 — 设计规划文档

## 1. 项目概述

设计并实现一套完整的A股量化炒股系统，涵盖行情数据采集、策略引擎、回测框架、模拟/实盘交易、风控管理及可视化监控。

---

## 2. 系统架构

```
┌─────────────────────────────────────────────────────┐
│                    前端展示层                         │
│       Web Dashboard / 移动端 / 桌面客户端             │
├─────────────────────────────────────────────────────┤
│                    API 网关层                         │
├────────┬────────┬────────┬────────┬─────────────────┤
│ 行情模块 │ 策略模块 │ 交易模块 │ 风控模块 │  回测模块    │
├────────┴────────┴────────┴────────┴─────────────────┤
│                   数据存储层                          │
│     时序数据库 / 关系数据库 / 消息队列 / 缓存          │
├─────────────────────────────────────────────────────┤
│                 外部数据源 / 交易接口                  │
│     行情API / 券商交易接口 / 财务数据 / 新闻舆情       │
└─────────────────────────────────────────────────────┘
```

---

## 3. 核心模块设计

### 3.1 行情数据模块

**职责：** 采集、清洗、存储、分发行情数据

| 项目       | 说明                                                         |
| ---------- | ------------------------------------------------------------ |
| 数据源     | Tushare、AKShare、东方财富、新浪财经、Wind（付费）           |
| 数据类型   | 日K / 分钟K / Tick级、Level1 / Level2、板块资金流向          |
| 存储方案   | 历史数据：PostgreSQL + TimescaleDB；实时缓存：Redis          |
| 实时推送   | WebSocket 接收实时行情，内部通过消息队列分发                 |

**关键设计：**

- 行情数据按 `股票代码 + 日期` 分区存储
- 增量更新机制，避免每次全量拉取
- 复权因子独立维护（前复权 / 后复权）
- 停牌、退市股票标记处理
- 数据质量校验：缺失值检测、异常值过滤

**数据表设计（核心）：**

```
stock_daily        -- 日K线数据（开高低收量额、换手率）
stock_minute       -- 分钟K线数据
stock_basic        -- 股票基础信息（代码、名称、行业、上市日期）
stock_finance      -- 财务数据（PE/PB/ROE/营收/利润）
adj_factor         -- 复权因子表
trade_calendar     -- 交易日历
index_daily        -- 指数日K线（上证、深证、创业板等）
```

---

### 3.2 策略引擎模块

**职责：** 策略定义、信号生成、参数管理

**策略分类体系：**

```
策略库
├── 技术指标策略
│   ├── 均线策略（MA/EMA 金叉死叉）
│   ├── MACD 策略（零轴上下、背离）
│   ├── KDJ 超买超卖
│   ├── 布林带突破
│   └── RSI 策略
├── 量价策略
│   ├── 放量突破（成交量 > N日均量 * 倍数）
│   ├── 缩量回调
│   └── 量价背离
├── 基本面策略
│   ├── PE/PB 低估值筛选
│   ├── 高 ROE 成长股
│   └── 财报超预期驱动
├── 多因子策略
│   ├── Alpha 因子组合（动量、价值、质量、波动率）
│   └── 因子加权评分排序
└── 机器学习策略（进阶）
    ├── LSTM / Transformer 价格预测
    └── 强化学习交易决策
```

**策略统一接口设计：**

```python
class BaseStrategy:
    def init(self, config: dict):
        """初始化策略参数"""

    def on_bar(self, bar_data: BarData) -> Signal:
        """K线驱动：每根K线触发一次"""

    def on_tick(self, tick_data: TickData) -> Signal:
        """Tick驱动：每笔行情触发"""

    def on_order(self, order: OrderData):
        """订单回报处理"""

    def on_trade(self, trade: TradeData):
        """成交回报处理"""

    def get_parameters(self) -> dict:
        """返回可调参数列表"""
```

**信号定义：**

```python
class Signal:
    code: str           # 股票代码
    direction: str      # BUY / SELL
    price: float        # 期望价格（0 表示市价）
    volume: int         # 数量（必须为 100 的整数倍）
    reason: str         # 触发原因（用于日志追踪）
    confidence: float   # 信号置信度 0.0 ~ 1.0
```

---

### 3.3 回测模块

**职责：** 历史数据模拟交易，验证策略有效性

**核心组件：**

| 组件         | 说明                                                   |
| ------------ | ------------------------------------------------------ |
| 数据加载器   | 按时间顺序回放历史K线数据                              |
| 撮合引擎     | 模拟真实交易撮合（限价单 / 市价单）                    |
| 账户管理     | 维护资金、持仓、冻结资金                               |
| 费用模型     | 佣金（万2.5）、印花税（千1 卖出）、过户费              |
| 评估引擎     | 计算各项绩效指标                                       |

**A股特殊规则模拟（必须实现）：**

```
- T+1 交易：当日买入次日才能卖出
- 涨跌停板：主板 ±10%、创业板/科创板 ±20%、北交所 ±30%
- 涨停无法买入、跌停无法卖出（模拟真实流动性）
- 停牌处理：停牌期间不产生行情、不允许交易
- 最小交易单位：买入必须为 100 股整数倍，卖出可零股
- 集合竞价时段不交易（简化处理）
- ST / *ST 股票涨跌停 ±5%
```

**绩效评估指标：**

```
├── 收益类
│   ├── 总收益率 / 年化收益率
│   ├── 基准收益率（对比沪深300）
│   └── Alpha / Beta
├── 风险类
│   ├── 最大回撤 / 最大回撤持续时间
│   ├── 年化波动率
│   ├── Sharpe 比率（无风险利率取十年国债收益率）
│   ├── Sortino 比率
│   └── Calmar 比率
└── 交易类
    ├── 总交易次数 / 胜率
    ├── 盈亏比（平均盈利 / 平均亏损）
    ├── 平均持仓天数
    └── 换手率
```

---

### 3.4 交易执行模块

**职责：** 将策略信号转化为实际委托单并管理订单生命周期

**对接方式（按推荐优先级）：**

| 方式                    | 说明                                 | 适用场景         |
| ----------------------- | ------------------------------------ | ---------------- |
| QMT / miniQMT           | 迅投提供，支持 Python 调用           | 中小资金量化交易 |
| PTrade                  | 恒生电子，券商集成度高               | 机构/大资金      |
| 券商原生API             | 华泰 / 中信等提供                    | 有开发能力的团队 |
| 东方财富模拟盘          | 免费，适合验证                       | 初期模拟测试     |

**订单管理：**

```
订单状态机：
  CREATED → SUBMITTED → PARTIAL_FILLED → FILLED
                     → REJECTED
                     → CANCELLED
```

**执行优化：**

- 大单拆分：避免冲击成本
- TWAP / VWAP 算法下单
- 滑点控制：限价单优先，超时未成交则撤单重挂

---

### 3.5 风控模块

**职责：** 事前检查 + 事中监控 + 事后分析，保护资金安全

**风控规则体系：**

```
一、仓位控制
├── 单票仓位上限：不超过总资金 20%
├── 单行业仓位上限：不超过总资金 30%
├── 总仓位上限：不超过总资金 80%
└── 新股 / 次新股仓位限制：不超过总资金 5%

二、止损规则
├── 个股止损：亏损达 -7% 强制卖出
├── 个股止盈：盈利达 +20% 触发移动止盈
├── 单日最大亏损：账户日亏 -3% 暂停当日交易
└── 最大回撤阈值：回撤 -10% 暂停全部策略

三、交易限制
├── 涨停板不追买
├── 跌停板不割肉（除非触发止损规则）
├── 单日最大交易次数限制
└── 单笔最大下单金额限制

四、黑名单过滤
├── ST / *ST 股票
├── 上市不足 N 天的次新股
├── 停牌股票
└── 用户自定义黑名单

五、异常检测
├── 策略信号频率异常告警
├── 持仓集中度告警
└── 异常大额委托告警
```

---

### 3.6 前端展示模块

**职责：** 可视化监控、策略管理、手动干预

**核心页面：**

```
├── 仪表盘（Dashboard）
│   ├── 账户总览（资金曲线、今日盈亏、持仓市值）
│   ├── 持仓明细（个股盈亏、仓位占比饼图）
│   └── 今日交易记录
├── 行情看板
│   ├── 自选股行情（TradingView K线图）
│   ├── 板块热力图
│   └── 涨跌排行
├── 策略管理
│   ├── 策略列表（启用/停用/参数配置）
│   ├── 策略信号日志
│   └── 策略绩效对比
├── 回测中心
│   ├── 回测任务创建（选策略、选时段、选股池）
│   ├── 回测结果展示（收益曲线、指标表格）
│   └── 历史回测记录
├── 风控中心
│   ├── 风控规则配置
│   ├── 告警记录
│   └── 风控触发日志
└── 系统设置
    ├── 数据源配置
    ├── 交易接口配置
    └── 通知设置（微信 / 钉钉 / 邮件）
```

---

## 4. 技术选型

| 层面       | 方案                                                       |
| ---------- | ---------------------------------------------------------- |
| 后端语言   | Python 3.11+（策略/回测/数据）+ Go（高性能撮合/网关）      |
| Web 框架   | FastAPI（REST API）+ WebSocket（实时推送）                  |
| 数据库     | PostgreSQL + TimescaleDB（时序数据）                        |
| 缓存       | Redis（实时行情缓存、会话管理）                            |
| 消息队列   | RabbitMQ（行情分发、订单流、告警通知）                      |
| 任务调度   | APScheduler / Celery（定时数据采集、策略定时执行）          |
| 前端       | Vue 3 + TypeScript + ECharts / TradingView Lightweight     |
| 容器化     | Docker + Docker Compose                                    |
| 日志监控   | ELK Stack 或 Loki + Grafana                                |

### 4.1 Web 技术路线

基于当前项目现状（核心业务已用 Python 实现，`api/` 基本为空，`frontend/` 尚未初始化），Web 技术路线确定为：

- **后端**：FastAPI + Pydantic + SQLAlchemy
- **前端**：Vue 3 + TypeScript + Vite
- **图表**：
  - 第一阶段：ECharts（净值、收益、统计图）
  - 第二阶段：TradingView Lightweight Charts（如需专业 K 线）
- **通信方式**：
  - 第一阶段：REST API + 轮询
  - 第二阶段：WebSocket（实时推送）
- **部署方式**：前后端分离，前端静态构建，Nginx/Caddy 反向代理

**不采用的路线：**

- 不把现有 Python 核心业务重写成 Go 单体
- 不采用 Next.js/全 TypeScript 全栈来承接现有回测与模拟盘逻辑

理由：

1. 现有数据、回测、模拟盘逻辑已经稳定在 Python 中
2. FastAPI 最容易复用现有 repository / ORM / paper 账户能力
3. Vue 3 + Vite 足以支撑 Dashboard / 回测中心 / 策略管理台
4. 可以先用 REST 快速出结果，后续再逐步补实时能力

### 4.2 通知技术路线

通知路线优先级确定为：

1. **邮件通知**
2. **企业微信机器人**
3. **不做个人微信**

当前第一阶段只规划 **邮件通知**。

**邮件通知路线：**

- **实现方式**：Python 标准库 `smtplib` + `email.message`
- **配置来源**：`config/settings.yaml` 中的 `notification.email`
- **敏感信息管理**：
  - 优先使用邮箱 SMTP 授权码 / app password
  - 不直接使用邮箱登录密码
- **设计要求**：
  - 提供统一通知接口，后续可平滑扩展企业微信机器人
  - 失败时必须记录日志，不允许静默吞没
  - 默认只做文本通知，HTML 富文本可后续再加

**第一批接入点：**

- `scripts/run_paper_trade.py`：每日运行摘要 / 异常失败
- `scripts/daily_update.py`：数据更新异常 / 缺失校验异常
- 系统级异常：关键流程失败时告警

**后续扩展：**

- 第二阶段再接企业微信机器人（群 Webhook）
- 若未来需要 Web UI 中的通知中心，再统一接入数据库或消息中心

**不采用个人微信通知的原因：**

- 缺少稳定、官方、可长期维护的服务端接口
- 常见方案依赖逆向协议或客户端自动化，稳定性和合规性都较差
- 不适合作为交易/模拟盘系统的正式通知链路

---

## 5. 项目目录结构

```
a-stock-trading-system/
├── config/                     # 全局配置
│   ├── settings.yaml           # 系统配置（数据源、数据库连接等）
│   └── strategies.yaml         # 策略参数配置
├── data/                       # 数据模块
│   ├── sources/                # 数据源适配器（tushare, akshare 等）
│   ├── storage/                # 数据存储层（DB 操作封装）
│   ├── models.py               # 数据模型定义（ORM）
│   └── collector.py            # 数据采集调度器
├── strategy/                   # 策略模块
│   ├── base.py                 # 策略基类（BaseStrategy）
│   ├── signals.py              # 信号定义
│   ├── technical/              # 技术指标策略
│   │   ├── ma_cross.py         # 均线交叉策略
│   │   ├── macd_strategy.py    # MACD 策略
│   │   └── bollinger.py        # 布林带策略
│   ├── fundamental/            # 基本面策略
│   └── ml/                     # 机器学习策略
├── backtest/                   # 回测模块
│   ├── engine.py               # 回测引擎
│   ├── matcher.py              # 撮合引擎（模拟交易撮合）
│   ├── account.py              # 账户管理（资金、持仓）
│   ├── fee.py                  # 费用模型
│   ├── rules.py                # A股交易规则（T+1、涨跌停等）
│   └── metrics.py              # 绩效评估指标计算
├── trading/                    # 交易执行模块
│   ├── broker/                 # 券商接口适配器
│   │   ├── base.py             # 统一交易接口
│   │   ├── qmt_broker.py       # QMT 对接
│   │   └── simulated.py        # 模拟交易
│   ├── order.py                # 订单管理
│   └── executor.py             # 执行引擎
├── risk/                       # 风控模块
│   ├── manager.py              # 风控管理器
│   ├── rules/                  # 风控规则
│   │   ├── position.py         # 仓位控制
│   │   ├── stop_loss.py        # 止损规则
│   │   ├── blacklist.py        # 黑名单
│   │   └── frequency.py        # 交易频率限制
│   └── alert.py                # 告警通知
├── api/                        # Web API
│   ├── main.py                 # FastAPI 入口
│   ├── routers/                # 路由定义
│   └── websocket.py            # WebSocket 实时推送
├── frontend/                   # 前端项目（Vue 3）
│   ├── src/
│   │   ├── views/              # 页面组件
│   │   ├── components/         # 通用组件
│   │   └── stores/             # 状态管理
│   └── package.json
├── scripts/                    # 运维脚本
│   ├── init_db.py              # 数据库初始化
│   └── daily_update.py         # 每日数据更新
├── tests/                      # 测试
│   ├── test_strategy/
│   ├── test_backtest/
│   └── test_risk/
├── docker-compose.yml          # 容器编排
├── requirements.txt            # Python 依赖
└── README.md
```

---

## 6. 开发路线图

> 说明：本节已按 **2026-04-20 当前代码状态** 同步。以下勾选反映的是仓库里**已经落地并可运行/验证**的内容，不是最初草案状态。

### Phase 1 — 数据基础（第 1-2 周）

- [ ] 搭建 PostgreSQL + TimescaleDB 数据库
- [x] 实现 Tushare / AKShare 数据源适配器
- [x] 完成股票日K线、基础信息、交易日历的采集与存储
- [x] 实现增量更新和复权因子维护
- [x] 编写数据质量校验脚本

### Phase 2 — 回测引擎（第 3-5 周）

- [x] 实现策略基类和信号定义
- [x] 实现回测撮合引擎（含A股特殊规则）
- [x] 实现账户管理（资金、持仓、冻结）
- [x] 实现费用模型（佣金、印花税、过户费）
- [x] 实现绩效评估指标计算
- [x] 用均线交叉策略跑通完整回测流程

### Phase 3 — 策略库（第 6-8 周，持续迭代）

- [x] 已实现部分策略：`ma_cross` / `macd` / `limitdown_short` / `overnight_long`
- [ ] 继续补齐 3-5 个经典技术指标策略（KDJ、布林带、RSI 等）
- [ ] 实现基本面筛选策略
- [ ] 实现多因子评分策略
- [ ] 策略参数优化工具（网格搜索 / 遗传算法）
- [ ] 策略组合与资金分配

### Phase 4 — 风控模块（第 9-10 周）

- [ ] 实现仓位控制规则
- [ ] 实现止损 / 止盈规则
- [ ] 实现黑名单过滤
- [ ] 实现异常检测与告警通知（钉钉 / 微信）
- [ ] 风控规则可配置化

### Phase 5 — 模拟交易（第 11-12 周）

- [x] 实现模拟交易接口
- [x] 策略信号 → 模拟下单全流程打通
- [x] 提供基础监控能力（CLI 状态/持仓/净值/挂单查询）
- [x] 交易日志记录与复盘（订单、持仓、净值持久化）

### Phase 6 — Web 可视化（第 13-16 周）

- [ ] FastAPI 后端 API 开发
- [ ] Vue 3 前端：仪表盘、行情看板
- [ ] K线图集成（TradingView Lightweight Charts）
- [ ] 回测中心页面
- [ ] 策略管理与风控中心页面

### Phase 7 — 实盘对接（第 17-18 周，谨慎推进）

- [ ] 对接 QMT / miniQMT 交易接口
- [ ] 小资金实盘验证（1-3 万）
- [ ] 实盘与回测结果对比分析
- [ ] 逐步放量运行

---

## 7. 风险与注意事项

### 技术风险

| 风险                   | 应对措施                                     |
| ---------------------- | -------------------------------------------- |
| 数据源不稳定 / 限频    | 多数据源备份，本地缓存，错峰采集             |
| 回测与实盘差异（滑点） | 回测加入滑点模拟，保守估算费用               |
| 策略过拟合             | 样本外测试、Walk-forward 分析、参数稳定性检验 |
| 系统宕机导致持仓风险   | 进程监控 + 自动重启 + 异常状态恢复机制       |

### 合规风险

- 程序化交易需关注交易所报备要求
- 高频交易可能触发异常交易监控
- 不得利用技术手段操纵市场

### 资金风险

- **永远不要用无法承受损失的资金进行量化交易**
- 初期小资金验证，确认策略稳定后再逐步增加
- 设置总资金最大亏损红线（如 -20% 清仓停止）

---

## 8. 待确认事项

> 在开始编码前需要确认以下问题：

- [ ] 初始资金规模和风险承受能力？
- [ ] 优先实现哪类策略（技术面 / 基本面 / 多因子）？
- [ ] 数据源选择（免费 Tushare/AKShare 还是付费 Wind）？
- [ ] 是否需要实盘交易，还是仅回测研究？
- [ ] 开户券商是哪家？（影响交易接口选择）
- [ ] 部署环境（本地 / 云服务器）？

### 当前进度总结（2026-04-20）

- 已完成：
  - 数据采集与落库主链路
  - 回测引擎主链路
  - 模拟盘主链路
  - `overnight_long` 全链路修复（回测 T 日收盘买、T+1 日开盘卖；模拟盘 14:55 买、次日开盘卖）
  - 交易明细 Daily P&L Journal 输出
  - 回测统计、初始资金口径、卖出整手规则、模拟盘账户隔离

- 进行中：
  - 文档与计划同步维护
  - 策略库逐步扩展

- 未开始 / 未完成：
  - 风控模块正式落地
  - FastAPI / Web 前端
  - 实盘对接

---

## 9. 迭代日志

### 2026-04-23 — Phase 7（实盘交易基座）启动计划

**目标**：启动 Phase 7，但第一阶段只做“实盘交易基座”，不直接进入真实券商下单。

**关联研究**：见 `research.md` → "2026-04-23 Phase 7（实盘交易基座）启动研究"

**当前判断**：

- `trading/broker/` 为空，缺少统一 broker 适配层
- 当前只有 paper 链路，没有 live 链路
- `risk/` 尚未落地，因此 Phase 7A 不能依赖完整风控模块
- 真实券商（QMT / miniQMT）细节尚未最终确定，先做 dry-run 基座更稳

**本轮建议范围（待你确认后执行）**：

| 模块 | 范围 |
|------|------|
| Broker 抽象 | 定义统一 broker 接口与数据结构 |
| Live Engine | 新增实盘执行引擎骨架 |
| DryRun | 提供 `DryRunBroker` 作为 Phase 7A 默认执行器 |
| 数据持久化 | 新增 live 账户 / 订单等最小表结构 |
| CLI | 新增 `scripts/run_live_trade.py` |
| 配置 | 在 `settings.yaml` 新增 broker 段 |

**拟改动文件**：

| 文件 | 改动 |
|------|------|
| `trading/broker/base.py` | 新增统一 broker 抽象 |
| `trading/broker/dry_run.py` | 新增 DryRunBroker |
| `trading/broker/qmt_broker.py` | 新增 QMT 适配器占位或最小壳 |
| `trading/live_engine.py` | 新增实盘执行引擎骨架 |
| `data/models.py` | 新增 live 账户 / 订单表 |
| `data/storage/repository.py` | 新增 live 表 CRUD |
| `config/settings.yaml` | 新增 `broker` 配置段 |
| `config/__init__.py` | 新增 broker 配置加载 |
| `scripts/run_live_trade.py` | 新增实盘执行 CLI |
| `README.md` | 补充 Phase 7A 启动说明 |
| `process.txt` | 记录本次 Phase 7A 基座变更 |

**实现顺序**：

1. 先定义 broker 抽象和数据结构
2. 再补 live ORM / repository
3. 实现 `DryRunBroker`
4. 实现 `live_engine`
5. 增加 `run_live_trade.py`
6. 最后补 README / process / 基础测试

**本轮不做**：

- 真实资金下单
- 完整 QMT / miniQMT 联调
- 完整成交回报同步
- 风控中心联动
- 实盘 GUI 交易台

**验收标准**：

1. 存在统一 broker 抽象层
2. 存在 `DryRunBroker`
3. 存在 `run_live_trade.py`
4. 策略信号能被翻译成统一订单请求并通过 DryRunBroker 执行
5. 订单结果能落库并可查询
6. 后续切换到真实 broker 时，不需要重写 live engine

**等待确认**：按项目规范，Phase 7 属于中大型任务。若你确认按上述 Phase 7A 范围推进，请直接回复 `GO`，我再开始编码。

### 2026-04-20 — Phase 6（Web 可视化）启动计划

**目标**：开始 Phase 6，但不一次性铺满全部 Web 功能；先落地“后端 API + 前端 Dashboard 首屏”的最小闭环。

**关联研究**：见 `research.md` → "2026-04-20 Phase 6（Web 可视化）启动研究"

**当前判断**：

- `api/` 基本为空，需要从 FastAPI 应用入口开始搭
- `frontend/` 尚不存在，需要初始化 Vue 3 + TypeScript + Vite
- `risk/` 仍未实现，因此本轮不做真正的风控中心，只保留 Phase 6 路线中的后续项

**本轮建议范围（待你确认后执行）**：

| 模块 | 范围 |
|------|------|
| 后端 | FastAPI 应用入口、只读 dashboard API、OpenAPI docs |
| 前端 | Vue 3 脚手架、Dashboard 首屏、账户概览/持仓/挂单/净值曲线 |
| 数据来源 | 仅复用现有 `PaperRepository`，不新增交易逻辑 |

**拟改动文件**：

| 文件 | 改动 |
|------|------|
| `api/main.py` | 新增 FastAPI 入口，挂载路由 |
| `api/schemas.py` | 新增接口返回 schema |
| `api/dependencies.py` | 新增 account_id/参数解析等依赖 |
| `api/routers/dashboard.py` | 新增 Dashboard 只读接口 |
| `api/routers/__init__.py` | 导出路由 |
| `frontend/package.json` | 新增前端依赖与脚本 |
| `frontend/vite.config.ts` | 新增 Vite 配置 |
| `frontend/src/main.ts` | 前端入口 |
| `frontend/src/App.vue` | 根组件 |
| `frontend/src/views/DashboardView.vue` | Dashboard 页面 |
| `frontend/src/api/dashboard.ts` | 前端调用后端 API 的封装 |
| `README.md` | 补充 Phase 6 启动方式（后端/前端开发命令） |
| `process.txt` | 记录本次 Phase 6 启动变更 |

**实现顺序**：

1. 先搭 FastAPI 应用骨架和 `/docs`
2. 暴露 Dashboard 所需只读接口
3. 初始化 Vue 3 + TypeScript + Vite
4. 做 Dashboard 首屏
5. 接通前后端
6. 补测试 / 基本运行验证

**本轮不做**：

- 回测中心完整页面
- 策略管理写接口
- 风控中心真实功能
- WebSocket 实时行情

**验收标准**：

1. 后端可通过 `uvicorn api.main:app --reload` 启动
2. `/docs` 可访问
3. 前端可通过 `npm run dev` 启动
4. Dashboard 页面能展示：
   - 账户概览
   - 当前持仓
   - 待执行订单
   - 最近净值曲线
5. 桌面端和移动端可正常显示

**等待确认**：按项目规范，Phase 6 属于中大型任务。若你确认按上述范围推进，请直接回复 `GO`，我再开始编码。

### 2026-04-20 — 交易明细重构：round-trip 视角 → 每日视角（Daily P&L Journal）

**目标**：修正用户体验问题——原 schema 第一行横跨两天（`买入日=01-05 / 卖出日=01-06`），被直觉误读为"01-05 既买又卖"。改为每行 = 一个交易日。

**关联研究**：见 `research.md` → "2026-04-20 交易明细重构：round-trip 视角 → 每日视角"

**新 schema（15 列）**

```
代码 日期 动作 开盘价 买入价 收盘价 卖出价 卖出份额 买入份额 佣金 净盈 收益率% 持仓天数 净值 动作备注
```

**动作分类**：建仓（只买）/ 换仓（先卖后买）/ 平仓（只卖）。

**核心改动**：
| 文件 | 改动 |
|------|------|
| `backtest/engine.py` | 新增 `_daily_actions` 暂存 + `_finalize_daily_trade` 日末聚合；`_process_signal` 不再直接 append `_trades` |
| `scripts/run_backtest.py` | TRADE_COLUMNS 重排 + CSV 整数列空值处理（避免 `9000.0`） |
| `README.md` | 字段说明表扩展为建仓/换仓/平仓三态 |

**口径分离**：
- `佣金` = 当日现金流口径（买+卖都计）
- `净盈` = round-trip 口径（上次买→本次卖，只扣两端佣金）
- 两者**不严格对齐**——换仓日新建仓佣金归属到下次平仓

**验证**：pytest 11/11；513090 2026-01-05~01-12 6 行输出 = 1 建仓 + 5 换仓，跨周末持仓天数=3。

---

### 2026-04-20 — 滑点模型：绝对值 → 百分比 + CLI 可配

**目标**：修正 `slippage: 0.01`（绝对元）的两个设计缺陷——低价 ETF 摩擦过重、默认无法关闭。

**关联研究**：见 `research.md` → "2026-04-20 滑点模型：绝对值 → 百分比 + CLI 可配"

**核心改动**：

| 文件 | 改动 |
|------|------|
| `config/settings.yaml` | `slippage: 0.01` → `slippage_rate: 0.0`（默认关闭） |
| `config/__init__.py` | `BacktestConfig.slippage` → `BacktestConfig.slippage_rate` |
| `backtest/engine.py` | 公式改 `exec_price × (1 ± slippage_rate)` + `round(3)`；`or` 改 `is not None` 防 falsy 坑；rate=0 时短路跳过 |
| `scripts/run_backtest.py` | 新增 `--slippage-rate RATE`，`default=None` 区分"未传" vs "传 0" |

**优先级**：`CLI --slippage-rate N  >  settings.yaml slippage_rate  >  代码兜底 0.0`

**验证**：pytest 11/11 全绿；513090 冒烟回测 rate=0 时 buy_price=bar.close 精确匹配，rate=0.0005 时 1.741→1.742、1.728→1.727 符合 `round(raw × 1.0005, 3)`。

---

### 2026-04-20 — overnight_long 切换为连续隔夜模式（模式 A → B）

> 历史记录：本段描述的是“模式 A → 模式 B”的中间迭代，后续已被“overnight_long 全链路 bug 修复（时序 / 统计 / 配置）”一节覆盖。若以当前代码为准，请优先阅读后文的全链路修复条目。

**目标**：修正 overnight_long 策略语义。原版实现"间隔一天持仓"（持仓率 50%），用户期望"每天都持仓过夜"（持仓率 100%），即每天 9:25 开盘卖 + 14:55 尾盘再买。

**关联研究**：见 `research.md` → "2026-04-20 overnight_long 切换为连续隔夜模式"

**核心改动**：

| 文件 | 改动 |
|------|------|
| `strategy/technical/overnight_long.py` | `on_bar` 从 `if / elif` 改为双独立 `if`；新增 `limit_pct` 参数 + 一字跌停判定（浮点容差 1e-6） |
| `config/strategies.yaml` | overnight_long 节新增 `limit_pct: 0.10` |
| `tests/test_overnight_long.py` | 8 → 11 用例：改 4 个断言（held_position / min_drop / max_rise / two_day_cycle），新增 3 个（一字跌停阻塞 / 被套次日恢复 / limit_pct 参数） |
| `research.md` / `plan.md` / `README.md` / `process.txt` / spec | 文档同步 |

**不改动**：`backtest/engine.py` / `backtest/account.py` / 交易明细输出（信号协议不变，引擎/账户对策略透明）。

**策略边界规则**：

- **有持仓 + 正常 bar** → 生成 `[SELL @ next_open, BUY @ close]`，引擎按列表顺序撮合（先卖释放资金，后买满仓）
- **有持仓 + 一字跌停**（`bar.open <= pre_close × (1 - limit_pct) + 1e-6`）→ SELL 阻塞，BUY 阻塞，当日零信号
- **T+1 冻结日**（持仓存在但 `available = 0`）→ SELL 跳过，BUY 也跳过（仓位仍在，资金被占）
- **涨跌幅过滤**（`min_drop_pct` / `max_rise_pct`）仅作用于 BUY 分支，SELL 不受影响

**撮合顺序依赖**：同根 bar 返回 `[SELL, BUY]` 顺序关键，依赖上次迭代已修复的 list[Signal] 处理。

**验收**：

- 11 个单测全绿（其中 1 个测试揭示了 `currently_empty` 逻辑 bug，修正后通过）
- 513090 2026-01-01~2026-04-07 回测：64 笔交易，买卖日连续（`row[N].sell_date == row[N+1].buy_date`）
- 交易数约为模式 A 两倍（从 ~393 → ~780 笔全区间预估）

---

### 2026-04-20 — overnight_long 全链路 bug 修复（时序 / 统计 / 配置）

**目标**：把 `overnight_long` 修回用户确认的严格语义：

- 回测：T 日 `close` 买入，T+1 日 `open` 卖出
- 模拟盘：T 日 14:55 近似 `close` 买入，T+1 日集合竞价挂跌停价卖出，成交价等价于 `open`

同时修复与该策略直接相关的高优先级基础设施 bug：`next_open` 语义、paper 执行链、策略配置注入、回测统计口径、paper 账户隔离、卖出整手规则。

**关联研究**：见 `research.md` → "2026-04-20 overnight_long 全链路 bug 修复研究"

**改动文件**：

| 文件 | 改动 |
|------|------|
| `strategy/technical/overnight_long.py` | 重写 `on_bar`：从“持仓日返回 SELL+BUY”改为“空仓日返回 BUY@close + SELL@next_open，持仓日只返回 SELL@next_open” |
| `backtest/engine.py` | 新增真正的 `next_open` pending 队列；次日开盘先执行 pending，再运行策略；回测结果显式携带 `initial_capital` |
| `trading/paper_engine.py` | 修正 `next_open` 卖单量解析与创建逻辑，使“今日收盘买、明日开盘卖”在 paper 端闭环成立 |
| `strategy/registry.py` | 合并 `config/strategies.yaml` 中对应策略默认参数（忽略 `enabled`） |
| `backtest/metrics.py` | 适配 Daily P&L Journal schema，按“存在卖出闭环”统计交易次数/胜率/持仓天数；接收真实 `initial_capital` |
| `scripts/run_paper_trade.py` | 生成稳定 `account_id`，让模拟盘账户按策略 / 参数 / 标的自动隔离 |
| `backtest/rules.py` | 显式校验卖出数量合法性，修复“>100 股非整手部分卖出”被放行的问题 |
| `data/sources/tushare_source.py` | 顺手修复深市指数代码错误拼成 `.SH` 的问题 |
| `tests/test_overnight_long.py` | 更新策略单测断言为新语义 |
| `tests/test_overnight_long_engines.py` | 覆盖 overnight_long 在 backtest/paper 的真实时序 |
| `tests/test_paper_trade_helpers.py` | 锁定 account_id 的稳定性与隔离性 |
| `tests/test_trading_rules.py` | 锁定卖出整手规则 |
| `README.md` / `research.md` / `process.txt` | 文档与变更日志同步 |

**影响评估**：

1. **`overnight_long` 行为会变化**
   - 旧版：依赖错误的回测 `next_open` 语义，模拟盘会跑偏
   - 新版：回测与模拟盘统一到“今日尾盘买，明早开盘卖”

2. **其它默认使用 `next_open` 的策略会被一并修正**
   - `ma_cross`
   - `macd`
   这是正向修复：原实现存在 lookahead bias，修复后会变成真正“次日开盘成交”

3. **回测摘要数字会变化**
   - `total_trades` / `win_rate` / `avg_holding_days` 会从错误值修为真实值
   - `初始资金` / `总收益率` / `总盈亏` 会去掉首日手续费污染

4. **模拟盘账户将自动隔离**
   - 相同策略 key 但不同 `--params` / `--codes` 会生成不同账户
   - `--status` / `--history` 需用与运行时相同的策略 / 参数 / 标的组合查询

**不改动**：

- 费用模型费率本身（`backtest/fee.py`）
- `limitdown_short` 的理论回测模型
- API / risk 占位模块

**执行顺序**：

1. 先修 `load_strategy()`，让 `strategies.yaml` 真正生效
2. 重构 `overnight_long` 信号语义
3. 修回测引擎 `next_open` 为真正跨日执行
4. 修 paper engine 的 pending 创建与量解析
5. 修 paper 账户隔离与卖出整手规则
6. 修 metrics / summary
7. 补集成测试并跑 `pytest`
8. 更新 README / process.txt

**验收标准**：

1. `load_strategy('overnight_long').config` 默认包含 `strategies.yaml` 中的参数
2. backtest 中 `overnight_long` 首日为 `BUY@close`，次日卖价精确取次日 `open`
3. paper 中 Day1 运行后有 1 笔 `BUY@close` + 1 笔 Day2 `pending SELL`；Day2 运行后该卖单成交且可再次生成 Day3 卖单
4. 回测摘要中的 `total_trades` 不再恒为 0
5. 模拟盘账户 ID 对相同策略/参数/标的稳定，对不同参数或标的不同
6. 非法部分 odd-lot 卖单会被拒绝，整手卖出与“一次性卖出全部零股”仍允许
7. pytest 全绿

### 2026-04-19 — 交易明细扩展 + profit 计算修正

**目标**：让回测产出的交易明细包含用户要求的 11 个字段，同时修复引擎 `profit` 只扣单边佣金的 bug。

**关联研究**：见 `research.md` → "2026-04-19 交易明细扩展 / profit 计算修正"

**改动清单**：

| 文件 | 改动 |
|------|------|
| `backtest/engine.py` | `_buy_records` 补 `commission` + `bar_open`；`_trades` 新增 `buy_open / sell_close / commission / net_equity`；修正 `profit` 扣两边佣金 |
| `scripts/run_backtest.py` | `_print_trades` 重写为 14 列中文表头；CSV 导出前 rename 为中文列名 |
| `research.md` | 新建，记录研究结论 |
| `README.md` | 补充交易明细新格式说明 |
| `process.txt` | 追加变更日志 |

**不改动**：`backtest/account.py` / `backtest/fee.py` / `backtest/metrics.py` / 所有策略文件 / 配置文件。

**输出字段设计**（中文表头，14 列）：

```
代码 | 买入日 | 卖出日 | 开盘价 | 买入价 | 收盘价 | 卖出价 | 份额 | 佣金 | 净盈 | 收益率% | 持仓天数 | 净值 | 卖出原因
```

- 开盘价 = 买入日 `bar.open`
- 收盘价 = 卖出日 `bar.close`
- 佣金 = 买入佣金 + 卖出佣金（ETF 无印花税/过户费，合并为单列）
- 净盈 = `(卖出价-买入价)*份额 - 佣金合计`
- 净值 = 卖出日 `account.equity_curve[date].total_equity`

**费用模型确认**（无需代码改动）：

- 万1费率：`settings.yaml:35 commission_rate: 0.0001` ✓
- 免5最低：`settings.yaml:37 min_commission: 0.0` ✓
- ETF 免印花税：`fee.py:57` + `account.py:82,147` 自动传 `is_etf` ✓
- ETF 免过户费：`fee.py:62` ✓

**验收标准**：

1. 控制台和 CSV 明细均为 14 列中文表头
2. `profit` 扣两边佣金后，与 `account.equity_curve` 每日资产差分一致
3. 513090 场景下"印花税/过户费"= 0（已合入 commission 单列）
4. `metrics` 指标（win_rate / avg_holding_days / sharpe 等）不变

**执行顺序**：research.md → plan.md → **用户 GO** → engine 改动 → run_backtest 改动 → 回测验证 → README + process.txt 更新 → commit + push。

---

*文档版本：v1.1 | 创建日期：2026-03-17 | 最后更新：2026-04-19*
