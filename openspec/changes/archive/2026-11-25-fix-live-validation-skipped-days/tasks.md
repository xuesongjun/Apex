# Tasks

## 1. 演练汇总

- [x] 1.1 在 `trading/live_validation.py` 记录各侧执行状态并更新一致率及期末资产计算。在 `tests/test_live_validation.py` 验证双侧跳过、单侧跳过、双侧正常零信号、既有错配与拒单计数，以及各侧期末资产取值。

## 2. 控制台报告

- [x] 2.1 在 `scripts/run_live_validation.py` 展示跳过侧、可比较天数和缺失资产，在 `tests/test_live_validation.py` 验证报告输出，并在 `README.md` 记录一致率和期末资产口径。

## 3. 集成验证

- [x] 3.1 使用临时 SQLite 构造包含完整行情和整日缺行情的交易区间，运行演练入口并验证缺行情日期在问题列表中。运行相关 pytest 测试及 OpenSpec 严格校验。

## Workflow follow-up

- 实现和验收完成后，在 OpenSpec 中归档变更并核对主规格。
