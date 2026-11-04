"""测试公共工具：快速构建 Agent（mock 模式）。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agent import ReActAgent, default_run_id  # noqa: E402
from src.llm import MockPlannerLLM  # noqa: E402
from src.tools import (  # noqa: E402
    EstimateCostTool,
    FallbackMaterialsTool,
    GenerateScriptTool,
    SavePlanTool,
    SearchMaterialsTool,
    ToolRegistry,
)

DATA_DIR = str(ROOT / "data")

__all__ = ["make_agent", "default_run_id", "DATA_DIR"]


def make_agent(inputs, runs_dir, run_id=None, max_steps=12, inject_fail=None, fresh=False):
    rid = run_id or default_run_id(inputs)
    registry = ToolRegistry([
        SearchMaterialsTool(),
        FallbackMaterialsTool(),
        GenerateScriptTool(),
        EstimateCostTool(),
        SavePlanTool(lambda: str(Path(runs_dir) / rid)),
    ])
    return ReActAgent(
        llm=MockPlannerLLM(),
        registry=registry,
        inputs=inputs,
        data_dir=DATA_DIR,
        runs_dir=str(runs_dir),
        run_id=rid,
        max_steps=max_steps,
        inject_fail=inject_fail,
        fresh=fresh,
    )
