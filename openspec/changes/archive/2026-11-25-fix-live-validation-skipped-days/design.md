# Design

## Context

参见 [提案](proposal.md)。`PaperEngine.run_daily()` 和 `LiveEngine.run_daily()` 都用空字典表示跳过，正常完成的摘要包含 `signals_generated`。该字段可以为零。仓库内报告摘要仅供演练 CLI 和相关测试读取。

## Goals / Non-Goals

- 在演练汇总层保留两侧的运行状态，并据此计算覆盖率和期末资产。
- 变更范围限于演练报告、CLI 呈现、回归测试和对应的 README 说明。

## Decisions

1. 在 `summarize_validation_day()` 规范化输入前记录 `paper_ran` 与 `live_ran`。空字典和 `None` 表示跳过，正常摘要表示当日完成。任一侧跳过时将 `signal_match` 记为 `None`，控制台给该侧信号数显示占位符。现有计数键供报告继续汇总。由演练层解释已有返回值，可以让生产执行引擎继续提供相同的摘要契约。
2. 在 `summarize_validation_report()` 保留 `trade_days`，新增 `comparable_days`。近尾部跳过可能只发生在一侧，因此分别取两侧最近完成日的资产。返回 `None` 表示区间内该侧无数据，由控制台显示为“无数据”。
3. 让 `print_report()` 在问题日呈现两侧的运行状态。CLI 参数和退出码维持现有行为，调用方可以通过报告查看未执行日期。

## Risks / Trade-offs

- 空摘要涵盖多种跳过原因。报告只使用执行链实际返回的状态，具体原因仍可从执行日志定位。
- 本次识别的是整条执行链返回空摘要的日期。单个标的的行情覆盖需要标的级数据，属于另一项变更。
