# 研究笔记

本文件记录每次迭代的研究结论与关键发现，按时间倒序追加。

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
