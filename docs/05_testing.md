# 05 · 测试设计与运行指南

## 测试矩阵（tests/，共 16 个用例，覆盖全部验收点）

| 文件 | 覆盖场景 |
|---|---|
| `test_normal_flow.py` | ① 预算 20 直接 premium 完成；② 预算 10 触发降级重规划（题面参考实例，验证 12→8 重规划与最终 9.5） |
| `test_missing_inputs.py` | ② 缺 theme / budget / deadline_hours：立即结束、不调用任何工具、花费 0 |
| `test_tool_failure.py` | ③ 工具失败：失败 1 次重试成功；始终失败→兜底素材；全部素材途径失败→停止；脚本 2 连败→停止且保留素材结果 |
| `test_budget_overrun.py` | 预算超限降级（12→8）；预算 5 无可行方案→缺口 4.0；工期不可行→诚实报告工期缺口 3.4h |
| `test_repeat_and_resume.py` | ⑤ 重复执行幂等（复用结果、不重复扣费、trace 不增长）；失败后自动续跑（不重复检索素材）；步数上限→明确未完成状态 |

## 测试策略

- 全部使用 `MockPlannerLLM`，不依赖网络，`pytest tests` 秒级完成；
- 故障注入通过 `FaultInjector` 精确控制"第 N 次失败"，覆盖重试/降级/停止三种分支；
- 断言聚焦**行为契约**：状态码、费用合计、步骤依赖顺序、重规划证据（tool_calls 序列）、持久化文件存在性。

## 运行

```bash
pip install -r requirements.txt
python -m pytest tests -v          # 单元测试
python -m pytest tests -q          # 简洁输出（16 passed）
```

## CLI 速查

```bash
python -m src.main --theme "主题" --budget 10 --deadline-hours 24            # mock 模式
python -m src.main --theme X --budget 10 --deadline-hours 24 --model real   # 真实模型（需 .env）
python -m src.main --theme X --budget 5  --deadline-hours 12                # 不可行路径
python -m src.main ... --inject-fail "generate_script:-1"                   # 故障注入
python -m src.main ... --max-steps 2                                        # 步数上限
```

退出码：`0` = completed；`3` = incomplete（含明确原因）。
