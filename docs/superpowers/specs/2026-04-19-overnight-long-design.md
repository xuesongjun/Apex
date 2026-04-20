# Overnight Long 策略设计

**日期：** 2026-04-19
**作者：** Mahdi（与 Claude 协作）
**状态：** 已定稿并完成实现；2026-04-20 从"模式 A 间隔隔夜"切换为"模式 B 连续隔夜"（见文末变更日志）
**本 spec 范围：** 回测 + 模拟盘接入（B1）
**后续立项：** Phase 7 实盘底座（独立 spec）

> **2026-04-20 重要修订**：原实现每日只生成 SELL **或** BUY 之一（if/elif），导致"买→过夜→卖→休一天→再买"的间隔持仓模式（持仓率 ~50%）。现修正为每日生成 SELL **和** BUY（双独立 if），真正实现"连续隔夜"：每天 9:25 开盘卖 + 14:55 尾盘再买。详见 §10 变更日志。

---

## 1. 目标

实现 A 股隔夜持股策略——每日尾盘买入、次日开盘以集合竞价跌停价挂单卖出（实际成交于开盘价），在仓库现有插件化策略框架下同时接入**回测**与**模拟盘**两条通道，零改动复用现有引擎。

**核心交易规则（用户原始描述）：**

1. T 日 14:55（收盘前 5 分钟）以**卖1价全仓买入**
2. T+1 日 9:20（集合竞价阶段）以**跌停价挂单卖出**

**标的：** 单只跨境 ETF `513090`（恒生互联网科技 ETF 易方达，±15% 涨跌停，免印花税）。标的参数可通过 `--codes` 覆盖，框架上不绑死单一标的。

---

## 2. 关键决策记录

### 2.1 时序近似

| 策略时点 | 引擎映射 | 近似说明 |
|---|---|---|
| T 日 14:55 卖1价买入 | `execute_at="close"`（按 T 日收盘价成交） | 日 K 线缺少 14:55 瞬时价，使用 15:00 收盘价近似；ETF 流动性好，5 分钟价差通常 < 0.2% |
| T+1 日 9:20 挂跌停价卖 | `execute_at="next_open"`（按 T+1 日开盘价成交） | A 股集合竞价为统一清算价撮合，限价 ≤ 开盘价即成交，成交价 = 开盘价（非限价） |

### 2.2 A 股集合竞价撮合机制（澄清）

- 集合竞价**不是连续撮合**，而是 9:25 一次性统一清算。系统找出成交量最大的价格 P，P 即开盘价
- 所有满足限价条件（买单 ≥ P、卖单 ≤ P）的委托**全部按 P 成交**，与挂单限价无关
- "挂跌停价卖"的真实含义是"设极低的卖出门槛以确保被撮合进成交"，成交价由市场集体清算出的开盘价决定
- 例外：**一字跌停**时开盘价 = 跌停价，且卖方远多于买方，可能部分成交或无法成交（由引擎 `_execute_pending_orders` 的"跌停卖出→cancelled"分支处理）

### 2.3 涨跌幅过滤（默认禁用）

| 参数 | 含义 | 默认值 |
|---|---|---|
| `min_drop_pct` | 当日跌幅阈值，正数百分比；`null` = 禁用 | `null` |
| `max_rise_pct` | 当日涨幅上限，正数百分比；`null` = 禁用 | `null` |

两参数均 `null` 时等价于"每日无条件执行"，用户可按需启用。

### 2.4 持仓与边界处理

- **C 项守卫（不追加买）**：空仓才产 BUY 信号，有仓位时跳过买入分支
- **A 项方案（每日挂卖脱困）**：有 `pos.available > 0` 时每日产 SELL 信号，被一字跌停套牢后次日继续尝试
- **T+1 限制**：`pos.available = 0` 时不产 SELL 信号，等待引擎 `new_trading_day()` 解冻
- **涨停买不进 / 跌停卖不出 / 停牌**：引擎 `paper_engine._execute_pending_orders` 已处理，策略零额外代码

### 2.5 实盘接入推迟

- `trading/broker/` 目前为空目录，仓库无实盘底座
- 实盘需要日内定时触发 + 券商 API + 实时行情 + 订单状态机，属 Phase 7 独立立项范畴
- 本 spec 仅覆盖 B1（回测 + 模拟盘）；B1 实现并提交后立即启动实盘底座的独立 brainstorm

---

## 3. 架构定位

**插件化接入，引擎零改动：**

```
┌──────────────────────────────────────────────────────────┐
│  用户命令：                                                │
│    run_backtest.py      --strategy overnight_long ...     │
│    run_paper_trade.py   --strategy overnight_long ...     │
└─────────────────────┬────────────────────────────────────┘
                      │
                      ▼
           ┌───────────────────────┐
           │  strategy/registry.py │  ← 新增 "overnight_long" 条目
           └──────────┬────────────┘
                      │ 反射加载
                      ▼
    ┌──────────────────────────────────────────┐
    │  strategy/technical/overnight_long.py    │  ← 新增文件（本 spec 核心）
    │  class OvernightLongStrategy(BaseStrategy)│
    │    def on_bar(bar) -> list[Signal]        │
    └──────────┬───────────────────────────────┘
               │ 信号输出
               ▼
    ┌──────────────────────────────────────────┐
    │  backtest/engine.py  │  trading/paper_   │   ← 零改动
    │                      │  engine.py        │
    └──────────────────────────────────────────┘
```

---

## 4. 详细设计

### 4.1 策略类 `OvernightLongStrategy`

**文件：** `strategy/technical/overnight_long.py`（新增，约 60–80 行）

```python
"""
隔夜多头策略（尾盘买 / 次日开盘卖）

交易规则：
  - T 日 14:55 以卖1价全仓买入（近似为 T 日收盘价买入）
  - T+1 日 9:20 集合竞价挂跌停价卖（实际成交于 T+1 日开盘价）

边界处理：
  - 空仓才买入（C 项守卫），避免重复加仓
  - 有可卖仓位才挂卖，T+1 冻结期跳过
  - 被一字跌停套牢时，次日 available 解冻后继续挂卖（A 方案）

可选过滤参数（默认禁用）：
  - min_drop_pct: 当日跌幅必须 ≥ 该值才买入（抄反弹）
  - max_rise_pct: 当日涨幅必须 ≤ 该值才买入（避免追高）
"""
from typing import Optional

from strategy.base import BarData, BaseStrategy, Direction, Signal


class OvernightLongStrategy(BaseStrategy):

    @property
    def name(self) -> str:
        return "overnight_long"

    def on_bar(self, bar: BarData) -> list[Signal]:
        signals: list[Signal] = []
        min_drop: Optional[float] = self.config.get("min_drop_pct")
        max_rise: Optional[float] = self.config.get("max_rise_pct")

        # ── 1) 卖出：有可卖仓位 → 次日集合竞价挂跌停价卖（开盘成交） ──
        pos = self.get_position(bar.code)
        if pos and pos.available > 0:
            signals.append(Signal(
                code=bar.code,
                direction=Direction.SELL,
                trade_date=bar.trade_date,
                price=0,
                volume=0,
                reason="次日集合竞价挂跌停价卖（开盘价成交）",
                execute_at="next_open",
            ))

        # ── 2) 买入：空仓 + 通过过滤 → 当日收盘价全仓买（近似 14:55 卖1价） ──
        if not self.has_position(bar.code) and bar.pre_close > 0:
            pct = (bar.close - bar.pre_close) / bar.pre_close * 100
            if min_drop is not None and -pct < min_drop:
                return signals
            if max_rise is not None and pct > max_rise:
                return signals
            signals.append(Signal(
                code=bar.code,
                direction=Direction.BUY,
                trade_date=bar.trade_date,
                price=0,
                volume=0,
                reason="尾盘 14:55 卖1价全仓买入",
                execute_at="close",
            ))

        return signals
```

### 4.2 注册条目（`strategy/registry.py`）

```python
"overnight_long": {
    "class": "strategy.technical.overnight_long.OvernightLongStrategy",
    "description": "隔夜多头（尾盘买 / 次日开盘卖）",
    "default_params": {"min_drop_pct": None, "max_rise_pct": None},
},
```

### 4.3 配置段（`config/strategies.yaml`）

```yaml
strategies:
  overnight_long:
    min_drop_pct: null    # 当日跌幅阈值（正数百分比），null = 禁用
    max_rise_pct: null    # 当日涨幅上限（正数百分比），null = 禁用
```

### 4.4 命令行入口示例

```bash
# 回测：2023 年起 513090 历史表现
python scripts/run_backtest.py --strategy overnight_long --codes 513090 \
    --start 2023-01-01 --capital 500000

# 回测：启用过滤（跌幅 ≥ 3% 才买）
python scripts/run_backtest.py --strategy overnight_long --codes 513090 \
    --start 2023-01-01 --params min_drop_pct=3.0

# 模拟盘：每日收盘后运行一次（16:35 cron）
python scripts/run_paper_trade.py --strategy overnight_long --codes 513090 \
    --capital 1000000

# 查看模拟盘账户状态
python scripts/run_paper_trade.py --strategy overnight_long --codes 513090 --status
```

---

## 5. 文件清单

| 文件 | 改动类型 | 估计行数 |
|---|---|---|
| `strategy/technical/overnight_long.py` | 新增 | ~80 |
| `strategy/registry.py` | 改（新增 1 条注册项） | +6 |
| `config/strategies.yaml` | 改（新增参数段） | +5 |
| `README.md` | 改（策略表 + 运行示例段） | +20 |
| `tests/test_overnight_long.py` | 新增（单元测试） | ~120 |
| `process.txt` | 改（追加变更日志） | +8 |

---

## 6. 测试策略

### 6.1 单元测试 `tests/test_overnight_long.py`

覆盖所有分支，构造 `BarData` 直接喂给策略，**不依赖数据库**：

| 用例 | 前置状态 | 断言 |
|---|---|---|
| 空仓 + 默认参数 | `_positions={}` | 1 个 BUY 信号，`execute_at="close"`，`volume=0` |
| 有仓位且可卖 | `Position(vol=1000, available=1000)` | 1 个 SELL 信号，`execute_at="next_open"` |
| 有仓位但 T+1 未解冻 | `Position(vol=1000, available=0)` | 无 SELL 信号（被套脱困分支守卫） |
| 过滤关闭 + 当日涨 5% | 空仓，两参数 `null` | 产 BUY（过滤未生效） |
| `min_drop_pct=3` + 当日跌 2% | 空仓 | 无 BUY（跌幅不足） |
| `min_drop_pct=3` + 当日跌 5% | 空仓 | 产 BUY |
| `max_rise_pct=3` + 当日涨 5% | 空仓 | 无 BUY（涨幅超限） |
| 连续两日时序 | T 日空仓 → T+1 日模拟已买入 | T 日产 BUY，T+1 日产 SELL 不再产 BUY |

### 6.2 回测集成验证

```bash
python scripts/run_backtest.py --strategy overnight_long --codes 513090 \
    --start 2023-01-01 --capital 500000 --csv /tmp/overnight_long.csv
```

**通过判据：**
- 运行无异常，回测报告含完整 15+ 指标（Sharpe / 最大回撤 / 胜率 / 交易次数等）
- CSV 明细呈现交替 BUY→SELL 配对
- 持仓周期统计 ≈ 1 交易日（真正的"隔夜持仓"）

### 6.3 模拟盘 smoke test

```bash
python scripts/run_paper_trade.py --strategy overnight_long --codes 513090 --capital 1000000
python scripts/run_paper_trade.py --strategy overnight_long --codes 513090 --status
```

**通过判据：**
- `paper_account` / `paper_position` / `paper_order` / `paper_nav` 表均有记录写入
- `--status` 能读出账户余额 / 持仓 / pending 订单

---

## 7. 验收清单

- [ ] 单元测试 8 个用例全部通过（`pytest tests/test_overnight_long.py -v`）
- [ ] 回测脚本在 513090 从 2023-01-01 至今无异常完成，报告完整
- [ ] 模拟盘脚本首次运行与 `--status` 查询均正常
- [ ] `README.md` 策略表新增一行 + 运行示例段新增一节
- [ ] `process.txt` 追加 `[2026-04-19 feat]` 变更日志条目
- [ ] 按 CLAUDE.md 规范 Conventional Commits 英文提交（不含 AI 信息）
- [ ] 提交后立即启动 Phase 7 实盘底座独立 brainstorm

---

## 8. 非目标（YAGNI）

以下内容**不在**本 spec 范围内，避免范围蔓延：

- 实盘接入（Phase 7 独立立项）
- 日内分钟 K 线支持（当前日 K 近似已说明）
- 多标的择时 / 资金分配器（策略设计为单标的，多标的需另立）
- 参数优化 / 过拟合扫描（策略无可调关键参数）
- Web 可视化（Phase 6）

---

## 9. 风险与限制

1. **14:55 时点近似**：日 K 模型无法精确模拟 14:55，用 15:00 收盘价代替；ETF 流动性好影响 < 0.2%，未来实盘需精确处理
2. **一字跌停套牢**：引擎自动取消卖单、次日继续挂卖；极端行情下可能连续多日无法脱困
3. **单标的限制**：策略当前针对单只 513090，多标的场景需调整资金分配逻辑
4. **T+1 规则依赖**：策略假设引擎正确处理 T+1 解冻；`pos.available > 0` 判定是必要守卫

---

## 10. 变更日志

### 2026-04-20 — 模式 A → 模式 B（连续隔夜）

**背景**：用户实测 2026-01-01~2026-01-20 交易明细后发现模式 A 的"间隔持仓"语义不符合真实的"隔夜多头因子"策略意图，期望每日都持仓过夜。

**改动**：
- `on_bar` 的 `if / elif` 改为双独立 `if`，同一根 bar 可返回 `[SELL @ next_open, BUY @ close]` 两个信号
- 新增 `limit_pct`（默认 0.10）参数，用于一字跌停判定：`bar.open <= pre_close × (1 - limit_pct) + 1e-6` 视为挂卖失败
- 一字跌停被套时 SELL 与 BUY 同时阻塞（资金被持仓占用），当日零交易
- 涨跌幅过滤 `min_drop_pct` / `max_rise_pct` 语义收窄为"仅作用于 BUY 分支"（进场条件），SELL 不受影响
- 单测从 8 → 11，修正 4 个断言 + 新增 3 个（一字跌停阻塞 / 被套次日恢复 / limit_pct 参数）

**回归验证**：
- 11 个单测全绿
- 513090 2026-01-01~2026-04-07 回测买卖日期连续（`row[N].sell_date == row[N+1].buy_date`）
- 交易数较模式 A 约翻倍（~393 → ~780 笔）

**语义修订**：`§1` 的交易规则 2 从"次日开盘卖完即结束"修订为"次日开盘卖完 + 当日尾盘再次满仓买"。`§9` 的风险 2（一字跌停套牢）新增"一字跌停当日 BUY 也跳过"说明。
