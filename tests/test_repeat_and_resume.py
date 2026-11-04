"""验收点 5 + 加分项：重复执行幂等、失败后自动续跑、步数上限。"""
import json

from tests.helpers import make_agent, default_run_id


def _executed_calls(trace_path):
    calls = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        if d.get("tool") and d["tool"] != "(finish)":
            calls.append(d["tool"])
    return calls


def test_repeat_execution_reuses_completed_result(tmp_path):
    """同一输入重复执行：直接复用已保存方案，不再执行工具、不再扣费。"""
    inputs = {"theme": "秋季新品奶茶上市", "budget": 10.0, "deadline_hours": 24.0}
    run_id = "t-repeat"

    first = make_agent(inputs, tmp_path, run_id=run_id).run()
    assert first.status == "completed"
    assert first.steps_used == 6

    second = make_agent(inputs, tmp_path, run_id=run_id).run()
    assert second.status == "completed"
    assert second.steps_used == first.steps_used  # 未增加任何步骤
    assert second.cost == first.cost              # 费用不变（未重复扣费）
    assert any("重复执行" in n for n in second.notes)
    # trace 中工具调用次数不变（第二次执行没有产生新的工具调用）
    trace_path = tmp_path / run_id / "trace.jsonl"
    assert len(_executed_calls(trace_path)) == first.steps_used


def test_resume_after_incomplete_run(tmp_path):
    """第一次因脚本失败中断 → 相同输入再次执行自动续跑，不重复执行已成功步骤。"""
    inputs = {"theme": "秋季新品奶茶上市", "budget": 10.0, "deadline_hours": 24.0}
    run_id = default_run_id(inputs)

    first = make_agent(inputs, tmp_path, run_id=run_id, inject_fail="generate_script:2").run()
    assert first.status == "incomplete"

    second = make_agent(inputs, tmp_path, run_id=run_id).run()
    assert second.status == "completed"
    assert second.saved_plan and second.saved_plan["path"]
    # 续跑提示
    assert any("继续" in n for n in second.notes)
    # 素材步骤只执行过一次（复用上次状态，未重复检索、未重复扣费）
    plan = {s["step"]: s for s in second.task_plan}
    assert plan["materials"]["attempts"] == 1
    # 脚本步骤跨运行累计：第一次 2 次失败 + 续跑后 premium/standard 各 1 次
    assert plan["script"]["attempts"] == 4
    assert plan["script"]["status"] == "success"
    assert second.tool_results["script"]["tier"] == "standard"
    # 费用：search 0.5 + premium 脚本 0.5 + standard 脚本 0.5 = 1.5，未重复扣素材检索费
    assert second.cost["tool_fees"] == 1.5
    assert second.cost["total"] == 9.5


def test_max_steps_reached_reports_clear_status(tmp_path):
    """步数上限 2：耗尽后返回明确未完成状态，并保留已完成结果。"""
    inputs = {"theme": "秋季新品奶茶上市", "budget": 20.0, "deadline_hours": 24.0}
    result = make_agent(inputs, tmp_path, run_id="t-maxsteps", max_steps=2).run()
    assert result.status == "incomplete"
    assert "步数上限" in result.unfinished_reason
    assert result.steps_used == 2
    assert result.saved_plan is None
    # 已完成部分保留：素材检索成功
    plan = {s["step"]: s for s in result.task_plan}
    assert plan["materials"]["status"] == "success"
