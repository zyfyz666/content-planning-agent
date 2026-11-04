# 03 · 评估（测试预期、实际结果、失败与限制）

## 测试矩阵与实际结果

运行方式：`python -m pytest tests -q` → **16 passed**（0.1s，离线，无需 API Key）。

| 测试文件 | 场景 | 预期 → 实际 |
|---|---|---|
| test_normal_flow.py | 预算 20 直接 premium 完成；预算 10 触发降级重规划（参考实例） | 2/2 通过 |
| test_missing_inputs.py | 缺 theme/budget/deadline：不调用任何工具、花费 0 | 4/4 通过 |
| test_tool_failure.py | 失败重试 / 兜底素材 / 全部素材途径失败停止 / 脚本 2 连败停止 | 4/4 通过 |
| test_budget_overrun.py | 预算超限降级（13→9.5）；预算 5 无可行方案缺口 4.0；工期缺口 3.4h 诚实报告 | 3/3 通过 |
| test_repeat_and_resume.py | 重复执行幂等 / 失败自动续跑 / 步数上限明确未完成 | 3/3 通过 |

## examples/ 运行记录（输入、实际输出、Trace）

| 目录 | 场景 | 覆盖验收点 |
|---|---|---|
| `examples/case1_normal_premium/` | 预算 20 直接 premium（13.0/20） | 正常完成 |
| `examples/case2_budget_downgrade/` | 预算 10：premium 13 超限 → 降级 standard 9.5（题面参考实例） | 正常完成 + 预算超限重规划 |
| `examples/case3_missing_input/` | 缺 deadline_hours：未调用任何工具，花费 0 | 信息不足 |
| `examples/case4_tool_failure_fallback/` | 检索始终失败 → 重试 2 次 → 兜底素材 → 完成 | 工具失败 |
| `examples/case5_infeasible_gap/` | 预算 5：最低档也需 9.0 → 报告预算缺口 4.0 | 不可行 + 明确未完成状态 |
| `examples/case6_real_llm/` | 真实 DeepSeek：直接选 standard（9.0/10），与 Mock 路径不同 | 真实模型决策 + 第二条路径 |
| `examples/case7_repeat_run/` | 同输入连跑两次：第二次复用结果、零工具调用 | 重复执行幂等 |
| `examples/case8_resume/` | 脚本 2 连败中断 → 续跑完成，素材不重复扣费 | 失败续跑（加分项） |

每个案例目录含 `runs/<run_id>/`：`input 命令`（见该组 README）、`result.json`（实际输出）、`trace.jsonl`（逐步决策轨迹：步骤号、工具参数、返回摘要、决策依据、实扣费）、`state.json`；成功案例另有 `plan.json`。steps 上限证据另见 `tests/test_repeat_and_resume.py::test_max_steps_reached_reports_clear_status`。

## 失败与限制（如实说明）

1. **Mock 只验证流程，不证明真实模型决策效果**：MockPlannerLLM 是规则策略（premium 优先、超限降级），用于离线复现与回归测试；真实模型行为见 case6（仅 1 组，样本少，且受 API 限流影响未跑更多场景）。
2. **工具是本地函数 + 合成数据**：素材库 10 条 + 兜底 3 条，价格/工时为模拟值；脚本内容为模板化生成，非真实创作。
3. **计费/工时是简化模型**：没有真实 API 计费与耗时，仅用于驱动预算/工期约束决策。
4. **未实现**：Web/API 服务、并发、鉴权、多 Agent、素材真实检索；真实模型的 prompt 仅做过基础调优，未做系统化评测集。
5. **工期缺口场景的行为**：premium 生成后才发现超工期时，已消耗的生成工时按沉没成本计入，降级后仍超期则诚实报告缺口（不回滚），见 `test_deadline_infeasible_reports_gap`。
