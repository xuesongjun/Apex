# 研究笔记

本文件记录每次迭代的研究结论与关键发现，按时间倒序追加。

---

## 2026-04-23 Phase 7B（QMT / miniQMT adapter）研究补充

### 当前可落地范围

在当前环境里无法完成真正的 QMT 联机验证，因为：

- 未安装 `xtquant`
- 无真实 QMT / miniQMT 客户端环境
- 无真实账户

但这并不妨碍把 **adapter 代码层** 做到可联调状态。

### 本轮应达到的目标

1. `QmtBroker` 不再是空壳
2. 支持：
   - connect / subscribe
   - 账户查询
   - 持仓查询
   - 即时下单
   - 撤单
   - 订单列表查询
3. `next_open` 计划单由 `LiveEngine` 在执行日激活
4. `miniqmt` 作为 `qmt` 的同路径别名支持

### 明确不在本轮范围

- 真实环境联调
- 成交回报 callback 持久化
- 自动对账修复
- 风控联动拦截
- 生产级异常恢复

### 设计结论

- `QmtBroker` 应保持 **懒加载 xtquant**
  - 避免在无 QMT 环境时影响其它功能
- `run_live_trade.py --mode live --provider qmt|miniqmt`
  - 应能直接构造 `QmtBroker`
- 若 `xtquant` 缺失，应报出清晰错误，而不是静默失败
- planned `next_open` 订单不要直接交给 `QmtBroker`
  - 应先落 `planned`
  - 到执行日由 `LiveEngine` 激活并再次调用 `submit_order()`

### 验证策略

真实环境不可用时，用 fake `xtquant` 模块验证：

- 账户映射
- 持仓映射
- 下单参数映射
- planned 订单在执行日激活

这样至少能把 adapter 逻辑锁住，后续真实联调只剩环境问题。

---

## 2026-04-23 Phase 7（实盘交易基座）启动研究

### 当前代码现状

仓库中与交易执行直接相关的能力目前只有：

- `trading/paper_engine.py`：模拟盘每日引擎
- `trading/paper_account.py`：模拟盘持久化账户
- `data/models.py` / `data/storage/repository.py`：`paper_account / paper_position / paper_order / paper_nav`

当前缺失：

- `trading/broker/` 为空，没有真实 broker 适配层
- 没有统一的“实盘订单请求 / 券商订单状态 / 券商持仓 / 券商账户”抽象
- 没有 `live_engine` / `executor` 这种把策略信号翻译成券商委托的基座
- 没有 dry-run / live 切换机制
- 没有实盘订单持久化表
- 风控模块还未实现，因此 Phase 7 第一阶段不能假设有完整风控可复用

### 结论：Phase 7 第一阶段必须先做“基座”，不能直接做完整实盘

现阶段如果直接做：

- QMT 下单
- 券商账户同步
- 实盘持仓管理
- 风控联动

会把 broker 细节、通知、风控、订单生命周期全部耦在一起，后面很难维护。

因此 Phase 7 第一阶段应只做 **实盘交易基座**，目标是把“策略信号 -> 统一订单请求 -> broker 适配器 -> 订单回报 / 状态持久化”这条链打通。

### 推荐的第一阶段范围（Phase 7A）

1. **统一 broker 抽象层**
   - `BaseBroker`
   - `BrokerAccount`
   - `BrokerPosition`
   - `BrokerOrder`
   - `BrokerOrderRequest`

2. **实盘执行引擎骨架**
   - 新增 `trading/live_engine.py`
   - 职责：
     - 加载策略
     - 读取账户/持仓
     - 生成统一委托请求
     - 调用 broker 下单
     - 记录结果

3. **dry-run broker**
   - 第一阶段先做一个 `DryRunBroker`
   - 不连真实券商
   - 只把委托请求落库 / 打日志 / 发送通知
   - 用它验证基座结构是否合理

4. **QMT/miniQMT 适配器占位**
   - 新增 `QmtBroker` 桩实现或最小接口壳
   - 明确 TODO，不在第一阶段硬接真实客户端

5. **实盘订单持久化**
   - 新增真实交易相关表，至少包括：
     - `live_account`
     - `live_order`
     - `live_fill`（如本阶段不做可先留后续）

6. **通知挂点**
   - 只挂邮件接口位置
   - 第一阶段不把完整邮件系统做完

### 为什么先做 DryRunBroker

因为你还没有最终确认真实券商接口细节（QMT / miniQMT / 其他），而且当前环境也不适合直接联真实交易端。

DryRunBroker 的价值：

- 验证实盘基座结构
- 不引入真实资金风险
- 给后续 QMT 适配器一个明确接口目标
- 可先通过 CLI / API / Web 面板查看“准备下什么单”

### 推荐的代码结构

建议第一阶段新增或扩展：

- `trading/broker/base.py`
- `trading/broker/dry_run.py`
- `trading/broker/qmt_broker.py`（占位）
- `trading/live_engine.py`
- `trading/models.py`（若不放到 `data/models.py`）
- `scripts/run_live_trade.py`

若继续沿用现有 ORM 风格，也可以把 live 表直接加到 `data/models.py`。

### 配置建议

`config/settings.yaml` 新增：

```yaml
broker:
  mode: "dry_run"   # dry_run / live
  provider: "qmt"   # qmt / miniqmt / dummy
  account_id: ""
  endpoint: ""
  timeout: 5
```

说明：

- `mode` 用于全局切换 dry-run 与 live
- `provider` 指定 broker 适配器
- 凭据类内容不要直接硬编码到仓库里，建议后续走本地配置或环境变量

### 第一阶段不做的内容

- 不直接接真实资金下单
- 不做完整成交回报同步
- 不做复杂风控联动
- 不做持仓对账自动修复
- 不做 GUI/可视化的实盘交易台

### 验收标准（Phase 7A）

1. 有统一 broker 抽象接口
2. 有 `DryRunBroker`
3. 有 `run_live_trade.py` 或等价 CLI
4. 策略信号可被翻译成统一订单请求并通过 DryRunBroker 执行
5. 订单结果能落库并可查询
6. 后续接 QMT 时无需重写 live engine，只需实现 broker adapter

### 风险提示

Phase 7 一旦进入真实券商对接，就是高风险区域。第一阶段一定要把目标限定在“基座 + dry-run”，不要把“真实下单成功”作为首要目标。

---

## 2026-04-20 Phase 6（Web 可视化）启动研究

### 当前代码基础

已确认可直接复用的后端能力：

- **数据库与 ORM**：`data/models.py` 已包含股票、行情、复权、模拟盘账户/持仓/订单/净值模型
- **数据读取**：`data/storage/repository.py` 已有 `StockRepository` / `PaperRepository`
- **回测结果**：`backtest/engine.py` 已能输出净值曲线与 Daily P&L Journal
- **模拟盘状态**：`trading/paper_engine.py` 与 `scripts/run_paper_trade.py` 已有账户、持仓、挂单、净值查询链路

当前缺口：

- `api/` 基本为空，尚无 FastAPI 入口、路由、schema、依赖注入
- 仓库中尚无 `frontend/` 目录，也没有 Node/Vite/TypeScript 工具链
- `risk/` 仍为占位模块，因此 Phase 6 中“风控中心”暂时只能做占位页或只读接口

### 结论：Phase 6 不应一次性全做完

按当前项目状态，Phase 6 必须拆成可落地的增量：

1. **Phase 6A：后端 API 基础设施 + Dashboard 只读接口**
   - FastAPI 应用入口
   - 健康检查
   - Dashboard 总览接口（账户总览、持仓、待执行订单、净值）
   - 回测结果查询接口（只读）
   - OpenAPI / docs

2. **Phase 6B：前端脚手架 + Dashboard 首屏**
   - Vue 3 + TypeScript + Vite
   - 首页仪表盘
   - 账户概览卡片
   - 持仓表格
   - 净值曲线

3. **Phase 6C：回测中心**
   - 历史回测任务列表
   - 回测摘要与交易明细查看

4. **Phase 6D：策略管理 / 风控中心**
   - 策略列表
   - 参数查看/编辑
   - 风控中心先做占位或只读视图

### 推荐本次编码范围

建议本轮只做 **Phase 6A + 6B 的最小闭环**，理由：

- 当前后端已有数据模型和查询能力，最容易快速出结果
- 先有 API，再接 Vue 前端，结构最稳
- `risk/` 尚未落地，风控中心现在直接做会制造大量假接口

### 推荐 UI 范围（第一版）

第一版页面只做一个 **Dashboard**：

- 账户总览：总资产、现金、持仓市值、累计收益
- 持仓列表：代码、份数、成本价、现价、浮盈亏
- 待执行订单：方向、代码、数量、执行日、原因
- 净值曲线：最近 N 天

数据来源全部基于现有 `PaperRepository`，避免引入额外业务逻辑。

### 主要技术决策

- **后端**：FastAPI + Pydantic v2 风格 schema
- **前端**：Vue 3 + TypeScript + Vite
- **图表**：首版优先 ECharts（项目已在规划中提到，接入成本较低）
- **接口风格**：只读 GET API 优先，先不做写接口
- **运行方式**：
  - 后端：`uvicorn api.main:app --reload`
  - 前端：`npm run dev`

### 需要避免的陷阱

1. **直接把 CLI 逻辑搬进 API**
   - CLI 负责打印和交互；API 应直接依赖 repository/service 返回结构化数据

2. **一次上来做完整策略管理 / 风控中心**
   - 当前 `risk/` 没有实现，直接做前端会导致大量伪功能

3. **把 account_id 逻辑只放在前端**
   - 后端接口必须显式支持按 `strategy / codes / params` 或稳定 `account_id` 查询

### 建议的第一批文件

若进入编码，建议第一批只涉及：

- `api/main.py`
- `api/schemas.py`
- `api/dependencies.py`
- `api/routers/dashboard.py`
- `api/routers/__init__.py`
- `frontend/package.json`
- `frontend/vite.config.ts`
- `frontend/src/main.ts`
- `frontend/src/App.vue`
- `frontend/src/views/DashboardView.vue`
- `frontend/src/api/dashboard.ts`

### 验收标准（第一阶段）

1. 启动 FastAPI 后可访问 `/docs`
2. 启动前端后首页能正常加载
3. Dashboard 能展示一个模拟盘账户的：
   - 账户概览
   - 持仓列表
   - 待执行订单
   - 最近净值曲线
4. 移动端与桌面端都能正常显示

---

## 2026-04-20 overnight_long 全链路 bug 修复研究

### 用户目标语义（明确口径）

用户确认的目标不是“信号层面大致类似”，而是严格的交易时序：

1. **回测**
   - T 日按 `close` 买入
   - T+1 日按 `open` 卖出

2. **实战 / 模拟盘**
   - T 日 14:55 买入，近似 `close`
   - T+1 日集合竞价挂跌停价卖出，成交价等价于 `open`

因此，系统必须支持“**收盘建仓 -> 次日开盘平仓**”这个跨日时序，不能再依赖当前实现里对 `next_open` 的“同 bar 开盘价立即成交”近似。

### 核心问题 1：回测引擎的 `next_open` 语义错误

当前 `backtest/engine.py` 中，策略在处理当天 bar 后立即处理信号：

- `execute_at="close"` → 当前 bar `close`
- 其余（含 `next_open`）→ 当前 bar `open`

这意味着 `next_open` 并没有被挂到下一交易日执行，而是被错误地在**当前 bar**用 `open` 成交。对多数“当日收盘出信号、次日开盘成交”的策略，这会产生标准的 lookahead bias。

`overnight_long` 之所以“看起来大致正确”，只是因为它当前在 **T+1 bar** 上生成 `SELL @ next_open`，引擎又把这个信号落在同一根 **T+1 bar.open** 成交，结果碰巧接近了用户想要的卖出价。但这不是一个可复用、可证明正确的机制。

### 核心问题 2：`overnight_long` 的当前信号设计依赖了上述错误语义

当前 `strategy/technical/overnight_long.py` 在“有可卖仓位且非一字跌停”时返回：

- `SELL @ next_open`
- `BUY @ close`

这是建立在“同一根 bar 上既能看到今天的收盘，又能把 `next_open` 直接落到今天开盘”这个错误机制上的。

若把 `next_open` 修正为真正跨日挂单，当前策略会变成：

- 今天持仓未卖出
- 今天收盘又买入
- 明天开盘才卖

即仓位被重复累加，模拟盘更会直接跑偏。

### 正确的 `overnight_long` 策略语义

在“收盘后统一运行”的引擎模型下，`overnight_long` 的日终信号应改为：

1. **若今日收盘后将持有隔夜仓位**
   - 生成 `SELL @ next_open`（给明早）

2. **若当前收盘时为空仓且买入过滤通过**
   - 生成 `BUY @ close`（今天尾盘）

换句话说，空仓日应返回 **`[BUY @ close, SELL @ next_open]`**，而不是当前的“有仓日返回 `[SELL @ next_open, BUY @ close]`”。

这样才能在 paper/backtest 两端都满足：

- Day T 收盘买入
- Day T+1 开盘卖出
- Day T+1 收盘再次买入

### 核心问题 3：paper engine 与 `overnight_long` 当前严重不一致

`trading/paper_engine.py` 的执行顺序是：

1. 执行昨日 pending（今日开盘）
2. 当日收盘后运行策略
3. 当日执行 `open/close`
4. 为明天创建 `next_open` pending

在这个真实跨日模型下，当前 `overnight_long` 返回的 `SELL @ next_open + BUY @ close` 会导致：

- 当日先买
- 卖单推迟到明天
- 甚至因为挂单量按 `available` 解析，卖不掉当日刚买的仓位

这是本次修复的最高优先级 bug。

### 核心问题 4：策略配置文件未实际生效

`config/strategies.yaml` 虽被加载到 `config.STRATEGY_CONFIG`，但 `strategy/registry.py:load_strategy()` 并未合并该配置，只用了注册表硬编码默认值 + CLI `--params`。

这导致：

- `overnight_long.limit_pct` 在无 CLI 覆盖时不会进入实例配置
- README 中“编辑 `config/strategies.yaml`”的描述与实际行为不一致

### 核心问题 5：回测统计口径在交易明细重构后失真

交易明细从 round-trip schema 改成 Daily P&L Journal 后，`backtest/engine.py` 写入的是：

- `action`
- `sell_price`
- `buy_price`
- `profit`

不再写入原先的 `direction`

但 `backtest/metrics.py` 仍按 `t.get("direction") == "SELL"` 识别成交闭环，导致：

- `total_trades`
- `win_rate`
- `profit_loss_ratio`
- `avg_holding_days`

在当前版本下都可能退化为 0 或明显失真。

### 核心问题 6：回测初始资金口径被第一天手续费污染

`BacktestResult.print_summary()` 和 `calculate_metrics()` 都把 `equity_curve[0]["total_equity"]` 当作“初始资金”。但 `equity_curve` 的第一条记录是在**首个交易日成交之后**才写入的。

对 `overnight_long` 这类首日大概率会买入的策略，首日手续费会让第一条净值低于真实初始资金，从而污染：

- 初始资金展示
- 总收益率
- 年化收益率
- 总盈亏

### 核心问题 7：模拟盘账户未按参数 / 标的隔离

`run_paper_trade.py` 和 `trading/paper_engine.py` 之前都默认把 `strategy.name` 当作模拟盘账户主键。

这会导致：

- 同一策略不同参数共享同一账户
- 同一策略不同股票池共享同一账户
- `--status` / `--history` 查到的账户可能不是当前实验那一套

对 `overnight_long` 这种 `name` 固定为 `"overnight_long"` 的策略尤其危险，多次试验会出现“串仓 / 串挂单 / 串净值”。

### 核心问题 8：卖出整手规则实现与注释不一致

`TradingRules.round_volume()` 的注释写的是：

- 卖出可以不足 100 股一次性卖出
- 超过 100 股的部分必须为 100 的整数倍

但实现实际上对卖出直接 `return volume`，没有任何校验。

这意味着以下非法卖单会被错误放行：

- 持仓 350 股，只卖 250 股
- 持仓 900 股，只卖 550 股

而这些都不符合注释声明的交易规则。

### 核心问题 9：Tushare 深市指数代码后缀错误

`data/sources/tushare_source.py` 在获取指数数据时，把所有指数都拼成 `.SH`。

因此若 AKShare 失败、系统回退到 Tushare：

- `399001`
- `399006`

这类深市指数会被错误查询为上交所代码。

### 修复策略

本次修复按以下顺序落地：

1. **先修执行时序**
   - backtest 引入真正的 `next_open` pending 队列
   - paper 保留 pending 模型，但修正卖单量解析与 `overnight_long` 信号语义

2. **再修策略语义**
   - `overnight_long` 改为“空仓日返回 `BUY @ close + SELL @ next_open`”
   - “持仓日”只负责为明早挂卖单，不再同日追加 `BUY @ close`

3. **最后修统计与配置**
   - `load_strategy()` 合并 `strategies.yaml`
   - metrics 改为按“有卖出闭环”的 daily journal 识别交易
   - metrics/summary 显式使用真实 `initial_capital`
   - paper 账户实例按“策略 key + 参数 + 标的”稳定隔离
   - 卖出整手规则显式校验，不再默认放行

### 预期影响面

| 文件 | 改动 |
|------|------|
| `strategy/technical/overnight_long.py` | 重写 `on_bar` 信号语义 |
| `backtest/engine.py` | 引入 `next_open` pending 跨日执行；修正 summary 初始资金 |
| `trading/paper_engine.py` | 修正 `next_open` 挂单量解析与 `overnight_long` 执行时序 |
| `strategy/registry.py` | 合并 `config/strategies.yaml` 默认参数 |
| `backtest/metrics.py` | 适配 daily journal 交易统计口径；接收真实初始资金 |
| `scripts/run_paper_trade.py` | 生成稳定 `account_id`，让 paper 账户按参数 / 标的隔离 |
| `backtest/rules.py` | 显式实现卖出数量合法性校验 |
| `data/sources/tushare_source.py` | 修复深市指数 `.SZ` / `.SH` 后缀 |
| `tests/test_overnight_long.py` | 更新策略单测断言 |
| `tests/test_paper_trade_helpers.py` | 锁定 paper 账户 ID 的稳定性与隔离性 |
| `tests/test_trading_rules.py` | 锁定卖出整手规则 |
| `tests/` 新增集成测试 | 覆盖 overnight_long 在 backtest/paper 的真实时序 |

---

## 2026-04-20 交易明细重构：round-trip 视角 → 每日视角（Daily P&L Journal）

### 背景

方案 A 切换触发：用户看到 `2026-01-05 | 2026-01-06 | 开盘价 2.046 | 买入价 2.107 | 收盘价 2.232 | 卖出价 2.107` 这一行，直觉理解为"01-05 当天既买又卖"，追问"第一次建仓 第一天不应该有卖出"。

### 根本矛盾

原明细是 **round-trip 视角**：每行 = 一次"买入日 → 卖出日"配对。在连续隔夜策略下，01-05 的建仓买入被 hoist 到行 1 里和 01-06 的卖出组成一个 pair，但视觉上像是"01-05 这一天发生了买卖"。

对长期持仓策略这种 schema 问题不大（买入日和卖出日差几十天），但对"每天都换手"的隔夜策略，第一行"跨越两个交易日"的语义极易误读。

### 新 schema：Daily P&L Journal（按日视角）

每行 = 一个交易日的所有动作。动作分三种：

| 动作 | 条件 | 典型场景 |
|------|------|----------|
| 建仓 | 当日只有买入 | 第一次进场；或上次被一字跌停套完后恢复 |
| 换仓 | 当日先卖后买 | 连续隔夜策略的"常态"每日形态 |
| 平仓 | 当日只有卖出 | 最后一日策略停更买；或过滤器挡住 BUY |

### 字段重排（14 → 15 列）

```
代码 日期 动作 开盘价 买入价 收盘价 卖出价 卖出份额 买入份额 佣金 净盈 收益率% 持仓天数 净值 动作备注
```

关键变化：
1. `买入日 + 卖出日` 合并为单列 `日期`（同日）
2. `份额` 拆为 `卖出份额 + 买入份额`——换仓日两者可能**不等**（卖 9000 股收回的现金 × 涨价后 = 买 8500 股）
3. 新增 `动作` 列标识行类型
4. 字段的"空缺规则"表达"该行无此动作"：
   - 建仓：卖出列空（`收盘价 / 卖出价 / 卖出份额 / 净盈 / 收益率 / 持仓天数`）
   - 平仓：买入列空（`买入价 / 买入份额`）

### 口径分离：当日佣金 vs round-trip 净盈

**佣金列** = 当日实际支付佣金（建仓=买佣金；换仓=卖+新买；平仓=卖佣金）。

**净盈列** = 本次卖出对应 round-trip 的净盈（当日卖 vs 上次建仓买 两端佣金都扣）。

两者**不对齐**——换仓日的"佣金"含了新建仓的买入佣金，但这笔"新建仓佣金"归属到下次平仓的 round-trip 里。

这个设计取舍：
- 若坚持 round-trip 全对齐（净盈 - 佣金 = 净收益），则佣金列也要只算 round-trip 两端 → 换仓日的"新建仓买佣金"无处归属
- 所以分离：佣金是"现金流口径"，净盈是"交易闭环口径"

### 实现：日末聚合

改动位置 `backtest/engine.py`：

1. `__init__`：新增 `self._daily_actions: dict[str, dict]`
2. `_process_signal`：BUY/SELL 成功后只写 `_daily_actions[code]["buy"/"sell"]`，不再直接 append `_trades`
3. `run()` 每日循环末尾（`record_equity` 之后）调 `_finalize_daily_trade(td, bar_map)`
4. `_finalize_daily_trade`：按 code 聚合 buy/sell 两组动作为一条 `_trades` 记录，action 判定为 "建仓/换仓/平仓"

为什么 `_finalize_daily_trade` 放在 `record_equity` 之后：明细里的"净值"列取当日收盘的 `account.total_equity`，必须在资产更新完成后再读。

### CSV 导出的 pandas 坑

`sell_volume / buy_volume / holding_days` 是 int 类型，但建仓/平仓行有 None 值。pandas 遇 None 会把 int 列升 float，CSV 输出 `9000.0` 而非 `9000`。解决：导出前把这三列 `.map(lambda v: "" if None else str(int(v)))`，让它变成 object/string 列再写。

控制台打印侧已有空值容错（`if raw is None or (isinstance(raw, float) and raw != raw): ""`），不需改动。

### 影响面

| 文件 | 改动 |
|------|------|
| `backtest/engine.py` | 新增 `_daily_actions` + `_finalize_daily_trade`；`_process_signal` 不再直接 append `_trades` |
| `scripts/run_backtest.py` | TRADE_COLUMNS 重排 + CSV 整数列空值处理 |
| `README.md` / `plan.md` / `process.txt` | 同步字段说明 |

### 验收

- 11/11 pytest 全绿（测试针对 on_bar 不过引擎，不受影响）
- 513090 2026-01-05~01-12 冒烟回测 6 行输出：第 1 行"建仓"卖出列全空 ✓；2-6 行"换仓"双面字段齐全 ✓；持仓天数跨周末=3 ✓
- CSV 导出 `sell_volume=9000` 而非 `9000.0` ✓

---

## 2026-04-20 滑点模型：绝对值 → 百分比 + CLI 可配

### 背景

用户在交易明细中发现 `买入价 2.242 ≠ 买入日 close 2.232` 的差异 0.010 元——恰好是 `settings.yaml` 里的 `slippage: 0.01`（绝对值）。该模型有两个设计缺陷：

1. **绝对滑点在不同价位上的摩擦系数不一致**：2 元股的 0.01 元 = 50bp；200 元股的 0.01 元仅 0.5bp。策略跨品种回测时摩擦成本失真。
2. **默认值强制施加**：用户没有选择"无滑点"的途径，且 0.01 的默认对低价 ETF（如 513090 in ~2元区间）明显偏高。

### 新模型

绝对值 → **百分比 × 基价**，buy 向上偏，sell 向下偏：

```python
if self.slippage_rate:
    if signal.direction == Direction.BUY:
        exec_price *= 1 + self.slippage_rate
    else:
        exec_price *= 1 - self.slippage_rate
    exec_price = round(exec_price, 3)
```

- **`if self.slippage_rate:` 短路**：`slippage_rate=0` 时完全跳过，`exec_price` 保持原 bar 浮点精度（避免无意义的 round 损失）
- **`round(..., 3)`**：A 股最小价位 0.001 元，与真实撮合一致
- **默认值改为 `0.0`**：用户在 `settings.yaml` 或 CLI 显式设置才启用；避免"藏在默认值里的假设"影响策略判断

### 配置路径（3 层覆盖优先级）

```
CLI --slippage-rate N  >  settings.yaml slippage_rate  >  代码兜底 0.0
```

CLI 参数用 `type=float, default=None` 让"未传" vs "传 0"可区分——传了 0 走 `BacktestEngine.slippage_rate=0`（真的无滑点），没传时 `None` 交给 `__init__` 读 yaml。

### 与 `or` 的一个坑

构造函数旧代码 `self.slippage = slippage or BacktestConfig.slippage`——若 `slippage=0` 会被 `or` 当 falsy 掉进 yaml 默认，永远关不掉滑点。新代码改为 `None` 显式判断：

```python
self.slippage_rate = (
    slippage_rate if slippage_rate is not None else BacktestConfig.slippage_rate
)
```

### 验证

| 场景 | buy_price 预期 | sell_price 预期 |
|------|---------------|----------------|
| slippage_rate=0 | bar.close | bar.open |
| slippage_rate=0.0005 | round(bar.close × 1.0005, 3) | round(bar.open × 0.9995, 3) |

实测 513090 2026-04-01 bar.close=1.741 → 1.742（+0.0005）；2026-04-02 bar.open=1.728 → 1.727（-0.0005）。符合。

### 影响面

| 文件 | 改动 |
|------|------|
| `config/settings.yaml` | `slippage: 0.01` → `slippage_rate: 0.0` |
| `config/__init__.py` | `BacktestConfig.slippage` → `BacktestConfig.slippage_rate` |
| `backtest/engine.py` | 构造参数重命名 + 公式改乘法 + `if self.slippage_rate:` 短路 |
| `scripts/run_backtest.py` | 新增 `--slippage-rate` CLI 参数 |
| `README.md` / `plan.md` / `process.txt` | 同步文档 |

---

## 2026-04-20 overnight_long 切换为连续隔夜模式（模式 A → B）

### 背景

用户回测后发现交易间隔一天（01-05 买 / 01-06 卖 / **01-06 空仓** / 01-07 买），与真实"隔夜因子"策略语义不符。用户期望每天都持仓过夜：01-05 买 → 01-06 开盘卖 → **01-06 尾盘再买** → 01-07 开盘卖 → …

### 原有逻辑（模式 A，间隔持仓）

`strategy/technical/overnight_long.py:28-63` 用 `if / elif` 互斥结构：

```python
if pos and pos.available > 0:
    → SELL @ next_open
elif not has_position(...):
    → BUY @ close
```

持仓状态下只走 SELL 分支，BUY 分支被 `elif` 跳过。即使当 bar 内 SELL 成交释放了资金，BUY 已不会再被评估。结果：持仓率 ~50%。

### 新逻辑（模式 B，连续隔夜）

核心改动：`if / elif` → **双独立 if**，再加一个"本 bar 即将清仓"的状态假设。

```python
has_sellable  = pos and pos.available > 0
sell_blocked  = has_sellable and (bar.open <= limit_down_price + 1e-6)

# 独立判断 1：挂卖单
if has_sellable and not sell_blocked:
    → SELL @ next_open

# 独立判断 2：挂买单（空仓 OR 即将通过 SELL 清仓）
currently_empty = pos is None or pos.volume == 0
will_sell_all   = has_sellable and not sell_blocked
if (currently_empty or will_sell_all) and 过滤通过:
    → BUY @ close
```

### 一字跌停判定

`BarData` 无 limit 字段，需自行算：

```python
limit_down_price = round(pre_close * (1 - limit_pct), 3)
sell_blocked = bar.open <= limit_down_price + 1e-6
```

- **浮点容差 1e-6**：防止 `bar.open=2.0970001` 与 `limit_down=2.097` 的末位误差导致误判
- **limit_pct 参数化**：默认 0.10（主板 / 跨境 ETF），创业板/科创板 ETF 传 0.20
- 一字跌停时：SELL 阻塞（卖不出）+ BUY 阻塞（持仓占用资金），当日无任何信号

### 一个漏网 bug（已修）

首次实现里 `will_be_empty = (not has_sellable) or (...)` 把"没有可卖仓位"等同于"空仓"，漏了 **T+1 冻结日**（pos 存在但 available=0）这种"仓位仍在只是锁着"的状态。单测 `test_position_with_zero_available_skips_sell` 直接捕获了这个逻辑错误。

修正为显式判空：`currently_empty = pos is None or pos.volume == 0`。

### 涨跌幅过滤的语义变化

**原（模式 A）**：过滤生效时整根 bar 跳过（return 前 BUY 分支尚未生成）

**新（模式 B）**：过滤**只作用于 BUY 分支**。持仓状态下即使 BUY 被过滤挡住，SELL 仍会照常挂单。语义上"过滤是进场条件，不是持仓条件"——被套时依然按常规出场逻辑卖。

### 撮合顺序依赖

同一根 bar 策略返回 `[SELL, BUY]`，引擎按列表顺序处理：
1. SELL @ open 执行 → 资金释放
2. BUY @ close 执行 → 用释放的资金满仓买

这个顺序依赖的前提是**上次迭代已修的 `_run_strategy` list-vs-single-Signal bug**（`trading/paper_engine.py` 和 `backtest/engine.py`）。如果那个 bug 还在，第二个信号会被吞掉。

### 影响面

| 文件 | 改动 |
|------|------|
| `strategy/technical/overnight_long.py` | 重写 `on_bar`，18 → 35 行 |
| `config/strategies.yaml` | 新增 `limit_pct: 0.10` |
| `tests/test_overnight_long.py` | 改 4 个断言 + 新增 3 个用例，共 11 个（原 8） |
| 引擎 / 账户 / 交易明细输出 | **不改**（信号协议不变） |

### 验收

- 11 个单测全绿（其中 1 个发现了 currently_empty 的 bug，修后通过）
- 513090 2026-01-01~2026-04-07 回测：64 笔交易，买卖日期连续（row N sell_date = row N+1 buy_date）
- 交易数约为模式 A 的 2 倍（~50% vs ~100% 持仓率）

---

## 2026-04-19 交易明细扩展 / profit 计算修正

### 背景

用户运行 overnight_long 策略回测后反馈：交易明细信息太少，要求包含 11 列：
开盘价、卖出价、卖出份额、买入价、买入份额、收盘价、佣金、净盈、收益率、持仓天数、净值。

### 现状定位

项目根目录的 `trades.csv` 是**用户手工放置的参考样例**（日期 2020-03-26，而项目数据库从 2023-01-01 起），**不是本回测引擎产出的**。引擎真实产出在两个地方：

| 产出点 | 代码位置 | 现有字段数 |
|--------|----------|-----------|
| 控制台表格 | `scripts/run_backtest.py:192-220` 的 `_print_trades` | 10 列 |
| CSV 导出 | `scripts/run_backtest.py:164` 的 `trades_df.to_csv()` | 11 列（英文） |

所有 trade 字典在 `backtest/engine.py:269-281` 组装，结构为：
```python
{
    "code", "direction",
    "buy_price", "sell_price", "volume",
    "profit", "profit_pct", "holding_days",
    "buy_date", "sell_date", "reason",
}
```

### 需求字段映射

| 需求字段 | 现状 | 数据源 | 备注 |
|---------|------|--------|------|
| 开盘价（买入日开盘价） | 未存 | `BarData.open`（买入日） | 方案 A：反映"尾盘买 vs 早盘买"择时成本 |
| 卖出价 | ✅ `sell_price` | 卖出 order `exec_price` | |
| 卖出份额 | ✅ 借用 `volume` | 成交量 | 与买入份额相等（策略全仓买卖） |
| 买入价 | ✅ `buy_price` | 买入 order `exec_price` | |
| 买入份额 | ✅ 借用 `volume` | 成交量 | 同上 |
| 收盘价（卖出日收盘价） | 未存 | `BarData.close`（卖出日） | 方案 A：反映"开盘卖 vs 收盘卖"择时收益 |
| 佣金（合计） | 未存 | 买入 order.commission + 卖出 order.commission | ETF 无印花税无过户费，仅佣金两项 |
| 净盈 | ⚠️ `profit` 有 bug | `(sell_price-buy_price)*volume - 合计佣金` | 见下方 BUG |
| 收益率% | ✅ `profit_pct` | `(sell_price/buy_price-1)*100` | |
| 持仓天数 | ✅ `holding_days` | `(sell_date - buy_date).days` | |
| 净值（卖出后） | 未存 | `Account.equity_curve` 按 sell_date 查 | 当日 `total_equity` |

### 已发现 BUG

**位置**：`backtest/engine.py:267`

```python
profit = (exec_price - buy_price) * volume - order.commission
```

**问题**：
- 只减了**卖出订单**的 commission
- 漏减了**买入订单**的 commission
- 对 ETF（无印花税、无过户费），买入佣金是唯一遗漏项，导致 profit 偏乐观
- 对个股，还漏了印花税 + 过户费（但 `Account.process_sell` 在账户层面扣了，净值数据正确；仅 `_trades` 里的 profit 字段偏乐观）

**修正方案**：
- 在 `_buy_records` 里补存 `commission`，卖出时读出
- 重写：`profit = (sell_price - buy_price) * volume - buy_commission - sell_commission`
- ETF 只减两笔佣金；个股仍少算 tax/transfer_fee，但这一部分本任务不扩展（后续另行评估）

### 费用模型确认

查 `backtest/fee.py` 和 `config/settings.yaml` 确认：

| 配置项 | 值 | 说明 |
|--------|-----|------|
| `commission_rate` | `0.0001` | 万1 ✓ |
| `min_commission` | `0.0` | 免5（无最低） ✓ |
| `stamp_tax_rate` | `0.001` | 仅个股卖出 |
| `transfer_fee_rate` | `0.00002` | 仅个股 |
| `FeeModel.calculate(is_etf=True)` | ETF 跳过 tax/transfer_fee | `fee.py:57, 62` |
| `Account.process_buy/sell` | 自动识别 ETF | `account.py:82, 147` |

**结论**：费用模型代码无需改动，万1免5 + ETF 免征已全部正确。

### 用户决策（2026-04-19 对话）

1. **字段语言**：中文表头
2. **开/收盘价语义**：方案 A（开盘价 = 买入日 open，收盘价 = 卖出日 close）
3. **佣金展示**：单列"佣金合计"
4. **净值**：只记卖出后净值（1 列）

### 数据流与新增 `_trades` 字段设计

```python
{
    "code": str,
    "buy_date": date,      # 买入日
    "sell_date": date,     # 卖出日
    "buy_open": float,     # 新增：买入日开盘价
    "buy_price": float,    # 买入成交价（= 买入日收盘价，overnight_long 特性）
    "sell_price": float,   # 卖出成交价（= 卖出日开盘价，overnight_long 特性）
    "sell_close": float,   # 新增：卖出日收盘价
    "volume": int,         # 份额
    "commission": float,   # 新增：买入佣金 + 卖出佣金 合计
    "profit": float,       # 修正：已扣两边佣金的净盈
    "profit_pct": float,   # 收益率%（基于 buy_price/sell_price，未扣佣金）
    "holding_days": int,
    "net_equity": float,   # 新增：卖出日 account.total_equity
    "reason": str,         # 卖出原因
}
```

### 控制台列设计（中文，14 列）

```
代码 | 买入日 | 卖出日 | 开盘价 | 买入价 | 收盘价 | 卖出价 | 份额 | 佣金 | 净盈 | 收益率% | 持仓天数 | 净值 | 卖出原因
```

### CSV 列（与控制台一致的中文表头）

通过 `trades_df.rename(columns=...)` 后再 `to_csv(encoding="utf-8-sig")`，保持 Excel 兼容。

### 影响面

| 文件 | 改动类型 | 规模 |
|------|---------|------|
| `backtest/engine.py` | 改 | 约 30 行（扩 _buy_records + 扩 _trades + 修 profit） |
| `scripts/run_backtest.py` | 改 | 约 40 行（重写 _print_trades + CSV 表头映射） |
| `backtest/account.py` | 不改 | — |
| `backtest/fee.py` | 不改 | — |
| `backtest/metrics.py` | 不改 | — |
| 策略文件 | 不改 | 对策略透明 |

### 验收标准

1. 控制台表格新增 3 列（开盘价 / 收盘价 / 佣金 / 净值），中文表头
2. CSV 导出与控制台列一致（中文表头）
3. profit 字段扣两边佣金后，与账户 equity_curve 计算的卖出当日资产变化**对得上**
4. 513090 场景下"印花税" "过户费"恒为 0（不单列，合入 commission=0）
5. `avg_holding_days` 等 metrics 指标不受影响（未改 metrics.py）
