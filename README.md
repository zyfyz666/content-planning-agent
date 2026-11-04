# 内容任务规划 Agent（小影校招 · AI Agent 开发岗考核）

基于 ReAct 循环的内容任务规划 Agent：在**预算**与**截止时间**约束下，为主题产出并保存一份内容活动方案（素材 → 脚本 → 成本估算 → 保存）。不可行时给出明确原因与缺口，支持工具故障重试、兜底降级、重复执行幂等与失败续跑。

```
主题+预算+截止时间 ──▶ [ReAct 循环] ──> 检索素材 ─> 生成脚本 ─> 估算成本 ─> 保存方案
                        模型决策 → 工具执行 → 观察调整        （超预算自动降级重规划）
```

## 快速开始

```bash
pip install -r requirements.txt

# 离线 Mock 模式（无需任何配置，复现题面参考实例：预算 10，12 超限 → 降级 8 → 保存）
python -m src.main --theme "秋季新品奶茶上市" --budget 10 --deadline-hours 24

# 真实模型模式：复制 .env.example 为 .env 并填入 OpenAI 兼容 API 的 Key
python -m src.main --theme "国庆黄金周出游季" --budget 10 --deadline-hours 24 --model real

# 运行测试（16 个用例，离线秒级）
python -m pytest tests -q
```

## 目录结构

```
src/
  schemas.py   # 数据结构（TaskInput / Action / Observation / RunState / FinalResult）
  llm.py       # 模型层：MockPlannerLLM（离线规则策略）+ OpenAICompatLLM（真实模型）
  tools.py     # 5 个工具 + 计费 + 故障注入
  agent.py     # ReAct 主循环 / 状态持久化 / 重规划
  main.py      # CLI 入口
data/          # 合成数据：素材库、成本价格表、档位定价
tests/         # 16 个 pytest 用例，覆盖全部验收点
docs/          # 01 设计 · 02 工具与计费 · 03 ReAct 决策 · 04 状态与续跑 · 05 测试
examples/      # 6 组真实运行记录（含两条不同决策路径）
```

## 功能与考核点对照

| 考核要求 | 实现 | 证据 |
|---|---|---|
| ReAct 循环（决策→工具→观察→调整） | `src/agent.py` ReActAgent，每步记录 thought 与 decision_basis | `docs/03`、`examples/*/runs/*/trace.jsonl` |
| ≥2 条不同决策路径 | Mock：premium 超预算后降级；真实 DeepSeek 直接选 standard | `examples/case1,2` vs `case6` |
| 步数上限与未完成状态 | `--max-steps`（默认 12），耗尽返回 incomplete + 已保留结果 | `tests/test_repeat_and_resume.py` |
| 缺输入不执行 | 缺 theme/budget/deadline 立即结束，不调用任何付费工具 | `tests/test_missing_inputs.py` |
| 工具失败处理 | 重试 1 次 → 兜底素材 → 仍败则停止并保留已完成结果；脚本 2 连败停止 | `tests/test_tool_failure.py`、case4 |
| 预算超限 | premium 13 超预算 10 → 自动降级 standard 9.5（题面参考实例） | `examples/case2` |
| 重复执行幂等 | 相同输入复用结果、不重复扣费；未完成任务自动续跑（加分项） | `docs/04`、`tests/test_repeat_and_resume.py` |
| 真实模型接入 | OpenAI 兼容协议（DeepSeek/GLM/Qwen），`.env` 配置，Mock 与真实模型同一决策接口 | `examples/case6_real_llm` |

## 计费模型（简化）

| 工具 | 费用 | 工时 |
|---|---|---|
| search_materials | 0.5 | 1.0h |
| generate_script | 0.5 | 档位相关 |
| estimate_cost / use_fallback / save_plan | 0 | 0.1–0.2h |
| 方案制作费 | premium 12 / standard 8 | premium 6h / standard 4h |

失败调用不计费但计步；估算总额 = 工具费累计 + 制作费，超过预算/截止即不可行，触发重规划。

## CLI 参数

| 参数 | 说明 |
|---|---|
| `--theme / --budget / --deadline-hours` | 任务输入 |
| `--model mock\|real` | Mock 规则策略 / OpenAI 兼容真实模型 |
| `--inject-fail "tool:n"` | 注入工具失败，`-1` 为始终失败（测试钩子） |
| `--max-steps N` | 步数上限（默认 12） |
| `--fresh` | 丢弃历史状态强制重跑 |
| `--run-id` | 显式指定运行 ID |

退出码：`0` completed / `3` incomplete。

## 运行产物

每次运行写入 `runs/<run_id>/`：`trace.jsonl`（逐步决策轨迹）、`state.json`（可续跑状态）、`result.json`（最终结果）、`plan.json`（保存的方案）。示例见 [examples/README.md](examples/README.md)。
