"""CLI 入口：内容任务规划 Agent。

示例：
  .venv/Scripts/python -m src.main --theme "秋季新品奶茶上市" --budget 10 --deadline-hours 24
  .venv/Scripts/python -m src.main --theme "..." --budget 5 --deadline-hours 24 --model mock
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .agent import ReActAgent, default_run_id
from .llm import make_llm
from .tools import (
    EstimateCostTool,
    FallbackMaterialsTool,
    GenerateScriptTool,
    SavePlanTool,
    SearchMaterialsTool,
    ToolRegistry,
)


def build_registry(run_dir_fn) -> ToolRegistry:
    return ToolRegistry([
        SearchMaterialsTool(),
        FallbackMaterialsTool(),
        GenerateScriptTool(),
        EstimateCostTool(),
        SavePlanTool(run_dir_fn),
    ])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="内容任务规划 Agent（ReAct）")
    parser.add_argument("--theme", help="活动主题")
    parser.add_argument("--budget", type=float, help="预算（模拟单位）")
    parser.add_argument("--deadline-hours", type=float, help="截止时间（小时，模拟）")
    parser.add_argument("--model", choices=["mock", "real"], default="mock",
                        help="mock=离线规则策略；real=OpenAI 兼容 API（需 .env）")
    parser.add_argument("--max-steps", type=int, default=12, help="执行步数上限")
    parser.add_argument("--inject-fail", default=None,
                        help='注入工具失败，如 "search_materials:1" 或 "generate_script:-1"（-1=始终失败）')
    parser.add_argument("--run-id", default=None, help="指定运行 ID（默认由输入派生，重复执行可复用）")
    parser.add_argument("--fresh", action="store_true", help="忽略既有状态，强制重新执行")
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args(argv)

    inputs = {"theme": args.theme, "budget": args.budget, "deadline_hours": args.deadline_hours}
    run_id = args.run_id or default_run_id(inputs)

    def run_dir_fn():
        return os.path.join(args.runs_dir, run_id)

    llm = make_llm(args.model)
    agent = ReActAgent(
        llm=llm,
        registry=build_registry(run_dir_fn),
        inputs=inputs,
        data_dir=args.data_dir,
        runs_dir=args.runs_dir,
        run_id=run_id,
        max_steps=args.max_steps,
        inject_fail=args.inject_fail,
        fresh=args.fresh,
    )
    result = agent.run()
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.status == "completed" else 3


if __name__ == "__main__":
    sys.exit(main())
