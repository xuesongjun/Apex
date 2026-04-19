# Overnight Long Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `overnight_long` 策略（T 日 14:55 近似收盘价全仓买入、T+1 日 9:20 集合竞价挂跌停价卖出），同时接入回测与模拟盘，spec + 代码 + 测试一次性提交。

**Architecture:** 插件化策略——继承 `BaseStrategy`，通过 `strategy/registry.py` 注册。信号用 `execute_at="close"`（当日收盘价买）+ `execute_at="next_open"`（次日开盘价卖）声明时序意图，`backtest/engine.py` 和 `trading/paper_engine.py` 两个引擎零改动复用。

**Tech Stack:** Python 3.11+、pytest 8、SQLAlchemy 2.0（复用现有）、loguru、pandas/numpy。

**Spec 来源：** `docs/superpowers/specs/2026-04-19-overnight-long-design.md`

---

## File Structure

| 文件 | 责任 | 改动类型 |
|---|---|---|
| `strategy/technical/overnight_long.py` | 策略主体：`OvernightLongStrategy.on_bar()` 产信号 | 新增 |
| `strategy/registry.py` | 注册表加 1 条 `overnight_long` 记录 | 改（+6 行） |
| `config/strategies.yaml` | 新策略默认参数段 | 改（+5 行） |
| `tests/__init__.py` | pytest 测试包标记 | 新增（空文件） |
| `tests/test_overnight_long.py` | 策略单元测试，8 个用例 | 新增 |
| `README.md` | 策略表 + 运行示例 | 改（+20 行） |
| `process.txt` | 首次创建变更日志（CLAUDE.md 规定） | 新增 |
| `docs/superpowers/specs/2026-04-19-overnight-long-design.md` | 设计 spec（已存在） | 已存在，本次 commit 一并进 |
| `docs/superpowers/plans/2026-04-19-overnight-long.md` | 本 plan 文件（已存在） | 已存在，本次 commit 一并进 |

**测试目录不存在，Task 0 中首次创建。`process.txt` 不存在，Task 13 中首次创建。**

---

## Task 0: 项目脚手架

**Files:**
- Create: `tests/__init__.py`（空文件）
- Create: `strategy/technical/overnight_long.py`（初始骨架）

### Steps

- [ ] **Step 0.1: 创建 tests 目录与包标记**

```bash
mkdir -p /home/mahdi/workspace/Apex/tests
touch /home/mahdi/workspace/Apex/tests/__init__.py
```

- [ ] **Step 0.2: 验证 pytest 可识别 tests 目录**

```bash
cd /home/mahdi/workspace/Apex && python -m pytest tests/ --collect-only 2>&1 | head -5
```

Expected: `no tests ran` 或 `collected 0 items`（不报错即可）

- [ ] **Step 0.3: 创建策略文件骨架**

写入 `strategy/technical/overnight_long.py`：

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
        return []
```

- [ ] **Step 0.4: 验证骨架能被 Python import**

```bash
cd /home/mahdi/workspace/Apex && python -c "from strategy.technical.overnight_long import OvernightLongStrategy; s = OvernightLongStrategy(); print(s.name)"
```

Expected: `overnight_long`

---

## Task 1: 单元测试 — 空仓时产生 BUY 信号（TDD 循环 1）

**Files:**
- Create: `tests/test_overnight_long.py`
- Modify: `strategy/technical/overnight_long.py` 增加买入分支

### Steps

- [ ] **Step 1.1: 写第一个失败测试（空仓产 BUY）**

写入 `tests/test_overnight_long.py`（新文件，完整内容）：

```python
"""
overnight_long 策略单元测试

覆盖所有信号分支，构造 BarData 直接喂给策略，不依赖数据库/引擎。
"""
from datetime import date

import pytest

from strategy.base import BarData, Direction, Position
from strategy.technical.overnight_long import OvernightLongStrategy


def make_bar(code="513090", trade_date=None, close=1.0, pre_close=1.0):
    """构造一根 BarData 便于测试"""
    td = trade_date or date(2026, 1, 5)
    return BarData(
        code=code,
        trade_date=td,
        open=pre_close,
        high=max(pre_close, close),
        low=min(pre_close, close),
        close=close,
        pre_close=pre_close,
        volume=1_000_000,
        amount=close * 1_000_000,
    )


def test_empty_position_generates_buy_signal():
    """空仓 + 默认参数 → 产生 1 个 BUY 信号，execute_at='close'，volume=0 由引擎解析"""
    strategy = OvernightLongStrategy()
    bar = make_bar(close=1.80, pre_close=1.82)

    signals = strategy.on_bar(bar)

    assert len(signals) == 1
    s = signals[0]
    assert s.direction == Direction.BUY
    assert s.code == "513090"
    assert s.execute_at == "close"
    assert s.volume == 0
    assert s.price == 0
```

- [ ] **Step 1.2: 运行测试确认失败**

```bash
cd /home/mahdi/workspace/Apex && python -m pytest tests/test_overnight_long.py::test_empty_position_generates_buy_signal -v
```

Expected: FAIL（on_bar 返回空列表，assertion `len(signals) == 1` 失败）

- [ ] **Step 1.3: 实现买入分支**

将 `strategy/technical/overnight_long.py` 中 `on_bar` 替换为：

```python
    def on_bar(self, bar: BarData) -> list[Signal]:
        signals: list[Signal] = []
        min_drop: Optional[float] = self.config.get("min_drop_pct")
        max_rise: Optional[float] = self.config.get("max_rise_pct")

        # 2) 买入：空仓 + 通过过滤 → 当日收盘价全仓买（近似 14:55 卖1价）
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

- [ ] **Step 1.4: 运行测试确认通过**

```bash
cd /home/mahdi/workspace/Apex && python -m pytest tests/test_overnight_long.py::test_empty_position_generates_buy_signal -v
```

Expected: PASS

---

## Task 2: 单元测试 — 有仓位产生 SELL 信号（TDD 循环 2）

**Files:**
- Modify: `tests/test_overnight_long.py` 追加测试
- Modify: `strategy/technical/overnight_long.py` 增加卖出分支

### Steps

- [ ] **Step 2.1: 追加 SELL 测试**

在 `tests/test_overnight_long.py` 末尾追加：

```python
def test_held_position_generates_sell_signal():
    """有可卖仓位 → 产生 1 个 SELL 信号，execute_at='next_open'"""
    strategy = OvernightLongStrategy()
    pos = Position(
        code="513090",
        volume=10000,
        available=10000,
        cost_price=1.80,
        current_price=1.80,
        buy_date=date(2026, 1, 4),
    )
    strategy._sync_account(positions={"513090": pos}, cash=0.0, total_value=18000.0)

    bar = make_bar(close=1.85, pre_close=1.80)
    signals = strategy.on_bar(bar)

    assert len(signals) == 1
    s = signals[0]
    assert s.direction == Direction.SELL
    assert s.execute_at == "next_open"
    assert s.volume == 0    # 0 = 全部可卖持仓，引擎解析
```

- [ ] **Step 2.2: 运行测试确认失败**

```bash
cd /home/mahdi/workspace/Apex && python -m pytest tests/test_overnight_long.py::test_held_position_generates_sell_signal -v
```

Expected: FAIL（当前实现没有 SELL 分支，`len(signals) == 0`）

- [ ] **Step 2.3: 在 on_bar 开头添加 SELL 分支**

在 `strategy/technical/overnight_long.py` 的 `on_bar` 方法中，在"# 2) 买入"分支**之前**插入：

```python
        # 1) 卖出：有可卖仓位 → 次日集合竞价挂跌停价卖（开盘成交）
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

```

- [ ] **Step 2.4: 运行所有测试确认全部通过**

```bash
cd /home/mahdi/workspace/Apex && python -m pytest tests/test_overnight_long.py -v
```

Expected: 2 passed

---

## Task 3: 单元测试 — T+1 未解冻不产 SELL（TDD 循环 3）

**Files:**
- Modify: `tests/test_overnight_long.py` 追加测试

**说明：** 当前 SELL 分支判定 `pos.available > 0`，`available=0` 天然走 False 分支。此测试验证该守卫确实生效，无需改代码。

### Steps

- [ ] **Step 3.1: 追加 T+1 冻结测试**

在 `tests/test_overnight_long.py` 末尾追加：

```python
def test_position_with_zero_available_skips_sell():
    """T+1 未解冻（available=0）→ 不产 SELL 信号，也不产 BUY（因为 has_position=True）"""
    strategy = OvernightLongStrategy()
    pos = Position(
        code="513090",
        volume=10000,
        available=0,    # 今日刚买入，T+1 未解冻
        cost_price=1.80,
        current_price=1.80,
        buy_date=date(2026, 1, 5),
    )
    strategy._sync_account(positions={"513090": pos}, cash=0.0, total_value=18000.0)

    bar = make_bar(close=1.85, pre_close=1.80)
    signals = strategy.on_bar(bar)

    assert len(signals) == 0
```

- [ ] **Step 3.2: 运行测试确认通过**

```bash
cd /home/mahdi/workspace/Apex && python -m pytest tests/test_overnight_long.py::test_position_with_zero_available_skips_sell -v
```

Expected: PASS（`pos.available > 0` 已是现有守卫，无需改代码）

---

## Task 4: 单元测试 — 过滤关闭时大涨日仍买入（TDD 循环 4）

**Files:**
- Modify: `tests/test_overnight_long.py` 追加测试

### Steps

- [ ] **Step 4.1: 追加过滤关闭测试**

在 `tests/test_overnight_long.py` 末尾追加：

```python
def test_filters_disabled_by_default_even_on_big_rise():
    """默认两参数 None → 当日涨 5% 也产 BUY（过滤未生效）"""
    strategy = OvernightLongStrategy()
    bar = make_bar(close=1.05, pre_close=1.00)  # 涨 5%
    signals = strategy.on_bar(bar)

    assert len(signals) == 1
    assert signals[0].direction == Direction.BUY
```

- [ ] **Step 4.2: 运行测试确认通过**

```bash
cd /home/mahdi/workspace/Apex && python -m pytest tests/test_overnight_long.py::test_filters_disabled_by_default_even_on_big_rise -v
```

Expected: PASS

---

## Task 5: 单元测试 — `min_drop_pct` 过滤（TDD 循环 5，2 个用例）

**Files:**
- Modify: `tests/test_overnight_long.py` 追加测试

### Steps

- [ ] **Step 5.1: 追加跌幅不足 / 跌幅足够两个测试**

在 `tests/test_overnight_long.py` 末尾追加：

```python
def test_min_drop_pct_blocks_when_drop_insufficient():
    """min_drop_pct=3 + 当日跌 2% → 不产 BUY（跌幅不足）"""
    strategy = OvernightLongStrategy(config={"min_drop_pct": 3.0})
    bar = make_bar(close=0.98, pre_close=1.00)   # 跌 2%
    signals = strategy.on_bar(bar)
    assert len(signals) == 0


def test_min_drop_pct_allows_when_drop_sufficient():
    """min_drop_pct=3 + 当日跌 5% → 产 BUY（跌幅达标）"""
    strategy = OvernightLongStrategy(config={"min_drop_pct": 3.0})
    bar = make_bar(close=0.95, pre_close=1.00)   # 跌 5%
    signals = strategy.on_bar(bar)
    assert len(signals) == 1
    assert signals[0].direction == Direction.BUY
```

- [ ] **Step 5.2: 运行两个测试确认通过**

```bash
cd /home/mahdi/workspace/Apex && python -m pytest tests/test_overnight_long.py::test_min_drop_pct_blocks_when_drop_insufficient tests/test_overnight_long.py::test_min_drop_pct_allows_when_drop_sufficient -v
```

Expected: 2 passed

---

## Task 6: 单元测试 — `max_rise_pct` 过滤（TDD 循环 6）

**Files:**
- Modify: `tests/test_overnight_long.py` 追加测试

### Steps

- [ ] **Step 6.1: 追加涨幅超限测试**

在 `tests/test_overnight_long.py` 末尾追加：

```python
def test_max_rise_pct_blocks_when_rise_exceeds():
    """max_rise_pct=3 + 当日涨 5% → 不产 BUY（涨幅超限）"""
    strategy = OvernightLongStrategy(config={"max_rise_pct": 3.0})
    bar = make_bar(close=1.05, pre_close=1.00)   # 涨 5%
    signals = strategy.on_bar(bar)
    assert len(signals) == 0
```

- [ ] **Step 6.2: 运行测试确认通过**

```bash
cd /home/mahdi/workspace/Apex && python -m pytest tests/test_overnight_long.py::test_max_rise_pct_blocks_when_rise_exceeds -v
```

Expected: PASS

---

## Task 7: 单元测试 — 连续两日时序（TDD 循环 7）

**Files:**
- Modify: `tests/test_overnight_long.py` 追加测试

### Steps

- [ ] **Step 7.1: 追加连续两日时序测试**

在 `tests/test_overnight_long.py` 末尾追加：

```python
def test_two_day_cycle_buy_then_sell_no_rebuy():
    """
    T 日空仓 → 产 BUY
    T+1 日持仓（模拟已买入、T+1 已解冻）→ 产 SELL 且不再产 BUY（C 项守卫）
    """
    strategy = OvernightLongStrategy()

    # T 日：空仓
    bar_t = make_bar(trade_date=date(2026, 1, 5), close=1.80, pre_close=1.82)
    signals_t = strategy.on_bar(bar_t)
    assert len(signals_t) == 1
    assert signals_t[0].direction == Direction.BUY

    # T+1 日：模拟持仓已买入并解冻
    pos = Position(
        code="513090",
        volume=10000,
        available=10000,
        cost_price=1.80,
        current_price=1.80,
        buy_date=date(2026, 1, 5),
    )
    strategy._sync_account(positions={"513090": pos}, cash=0.0, total_value=18000.0)

    bar_t1 = make_bar(trade_date=date(2026, 1, 6), close=1.85, pre_close=1.80)
    signals_t1 = strategy.on_bar(bar_t1)

    assert len(signals_t1) == 1
    assert signals_t1[0].direction == Direction.SELL
    assert signals_t1[0].execute_at == "next_open"
```

- [ ] **Step 7.2: 运行全部 8 个测试确认通过**

```bash
cd /home/mahdi/workspace/Apex && python -m pytest tests/test_overnight_long.py -v
```

Expected: 8 passed

---

## Task 8: 注册到策略表

**Files:**
- Modify: `strategy/registry.py:15-31` 的 `STRATEGY_REGISTRY` 字典

### Steps

- [ ] **Step 8.1: 在 `limitdown_short` 之后添加注册项**

编辑 `strategy/registry.py`，将：

```python
    "limitdown_short": {
        "class": "strategy.technical.limitdown_short.LimitDownShortStrategy",
        "description": "跌停做空策略（集合竞价卖出 + 收盘买入）",
        "default_params": {},
    },
}
```

替换为：

```python
    "limitdown_short": {
        "class": "strategy.technical.limitdown_short.LimitDownShortStrategy",
        "description": "跌停做空策略（集合竞价卖出 + 收盘买入）",
        "default_params": {},
    },
    "overnight_long": {
        "class": "strategy.technical.overnight_long.OvernightLongStrategy",
        "description": "隔夜多头（尾盘买 / 次日开盘卖）",
        "default_params": {"min_drop_pct": None, "max_rise_pct": None},
    },
}
```

- [ ] **Step 8.2: 验证注册成功**

```bash
cd /home/mahdi/workspace/Apex && python -c "from strategy.registry import load_strategy; s = load_strategy('overnight_long'); print(s.name, s.config)"
```

Expected: `overnight_long {'min_drop_pct': None, 'max_rise_pct': None}`

---

## Task 9: 配置文件更新

**Files:**
- Modify: `config/strategies.yaml`（在现有策略段之后追加）

### Steps

- [ ] **Step 9.1: 在 `rsi` 段之后追加 `overnight_long` 默认配置**

编辑 `config/strategies.yaml`，在 `oversold: 30` 行（line 38）之后、`# 股票池配置` 行（line 40）之前，插入：

```yaml

  # 隔夜多头策略（尾盘买 / 次日开盘卖）
  overnight_long:
    enabled: true
    min_drop_pct: null    # 当日跌幅阈值（正数百分比），null = 禁用
    max_rise_pct: null    # 当日涨幅上限（正数百分比），null = 禁用
```

- [ ] **Step 9.2: 验证 YAML 语法正确**

```bash
cd /home/mahdi/workspace/Apex && python -c "import yaml; d = yaml.safe_load(open('config/strategies.yaml')); print(d['strategies']['overnight_long'])"
```

Expected: `{'enabled': True, 'min_drop_pct': None, 'max_rise_pct': None}`

---

## Task 10: 回测集成验证（需 513090 本地数据）

**Files:** 无代码改动；本 Task 只是手动运行验证。

**前置条件：** 513090 历史数据已入库。若未入库，先运行 `python scripts/init_db.py --codes 513090 --start 2023-01-01`。

### Steps

- [ ] **Step 10.1: 检查 513090 数据是否可用**

```bash
cd /home/mahdi/workspace/Apex && python scripts/query_stock.py -c 513090 -s 2023-01-03 -e 2023-01-10
```

Expected: 列出 2023-01-03 起的若干条日 K 线。如为空，先运行 `python scripts/init_db.py --codes 513090 --start 2023-01-01` 补数据后再试。

- [ ] **Step 10.2: 运行 overnight_long 回测**

```bash
cd /home/mahdi/workspace/Apex && python scripts/run_backtest.py --strategy overnight_long --codes 513090 --start 2023-01-01 --capital 500000 --csv /tmp/overnight_long.csv
```

Expected:
- 无 Python 异常
- 打印回测报告含：初始资金 / 期末资金 / 总收益率 / Sharpe / 最大回撤 / 胜率 / 交易次数 / 盈利天数 等 15+ 指标
- `/tmp/overnight_long.csv` 被生成

- [ ] **Step 10.3: 抽查 CSV 明细**

```bash
head -20 /tmp/overnight_long.csv
```

Expected: 看到交替的 BUY 和 SELL 记录，每笔 BUY 后紧跟一笔 SELL（次日），持仓周期 ≈ 1 交易日。

---

## Task 11: 模拟盘 smoke test

**Files:** 无代码改动

### Steps

- [ ] **Step 11.1: 先更新行情数据确保当日可用**

```bash
cd /home/mahdi/workspace/Apex && python scripts/daily_update.py --codes 513090
```

Expected: 无异常，日志显示增量更新完成。

- [ ] **Step 11.2: 首次运行模拟盘（创建账户）**

```bash
cd /home/mahdi/workspace/Apex && python scripts/run_paper_trade.py --strategy overnight_long --codes 513090 --capital 1000000
```

Expected:
- 日志显示 "账户已加载：overnight_long" 和 "运行完成"
- 若当日非交易日或已跑过会显示 "跳过"，此为正常守卫
- 无未捕获异常

- [ ] **Step 11.3: 查询账户状态**

```bash
cd /home/mahdi/workspace/Apex && python scripts/run_paper_trade.py --strategy overnight_long --codes 513090 --status
```

Expected: 打印账户现金 / 持仓 / pending 订单 / 净值等状态。若当日触发买入则看到 513090 持仓。

---

## Task 12: 文档更新 — README

**Files:**
- Modify: `README.md`（3 处）

### Steps

- [ ] **Step 12.1: 在"可用策略"表追加一行**

编辑 `README.md`，找到策略表（约 line 354-360）：

```markdown
| `ma_cross` | 均线交叉 | 趋势跟踪，短均线金叉/死叉长均线，次日开盘执行 |
| `macd` | MACD | 趋势动量，DIF/DEA 金叉死叉，次日开盘执行 |
| `limitdown_short` | 跌停做空 | 每日开盘卖出（集合竞价）+ 收盘买入，当日执行 |
```

在 `limitdown_short` 行后追加：

```markdown
| `overnight_long` | 隔夜多头 | 尾盘买入（14:55 近似收盘价）+ 次日集合竞价挂跌停价卖出（开盘成交） |
```

- [ ] **Step 12.2: 在"策略回测"段落追加运行示例**

编辑 `README.md`，在"### 3. 策略回测"段末尾（约 line 125 之后、"### 4. 开盘做空策略回测"之前）追加：

````markdown

```bash
# 隔夜多头策略（尾盘买 / 次日集合竞价卖）
python scripts/run_backtest.py --strategy overnight_long --codes 513090 --start 2023-01-01 --capital 500000

# 启用涨跌幅过滤（跌幅 ≥ 3% 才买）
python scripts/run_backtest.py --strategy overnight_long --codes 513090 --start 2023-01-01 --params min_drop_pct=3.0
```
````

- [ ] **Step 12.3: 在"模拟盘交易"段追加 overnight_long 示例**

编辑 `README.md`，在 "跌停做空策略" 模拟盘示例行（约 line 314）之后追加：

```markdown

# 隔夜多头策略（尾盘买 / 次日开盘卖）
python scripts/run_paper_trade.py --strategy overnight_long --codes 513090 --capital 1000000
```

---

## Task 13: 文档更新 — process.txt（首次创建）

**Files:**
- Create: `process.txt`（CLAUDE.md 规定的变更日志，本次首次创建）

### Steps

- [ ] **Step 13.1: 创建 process.txt**

写入 `/home/mahdi/workspace/Apex/process.txt`：

```
[2026-04-19 feat] 新增 overnight_long 隔夜多头策略
- 改动文件：strategy/technical/overnight_long.py (新增), strategy/registry.py, config/strategies.yaml, README.md, tests/__init__.py (新增), tests/test_overnight_long.py (新增), docs/superpowers/specs/2026-04-19-overnight-long-design.md (新增), docs/superpowers/plans/2026-04-19-overnight-long.md (新增), process.txt (新增)
- 改动说明：实现"T 日 14:55 近似收盘价全仓买入 + T+1 日 9:20 集合竞价挂跌停价卖出"的隔夜持股策略，主要针对 513090 恒生互联网科技 ETF。插件化接入回测与模拟盘双通道，零引擎改动。可选涨跌幅过滤参数默认禁用。单元测试 8 个用例覆盖所有信号分支。本次为 B1 阶段（回测+模拟盘），Phase 7 实盘底座将于下一阶段独立立项。
```

---

## Task 14: 最终验证 + 一次性提交

**Files:** 全部

### Steps

- [ ] **Step 14.1: 跑完整单元测试套**

```bash
cd /home/mahdi/workspace/Apex && python -m pytest tests/ -v
```

Expected: 8 passed, 0 failed

- [ ] **Step 14.2: 查看将要提交的文件清单**

```bash
cd /home/mahdi/workspace/Apex && git status
```

Expected: 看到以下新增/修改文件：
- new file: docs/superpowers/specs/2026-04-19-overnight-long-design.md
- new file: docs/superpowers/plans/2026-04-19-overnight-long.md
- new file: strategy/technical/overnight_long.py
- new file: tests/__init__.py
- new file: tests/test_overnight_long.py
- new file: process.txt
- modified: strategy/registry.py
- modified: config/strategies.yaml
- modified: README.md

**注意：** `trades.csv` 是本地产物，不提交。

- [ ] **Step 14.3: 添加目标文件并查看待提交摘要**

```bash
cd /home/mahdi/workspace/Apex && git add \
    strategy/technical/overnight_long.py \
    strategy/registry.py \
    config/strategies.yaml \
    tests/__init__.py \
    tests/test_overnight_long.py \
    README.md \
    process.txt \
    docs/superpowers/specs/2026-04-19-overnight-long-design.md \
    docs/superpowers/plans/2026-04-19-overnight-long.md
git status
```

Expected: 所有上述文件显示在 "Changes to be committed"。

- [ ] **Step 14.4: 创建 commit（CLAUDE.md 规范：英文、Conventional Commits、不含 AI 信息）**

```bash
cd /home/mahdi/workspace/Apex && git commit -m "$(cat <<'EOF'
feat: add overnight_long strategy (close-buy / next-open-sell)

Implements a T-day-close-buy / T+1-open-sell overnight-hold strategy,
targeting 513090 (HSTECH ETF). Plugs into both backtest and paper-trading
via strategy/registry.py with zero engine changes. Optional drop/rise
filters are provided but disabled by default. Includes 8 unit tests
covering all signal branches (empty/held/frozen position, filter on/off,
two-day cycle). Ships with spec + plan under docs/superpowers/.
EOF
)"
```

Expected: commit 成功，输出包含 "[main <hash>] feat: add overnight_long strategy..."

- [ ] **Step 14.5: 验证 commit**

```bash
cd /home/mahdi/workspace/Apex && git log -1 --stat
```

Expected: 看到 9 个文件被提交。

---

## 非目标（YAGNI 复提醒）

- **实盘接入**：Phase 7 独立立项，不在本 plan 范围
- **日内分钟 K 支持**：当前用日 K close 近似 14:55，精确化留给 Phase 7
- **多标的资金分配器**：单标的设计，多标的需另立
- **参数网格搜索**：策略无可调关键参数，无过拟合风险

## 风险提醒

1. **14:55 vs 15:00 时点近似**：回测/模拟盘结果的 5 分钟价差误差通常 < 0.2%，但统计意义上会放大到累计收益上，属已知误差
2. **一字跌停持续套牢**：引擎每日尝试挂卖、次日继续，极端行情可能连续多日无法出货
3. **T+1 守卫依赖 available**：引擎 `new_trading_day()` 必须正确解冻，若该链路有 bug，策略将永久锁仓（由 `pos.available > 0` 判定兜底，但不是根治方案）

---

## Plan 自审（按 writing-plans skill 要求）

**1. Spec 覆盖检查：**

| Spec 章节 | 对应 Task |
|---|---|
| §2.1 时序近似（close/next_open） | Task 1, 2 |
| §2.2 集合竞价机制澄清 | Task 2（reason 字段注明） |
| §2.3 涨跌幅过滤默认禁用 | Task 4, 5, 6, 9 |
| §2.4 C 项守卫（不追加买） | Task 7 |
| §2.4 A 项方案（每日挂卖脱困） | Task 2（pos.available>0 判定） |
| §2.4 T+1 未解冻不卖 | Task 3 |
| §2.4 涨跌停/停牌由引擎处理 | Task 10, 11 手动验证 |
| §2.5 实盘推迟 | 本 plan 不含，任务 #8 follow-up |
| §3 架构（插件化注册） | Task 8 |
| §4.3 配置 yaml | Task 9 |
| §4.4 命令行入口 | Task 10, 11, 12 |
| §5 文件清单 | 全部 14 个 Task |
| §6.1 单元测试 8 用例 | Task 1–7（已覆盖 8 个） |
| §6.2 回测集成 | Task 10 |
| §6.3 模拟盘 smoke test | Task 11 |
| §7 验收清单 | Task 14.1, 14.4 |

无缺口。

**2. Placeholder 扫描：** 无 TBD / TODO / "handle edge cases" 等模糊用语；每处代码块均完整可粘贴。

**3. 类型/命名一致性：** `min_drop_pct` / `max_rise_pct` / `OvernightLongStrategy.name = "overnight_long"` 在所有任务中一致。`execute_at="close"` 与 `"next_open"` 映射一致。
