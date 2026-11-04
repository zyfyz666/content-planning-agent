# 04 · 状态持久化与重复执行

## 目录结构

每次运行的所有状态写入 `runs/<run_id>/`：

| 文件 | 内容 | 写入时机 |
|---|---|---|
| `state.json` | 输入、已完成步骤结果、花费、失败计数、骨架进度 | 每步执行后 |
| `trace.jsonl` | 逐步决策轨迹（thought / decision_basis / ok / 实扣费） | 每步追加 |
| `result.json` | 最终结果（含 task_plan / cost / notes） | 运行结束时 |
| `plan.json` | 保存的活动方案（仅成功时） | save_plan 成功时 |

## run_id 派生与幂等

- `run_id = "run-" + sha1([theme, budget, deadline_hours])[:8]`，相同输入 → 相同 run_id。
- **重复执行已完成任务**：直接复用已有 `result.json`，在 notes 中注明"未重复执行工具、未重复扣费"（examples 之外的验证：连续运行两次同命令，第二次 `steps_used` 与 `cost` 完全不变）。
- **失败续跑（加分项）**：若上次运行未完成，相同输入再次执行时自动从 `state.json` 恢复——已成功的步骤（含已扣的费用）不重复执行，从断点继续。续跑会清空本会话内的失败计数，给模型新的重试机会。

## 恢复语义

| 上次状态 | 再次执行的行为 |
|---|---|
| completed | 复用 result.json，不执行任何工具 |
| incomplete（如脚本生成 2 连败中断） | 保留素材结果与花费，从脚本步骤继续，直至完成 |
| 步数耗尽中断 | 同上，从中断点续跑 |

`--fresh` 可丢弃全部历史状态强制重跑；`--run-id` 可显式指定运行 ID。
