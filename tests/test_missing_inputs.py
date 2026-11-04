"""验收点 2：输入信息缺失（budget / deadline_hours / theme）。"""
from tests.helpers import make_agent


def _run(inputs, tmp_path, run_id):
    return make_agent(inputs, tmp_path, run_id=run_id).run()


def test_missing_budget(tmp_path):
    result = _run({"theme": "周年庆活动", "deadline_hours": 24.0}, tmp_path, "t-miss-budget")
    assert result.status == "incomplete"
    assert "budget" in result.unfinished_reason
    # 未调用任何付费工具
    assert result.steps_used == 0
    assert result.cost["tool_fees"] == 0
    assert result.saved_plan is None


def test_missing_deadline(tmp_path):
    result = _run({"theme": "周年庆活动", "budget": 10.0}, tmp_path, "t-miss-deadline")
    assert result.status == "incomplete"
    assert "deadline_hours" in result.unfinished_reason
    assert result.steps_used == 0


def test_missing_theme(tmp_path):
    result = _run({"budget": 10.0, "deadline_hours": 24.0}, tmp_path, "t-miss-theme")
    assert result.status == "incomplete"
    assert "theme" in result.unfinished_reason
    assert result.steps_used == 0


def test_missing_all_inputs_finishes_before_tools(tmp_path):
    result = _run({}, tmp_path, "t-miss-all")
    assert result.status == "incomplete"
    assert result.steps_used == 0
    # task_plan 仍是四步骨架，但全部 pending
    assert all(s["status"] == "pending" for s in result.task_plan)
