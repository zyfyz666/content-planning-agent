# 03 · ReAct 决策过程

## 循环

```
while 未结束 且 steps_used < max_steps:
    view  = 任务输入 + 工具规格 + 当前状态 + 失败计数 + 上一步观察
    action = llm.decide(view)            # Thought + Tool+Params 或 Finish
    obs   = 工具执行(action)             # 成功/失败均为观察
    state 持久化（state.json / trace.jsonl）
    model 据 obs 调整下一步
```

## 决策轨迹示例（预算 10，Mock 策略，见 examples/case2）

| 步 | Thought（摘要） | 动作 | 观察 | 下一步依据 |
|---|---|---|---|---|
| 1 | 先获取素材 | search_materials | 2 条相关素材 | 有素材才能生成脚本 |
| 2 | 预算 20 内默认 premium | generate_script(premium) | 成功 | 需要估算验证 |
| 3 | 估算可行性 | estimate_cost | 总计 13.0 > 预算 10，超 3.0 | premium 不可行 |
| 4 | **重规划：降级档位** | generate_script(standard) | 成功 | 脚本已变更，旧估算作废 |
| 5 | 重新估算 | estimate_cost | 总计 9.5 ≤ 10，可行 | 满足约束，可以保存 |
| 6 | 落盘 | save_plan | 保存成功 → 结束(completed) | — |

trace.jsonl 中每条记录都含 `thought` 与 `decision_basis` 字段，可逐步审计模型的决策依据。

## 重规划触发条件

- **估算超预算/超工期**：若当前档位 premium 且尚未尝试 standard → 降级重生成脚本；已无更低档 → 结束(incomplete) 并报告缺口。
- **素材检索失败**：重试 1 次 → 仍失败则 `use_fallback_materials` 兜底；两者皆败 → 结束(incomplete)。
- **脚本生成连续 2 次失败**：停止生成，保留已成功的素材结果。

## 两条不同决策路径（验收点）

- Mock（规则策略）：premium 优先，超预算后降级（case1/case2）。
- DeepSeek（真实模型）：看到预算 10 时直接选 standard，一次通过（case6）。
- 两者都合法，说明执行流由模型决策驱动、而非固定脚本。
