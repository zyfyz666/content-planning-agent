# 02 · 方案（调用流程、动态决策、技术取舍）

## 总体结构（原生实现，未用 Agent 框架）

```
src/schemas.py   数据结构：Action / Observation / RunState / FinalResult
src/llm.py       模型层：BasePlannerLLM 抽象 + MockPlannerLLM（离线规则策略）
                          + OpenAICompatLLM（openai SDK，OpenAI 兼容协议）
src/tools.py     5 个工具（本地函数实现）+ AgentEnv 计费 + FaultInjector 故障注入
src/agent.py     ReActAgent：决策循环、依赖失效、重规划、状态持久化、幂等复用
src/main.py      CLI 入口
```

- 语言 Python 3.12；模型接入用 `openai>=1.30` SDK（OpenAI 兼容协议），框架选型上**未用** LangGraph/ADK——本题核心是"模型每轮看观察、选动作"的小循环，原生实现约 300 行即可完整控制 trace、计费与持久化语义，引入框架反而难以精确实现"失败调用不计费但计步""档位变更使旧估算失效"这类细粒度规则。
- 工具为本地函数（题面允许），统一协议：`run(params, state, env) -> Observation`，成功与失败都是观察，不抛异常打断循环。

## 调用流程

```
while 未结束 且 steps_used < max_steps:
    view   = 任务输入 + 工具规格 + 当前状态 + 失败计数 + 上一步观察
    action = llm.decide(view)                # ① 模型选择动作（JSON：thought/tool/params 或 finish）
    obs    = registry.run(action)            # ② 执行工具（统一计费、故障注入）
    state  = 更新骨架步骤/费用/依赖失效，持久化 trace.jsonl + state.json   # ③ 观察落盘
    模型下一轮依据 obs 调整（重试 / 换兜底 / 降级档位 / 结束）           # ④ 调整
```

模型输出协议：单个 JSON `{"thought","decision_basis","tool","params"}` 或 `{"thought","action":"finish","final_status","reason"}`；解析失败连续 3 次中止（真实模型异常同样包装为 LLMError 计入）。

## 动态决策点（模型根据观察调整）

| 观察到 | 调整动作 |
|---|---|
| 估算超预算/超工期，当前档位 premium | 降级 standard 重新生成脚本（脚本变更使旧估算失效，强制重估） |
| 已无更低档位 | finish(incomplete)，报告缺口数值 |
| search_materials 失败 1 次 | 重试一次 |
| 检索累计失败 2 次 | 改用 use_fallback_materials 兜底 |
| 兜底也失败 | finish(incomplete)，保留已成功结果 |
| generate_script 连续失败 2 次 | finish(incomplete)，保留素材结果 |
| 缺 theme/budget/deadline | 不调用任何付费工具，直接 finish(incomplete) |

## 关键取舍

1. **计费模型显式化**：失败调用不计费但计步（失败占用执行预算）；`generate_script` 换档位时旧 `estimate_cost` 结果作废——防止拿旧档位估算做决策（这是实现中发现的真实 bug，见 05）。
2. **保存硬校验**：save_plan 对不可行估算（超预算/超工期）拒绝保存，宁可 incomplete 也不产出超支方案。
3. **状态即事实源**：RunState 每步持久化（state.json/trace.jsonl），支撑重复执行幂等（completed 直接复用）与失败续跑（清空本轮失败计数，从断点继续，不重复执行已成功步骤）。
4. **Mock 与真实模型同一接口**（`decide(view) -> Action`）：离线可复现全部流程；真实模型验证决策效果（examples/case6，DeepSeek 直接选 standard，与 Mock 的 premium→降级路径不同，构成两条决策路径证据）。
5. **故障注入**为 CLI 参数（`--inject-fail "tool:n"`），便于测试与评审复现失败分支。
