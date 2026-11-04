"""验收点 3：工具失败（重试 / 兜底 / 停止）。"""
from tests.helpers import make_agent


def test_search_fail_once_then_retry(tmp_path):
    """检索失败 1 次 → 重试成功，正常完成。"""
    inputs = {"theme": "秋季新品奶茶上市", "budget": 20.0, "deadline_hours": 24.0}
    result = make_agent(inputs, tmp_path, run_id="t-retry", inject_fail="search_materials:1").run()
    assert result.status == "completed"
    plan = {s["step"]: s for s in result.task_plan}
    assert plan["materials"]["attempts"] == 2
    assert plan["materials"]["status"] == "success"
    assert result.tool_results["materials_source"] == "search"


def test_search_always_fail_use_fallback(tmp_path):
    """检索始终失败 → 切换 use_fallback_materials 兜底 → 完成并标注 fallback。"""
    inputs = {"theme": "秋季新品奶茶上市", "budget": 20.0, "deadline_hours": 24.0}
    result = make_agent(inputs, tmp_path, run_id="t-fallback", inject_fail="search_materials:-1").run()
    assert result.status == "completed"
    assert result.tool_results["materials_source"] == "fallback"
    assert result.tool_results["script"]["uses_fallback"] is True
    # 兜底素材也进入脚本引用
    assert result.tool_results["script"]["based_on_materials"]


def test_all_material_paths_fail_stop_with_partial_results(tmp_path):
    """检索与兜底都失败 → 停止并保留已完成步骤，给出明确未完成原因。"""
    inputs = {"theme": "秋季新品奶茶上市", "budget": 20.0, "deadline_hours": 24.0}
    result = make_agent(
        inputs, tmp_path, run_id="t-allfail",
        inject_fail="search_materials:-1,use_fallback_materials:-1",
    ).run()
    assert result.status == "incomplete"
    assert result.unfinished_reason
    assert result.saved_plan is None
    plan = {s["step"]: s for s in result.task_plan}
    assert plan["materials"]["status"] == "failed"
    assert plan["script"]["status"] == "pending"


def test_script_fail_twice_stop_keep_materials(tmp_path):
    """脚本连续失败 2 次 → 停止，但素材结果与花费保留。"""
    inputs = {"theme": "秋季新品奶茶上市", "budget": 20.0, "deadline_hours": 24.0}
    result = make_agent(inputs, tmp_path, run_id="t-scriptfail", inject_fail="generate_script:2").run()
    assert result.status == "incomplete"
    assert result.tool_results["materials"]  # 素材结果保留
    assert result.cost["tool_fees"] > 0      # 已成功的花费保留
    plan = {s["step"]: s for s in result.task_plan}
    assert plan["materials"]["status"] == "success"
    assert plan["script"]["status"] == "failed"
    assert plan["script"]["attempts"] == 2
