# 示例运行记录（输入 / 实际输出 / Trace）

每个案例目录：`input.json`（输入与复现命令）、`runs/<run_id>/`（`result.json` 实际输出、`trace.jsonl` 逐步决策轨迹、`state.json` 执行状态；成功案例含 `plan.json`）。case7/case8 另存 `result_run1.json` / `result_run2.json` 用于对比两次运行。

## 验收点对照

| 案例 | 场景 | 覆盖验收点 | 关键证据 |
|---|---|---|---|
| case1_normal_premium | 预算 20，直接 premium 完成 | 正常完成 | `result.json: status=completed, tier=premium, total=13.0` |
| case2_budget_downgrade | 预算 10：premium 13 超限 → 降级 standard 9.5（题面参考实例） | 预算超限重规划 | script/estimate 各 2 次调用；trace 中含降级决策依据 |
| case3_missing_input | 缺 deadline_hours | 信息不足不执行 | `steps_used=0, tool_fees=0`，原因注明缺少字段 |
| case4_tool_failure_fallback | 检索始终失败 → 重试 2 次 → 兜底素材 | 工具失败处理 | `materials_source=fallback`，仍 completed |
| case5_infeasible_gap | 预算 5 < 最低档 9.0 | 不可行明确报告 | 缺口 4.0，不保存方案 |
| case6_real_llm | **真实模型 DeepSeek**：直接选 standard | 真实模型决策 + 第二条决策路径 | 4 步完成，总 9.0/10 |
| case7_repeat_run | 同输入连续运行两次 | 重复执行幂等 | run2 `steps_used` 不变，notes 注明"未重复扣费" |
| case8_resume | 脚本 2 连败中断 → 同输入再跑自动续跑 | 失败续跑（加分项） | run1 incomplete → run2 completed，素材未重复扣费 |

## 两条不同决策路径（考核要求）

- **Mock 策略**（case1/case2）：预算充足先选 premium；预算 10 时 premium 估算 13 超限，模型降级 standard 重生成并重估，最终 9.5 ≤ 10 保存。
- **真实模型**（case6）：DeepSeek 看到预算 10 直接选 standard，4 步一次通过。
- 两条路径均由"模型根据观察自主决策"产生（trace 每步含 thought 与 decision_basis 字段）。

## 复现

```bash
python -m pytest tests -q          # 16 个用例
python -m src.main --theme "秋季新品奶茶上市" --budget 10 --deadline-hours 24   # case2 复现
```
