# Proposal

## Why

模拟盘和 DryRun 演练遇到全天缺少行情时会返回空摘要。当前报告把空摘要当作零信号，导致双方均跳过的交易日被计入一致天数，掩盖了演练覆盖缺口。

## What Changes

- 每日摘要记录 Paper 和 Live 各自是否完成运行。任一侧跳过时，将该日列为问题日。
- 报告同时展示区间交易日数与双方均完成的可比较天数。一致率以可比较天数为分母，无可比较日时显示“无可比较日”。
- 期末资产按每条执行链各自最近一次成功运行计算。该链在区间内未运行成功时显示“无数据”。

## Capabilities

### New Capabilities

- `live-validation-reporting` — Paper 与 DryRun 演练的日级运行状态、信号比较覆盖和期末资产。

### Modified Capabilities

## Impact

涉及 `trading/live_validation.py` 的摘要与汇总、`scripts/run_live_validation.py` 的控制台呈现、`tests/test_live_validation.py` 的回归测试及 README 的报告口径说明。数据和执行结果仍取自演练中的 PaperEngine 与 DryRunBroker。
