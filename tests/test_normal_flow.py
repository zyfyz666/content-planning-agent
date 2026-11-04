"""验收点 1：正常完成（两种预算下两条不同路径）。"""
from pathlib import Path

from tests.helpers import make_agent


def test_normal_premium_direct(tmp_path):
    """预算充足（20）：直接选 premium（估算 13 ≤ 20），一次通过并保存。"""
    inputs = {"theme": "秋季新品奶茶上市", "budget": 20.0, "deadline_hours": 24.0}
    agent = make_agent(inputs, tmp_path, run_id="t-normal-premium")
    result = agent.run()

    assert result.status == "completed"
    assert result.saved_plan and result.saved_plan["path"]
    assert result.cost["total"] <= result.cost["budget"]
    assert result.cost["within_budget"] is True
    assert result.duration["within_deadline"] is True
    assert result.tool_results["script"]["tier"] == "premium"
    # 步骤依赖顺序：materials → script → estimate → save
    statuses = {s["step"]: s["status"] for s in result.task_plan}
    assert statuses == {"materials": "success", "script": "success",
                        "estimate": "success", "save": "success"}


def test_normal_with_downgrade_reference_case(tmp_path):
    """参考实例：预算 10，初始 premium 估算 13 超预算 → 降级 standard（8）→ 重估 → 保存。"""
    inputs = {"theme": "秋季新品奶茶上市", "budget": 10.0, "deadline_hours": 24.0}
    agent = make_agent(inputs, tmp_path, run_id="t-downgrade")
    result = agent.run()

    assert result.status == "completed"
    # 重规划证据：先 premium 后 standard，两次估算
    plan = {s["step"]: s for s in result.task_plan}
    assert plan["script"]["tool_calls"] == ["generate_script", "generate_script"]
    assert plan["estimate"]["tool_calls"] == ["estimate_cost", "estimate_cost"]
    assert result.tool_results["estimate"]["tier"] == "standard"
    # 费用合计：工具费 1.5（search 0.5 + 两次脚本 1.0）+ 制作费 8.0 = 9.5 ≤ 10
    assert result.cost["tool_fees"] == 1.5
    assert result.cost["production"] == 8.0
    assert result.cost["total"] == 9.5
    assert result.cost["within_budget"] is True
    assert result.saved_plan and Path(result.saved_plan["path"]).exists()
    # trace 记录重规划决策依据
    trace = (Path(result.saved_plan["path"]).parent / "trace.jsonl").read_text(encoding="utf-8")
    assert "重规划" in trace or "降级" in trace
