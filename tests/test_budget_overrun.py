"""验收点 4：预算超限 / 无可行方案。"""
from tests.helpers import make_agent


def test_budget_5_infeasible_with_gap(tmp_path):
    """预算 5：standard 也需 9.0，无可行方案 → 明确未完成 + 缺口 4.0。"""
    inputs = {"theme": "秋季新品奶茶上市", "budget": 5.0, "deadline_hours": 24.0}
    result = make_agent(inputs, tmp_path, run_id="t-gap").run()
    assert result.status == "incomplete"
    assert "4.0" in result.unfinished_reason
    assert result.saved_plan is None
    # 已尝试的档位已穷尽（初始 standard，无更低档）
    assert result.tool_results["estimate"]["tier"] == "standard"
    assert result.cost["within_budget"] is False


def test_budget_overrun_replan_keeps_cost_within_budget(tmp_path):
    """预算 10：premium 13 超限后重规划，最终总花费必须 ≤ 预算。"""
    inputs = {"theme": "夏季冰饮节", "budget": 10.0, "deadline_hours": 12.0}
    result = make_agent(inputs, tmp_path, run_id="t-replan").run()
    assert result.status == "completed"
    assert result.cost["total"] <= result.cost["budget"]
    assert result.cost["within_budget"] is True


def test_deadline_infeasible_reports_gap(tmp_path):
    """工期不可行：premium（11.3h > 8h）→ 降级 standard 仍超（11.4h，含已沉没的 premium 生成工时）
    → 诚实报告不可行与工期缺口，不保存方案。"""
    inputs = {"theme": "周末闪购", "budget": 20.0, "deadline_hours": 8.0}
    result = make_agent(inputs, tmp_path, run_id="t-deadline").run()
    assert result.status == "incomplete"
    assert "工期缺口" in result.unfinished_reason
    assert result.saved_plan is None
    est = result.tool_results["estimate"]
    assert est["within_deadline"] is False
    assert est["deadline_gap_hours"] == 3.4
    # 重规划证据：premium 与 standard 均已尝试
    plan = {s["step"]: s for s in result.task_plan}
    assert plan["script"]["tool_calls"] == ["generate_script", "generate_script"]
