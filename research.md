# 研究笔记

本文件记录每次迭代的研究结论与关键发现，按时间倒序追加。

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
