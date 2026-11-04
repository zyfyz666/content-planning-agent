# 02 · 工具协议与计费规则

## 工具清单

| 工具 | 费用（模拟单位） | 工时（模拟小时） | 说明 |
|---|---|---|---|
| `search_materials` | 0.5 | 1.0 | 按主题关键词检索素材库，返回相关性最高的 ≤3 条 |
| `use_fallback_materials` | 0 | 0.2 | 素材检索失败后的兜底通用素材（F001-F003） |
| `generate_script` | 0.5 | premium 0.3 / standard 0.2 | 基于已有素材生成指定档位脚本；档位变更会使旧估算失效 |
| `estimate_cost` | 0 | 0.1 | 估算总费用与总工期（含已花费部分），判断预算/工期可行性 |
| `save_plan` | 0 | 0.1 | 保存方案到 `plan.json`；含预算/工期硬校验，不可行时拒绝保存 |

## 计费与步骤规则（考核要求）

1. **失败调用不计费，但计入步数**：工具执行失败（含故障注入）不扣费，但 `steps_used` 照常 +1——失败是有成本的（占用执行预算）。
2. **步数上限**：默认 12 步（`--max-steps` 可调）。耗尽后返回 `incomplete`，原因中明确说明"达到步数上限"，并保留已完成步骤的结果与花费。
3. **依赖失效**：`generate_script` 生成新档位脚本时，旧的 `estimate_cost` 结果自动作废（estimate 依赖 script），模型必须重新估算——这防止用旧档位的估算数据做决策。

## 工具间依赖

```
search_materials ──┐
                   ├─→ generate_script ─→ estimate_cost ─→ save_plan
use_fallback_materials ─┘
```

- 没有素材时直接生成脚本会被拒绝（`no_materials`）；
- 没有脚本/估算时保存会被拒绝（`missing_prereq`）；
- 估算不可行时保存被硬校验拒绝（`budget_deadline_guard`）。

## 故障注入（测试钩子）

`--inject-fail "工具名:次数"`，次数 `-1` 表示始终失败，支持逗号分隔多个工具：

```bash
python -m src.main ... --inject-fail "search_materials:2"          # 失败 2 次后恢复
python -m src.main --theme X --budget 20 --deadline-hours 24 --inject-fail "generate_script:-1"  # 始终失败
python -m src.main --theme X --budget 20 --deadline-hours 24 --inject-fail "search_materials:-1,use_fallback_materials:-1"
```
