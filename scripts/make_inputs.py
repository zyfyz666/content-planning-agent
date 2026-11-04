import json
import pathlib

spec = {
    "case1_normal_premium":        ("秋季新品奶茶上市", 20, 24, "mock", ""),
    "case2_budget_downgrade":      ("秋季新品奶茶上市", 10, 24, "mock", ""),
    "case3_missing_input":         ("周年庆大促", 15, None, "mock", "不传 --deadline-hours"),
    "case4_tool_failure_fallback": ("冬季热饮上新", 20, 24, "mock", "--inject-fail \"search_materials:-1\" 表示素材检索始终失败"),
    "case5_infeasible_gap":        ("新品试吃活动", 5, 12, "mock", ""),
    "case6_real_llm":              ("国庆黄金周出游季", 10, 24, "real", "真实模型 DeepSeek（需 .env 配置）"),
    "case7_repeat_run":            ("双11预热活动", 20, 24, "mock", "同一命令连续运行两次，对比 result_run1/run2"),
    "case8_resume":                ("周年庆庆典", 10, 24, "mock", "首次运行附加 --inject-fail \"generate_script:2\" 使其失败中断，第二次同输入续跑"),
}

for case, (theme, budget, dh, model, note) in spec.items():
    cmd = f'python -m src.main --theme "{theme}" --budget {budget}'
    if dh is not None:
        cmd += f" --deadline-hours {dh}"
    if model == "real":
        cmd += " --model real"
    if case == "case4_tool_failure_fallback":
        cmd += ' --inject-fail "search_materials:-1"'
    if case == "case8_resume":
        cmd += ' --inject-fail "generate_script:2"'
    data = {
        "command": cmd,
        "inputs": {"theme": theme, "budget": budget, "deadline_hours": dh},
        "model": model,
    }
    if case in ("case3_missing_input", "case4_tool_failure_fallback", "case6_real_llm", "case7_repeat_run", "case8_resume"):
        data["note"] = note
    path = pathlib.Path("examples") / case / "input.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print("input.json written for", len(spec), "cases")
