# 示例运行记录（不同决策路径）

每个案例包含 `runs/<run_id>/` 下的三份产物：`result.json`（最终结果）、`trace.jsonl`（逐步决策轨迹）、`state.json`（执行状态快照）；已完成的运行另有 `plan.json`（保存的方案）。

## 两条不同的决策路径（验收点）

- **Mock 策略（case1/case2）**：预算充足时先选 premium（13.0 ≤ 20 直接通过）；预算 10 时先选 premium，估算 13.0 超预算后**降级 standard 重规划**（9.5 ≤ 10）。
- **真实模型 DeepSeek（case6）**：面对预算 10，模型**一开始就直接选 standard**（9.0 ≤ 10），一次通过，无需降级。

同一个任务，两种"大脑"走出了不同的合理路径——这正是 ReAct 循环中模型自主决策的证据。

## 案例列表

| 案例 | 命令要点 | 结果 |
|---|---|---|
| case1_normal_premium | `--budget 20 --deadline-hours 24`（mock） | completed：直接 premium，总花费 13.0 ≤ 20 |
| case2_budget_downgrade | `--budget 10 --deadline-hours 24`（mock） | completed：premium 13.0 超预算 → 降级 standard → 9.5 ≤ 10（题面参考实例） |
| case3_missing_input | 只给 `--budget 15`（mock） | incomplete：`缺少 deadline_hours`，未调用任何付费工具（花费 0） |
| case4_tool_failure_fallback | `--inject-fail search_materials:-1`（mock） | completed：素材检索始终失败 → 重试 2 次后改用 `use_fallback_materials` 兜底 → 完成 |
| case5_infeasible_gap | `--budget 5 --deadline-hours 12`（mock） | incomplete：最低档 standard 也需 9.0 > 5，诚实报告预算缺口 4.0，不保存方案 |
| case6_real_llm | `--model real`（DeepSeek，预算 10） | completed：模型自主选择 standard，4 步完成，总花费 9.0 |

## 复现命令

```bash
# 以 case2 为例（mock 模式，离线可复现）
python -m src.main --theme "秋季新品奶茶上市" --budget 10 --deadline-hours 24 --fresh

# 真实模型模式（需先配置 .env，见 .env.example）
python -m src.main --theme "国庆黄金周出游季" --budget 10 --deadline-hours 24 --model real
```
