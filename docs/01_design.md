# 01 · 项目设计与模块结构

## 目标

在预算与截止时间内，为主题产出一份可保存的内容活动方案（素材 → 脚本 → 成本估算 → 保存）。方案不可行时，给出明确的未完成原因与缺口。

## 架构

```
┌─────────────┐     decide(view)      ┌──────────────┐
│ ReActAgent  │ ────────────────────▶ │ PlannerLLM   │  MockPlannerLLM（离线规则）
│ (调度循环)   │ ◄──────────────────── │ (Action JSON)│  OpenAICompatLLM（真实 API）
└─────┬───────┘      Action(JSON)     └──────────────┘
      │ _execute(tool, params)
      ▼
┌─────────────┐   run(params, state)  ┌──────────────┐
│ ToolRegistry│ ────────────────────▶ │ 5 个工具      │  search / fallback / script /
└─────┬───────┘ ◄──────────────────── │ (统一接口)    │  estimate / save
      │ Observation(ok, summary, data)└──────────────┘
      ▼
  RunState（全程持久化 state.json / trace.jsonl / result.json）
```

## 模块职责

| 模块 | 职责 |
|---|---|
| `src/schemas.py` | 数据结构：TaskInput、Action、Observation、RunState、FinalResult 等 |
| `src/llm.py` | 模型层：统一的 `decide(view) -> Action` 接口；Mock 规则策略与 OpenAI 兼容 API 两种实现 |
| `src/tools.py` | 工具层：5 个工具 + 计费（AgentEnv）+ 故障注入（FaultInjector） |
| `src/agent.py` | ReAct 主循环、步骤骨架跟踪、状态持久化、终止条件、结果汇总 |
| `src/main.py` | CLI 入口 |

## 核心设计决策

1. **模型只做决策，工具只做执行**：模型每轮只能输出一个 JSON Action（工具调用或 finish），所有副作用都在工具内完成，便于测试与故障注入。
2. **Mock 与真实模型同构**：两者实现同一个 `decide(view)` 接口，agent 对其无感知，保证离线演示与在线行为可比。
3. **状态即事实源**：`RunState` 记录已完成步骤的结果与花费，任何一步失败都能从 `state.json` 恢复，这是重复执行幂等与续跑的基础。
4. **失败也是一种观察**：工具失败返回 `Observation(ok=False, error=...)` 而不是抛异常终止，模型据此决定重试、降级或结束。
