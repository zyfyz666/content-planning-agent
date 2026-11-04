"""ReAct Agent 核心：模型选择动作 → 执行工具 → 观察结果 → 模型调整下一步或结束。

- task_plan（预设骨架）只承载步骤依赖与实际状态展示，不代替模型决策；
- 每步执行后持久化 state.json / trace.jsonl，支持失败续跑与重复执行幂等；
- 达到 max_steps 立即停止，返回明确的未完成状态并保留已成功步骤的结果。
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Optional

from .llm import BasePlannerLLM, LLMError
from .schemas import (
    Action,
    FinalResult,
    FinalStatus,
    Observation,
    PlanStep,
    RunState,
    StepStatus,
    ToolCallRecord,
)
from .tools import AgentEnv, FaultInjector, ToolError, ToolRegistry

SKELETON = [
    ("materials", "检索/准备素材"),
    ("script", "生成活动脚本"),
    ("estimate", "成本与工期估算"),
    ("save", "保存方案"),
]

TOOL_TO_SKELETON = {
    "search_materials": "materials",
    "use_fallback_materials": "materials",
    "generate_script": "script",
    "estimate_cost": "estimate",
    "save_plan": "save",
}


def default_run_id(inputs: dict) -> str:
    raw = json.dumps(
        [inputs.get("theme"), inputs.get("budget"), inputs.get("deadline_hours")],
        ensure_ascii=False,
    )
    return "run-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]


class ReActAgent:
    def __init__(
        self,
        llm: BasePlannerLLM,
        registry: ToolRegistry,
        inputs: dict,
        data_dir: str,
        runs_dir: str,
        run_id: Optional[str] = None,
        max_steps: int = 12,
        inject_fail: Optional[str] = None,
        fresh: bool = False,
    ):
        self.llm = llm
        self.registry = registry
        self.inputs = dict(inputs)
        self.data_dir = data_dir
        self.runs_dir = runs_dir
        self.max_steps = max_steps
        self.run_id = run_id or default_run_id(self.inputs)
        self.run_dir = os.path.join(runs_dir, self.run_id)
        if fresh and os.path.isdir(self.run_dir):
            for name in ("state.json", "result.json", "trace.jsonl", "plan.json"):
                p = os.path.join(self.run_dir, name)
                if os.path.exists(p):
                    os.remove(p)
        os.makedirs(self.run_dir, exist_ok=True)
        self.env = AgentEnv(data_dir, lambda: self.run_dir, FaultInjector(inject_fail))

    # ------------------------------------------------------------------ run
    def run(self) -> FinalResult:
        state = self._load_state() or self._init_state()
        notes: list[str] = []

        # 重复执行：已完成的运行直接复用 result.json，不重复扣费
        if state.finished and state.final_status == FinalStatus.COMPLETED.value:
            notes.append("重复执行：检测到该任务已有完成的方案，直接复用已保存结果（未重复执行工具、未重复扣费）")
            return self._finalize(state, notes)

        # 失败续跑：上次未完成的运行，从已完成步骤的状态继续
        if state.finished and state.final_status == FinalStatus.INCOMPLETE.value:
            notes.append(f"检测到上次未完成的运行（原因：{state.unfinished_reason}），从已完成步骤继续")
            state.finished = False
            state.final_status = None
            state.unfinished_reason = None
            state.model_fail_streak = 0
            state.fail_counts = {}

        while not state.finished and state.steps_used < state.max_steps:
            view = self._build_view(state)
            try:
                action = self.llm.decide(view)
            except LLMError as exc:
                state.model_fail_streak += 1
                self._trace_raw({
                    "event": "model_error", "error": str(exc),
                    "steps_used": state.steps_used,
                })
                if state.model_fail_streak >= 3:
                    state.finished = True
                    state.final_status = FinalStatus.INCOMPLETE.value
                    state.unfinished_reason = f"模型连续 {state.model_fail_streak} 次输出异常（{exc}），任务中止"
                continue

            state.model_fail_streak = 0

            if action.is_finish:
                state.finished = True
                state.final_status = action.final_status or FinalStatus.INCOMPLETE.value
                state.unfinished_reason = action.reason or None
                self._trace_action(state, action, Observation(ok=True, summary="任务结束"), executed=False)
                break

            fee_before = state.fee_spent
            obs = self._execute(action, state)
            fee_charged = round(state.fee_spent - fee_before, 2)
            state.steps_used += 1
            self._update_skeleton(state, action.tool, obs.ok)
            self._trace_action(state, action, obs, executed=True, fee_charged=fee_charged)
            self._persist(state)

        if not state.finished:  # 步数耗尽
            state.finished = True
            state.final_status = FinalStatus.INCOMPLETE.value
            state.unfinished_reason = (
                f"达到步数上限 {state.max_steps}，任务未完成；"
                f"已完成步骤的结果与花费（{state.fee_spent}）已保留，可用相同 run_id 续跑"
            )
        return self._finalize(state, notes)

    # -------------------------------------------------------------- execute
    def _execute(self, action: Action, state) -> Observation:
        tool = self.registry.get(action.tool or "")
        if tool is None:
            return Observation(ok=False, summary=f"未知工具 {action.tool}", data={}, error="unknown_tool")
        try:
            return tool.run(action.params, state, self.env)
        except ToolError as exc:
            state.record_fail(action.tool)
            return Observation(ok=False, summary=f"工具 {action.tool} 执行失败", data={}, error=str(exc))

    def _update_skeleton(self, state, tool_name: str, ok: bool) -> None:
        key = TOOL_TO_SKELETON.get(tool_name)
        if key is None:
            return
        for step in state.plan_steps:
            if step["step"] == key:
                step["attempts"] += 1
                step["tool_calls"].append(tool_name)
                step["status"] = StepStatus.SUCCESS.value if ok else StepStatus.FAILED.value
                step["detail"] = ("执行成功" if ok else "失败（模型可重试或改选替代方案）")
                return

    # ----------------------------------------------------------------- view
    def _build_view(self, state) -> dict:
        return {
            "task": "在预算与截止时间内为主题产出并保存内容活动方案；不可行时说明缺口并结束。",
            "tool_specs": self.registry.specs(),
            "inputs": {**state.inputs, "missing": self._missing_inputs(state.inputs)},
            "state": {
                "materials": state.materials,
                "materials_source": state.materials_source,
                "script": state.script,
                "estimate": state.estimate,
                "current_tier": state.current_tier,
                "tried_tiers": state.tried_tiers,
                "saved_plan_path": state.saved_plan_path,
                "fee_spent": state.fee_spent,
                "hours_spent": state.hours_spent,
            },
            "fail_counts": state.fail_counts,
            "last_observation": (
                {k: v for k, v in state.tool_call_log[-1].items() if k != "params"}
                if state.tool_call_log else None
            ),
            "steps_used": state.steps_used,
            "max_steps": state.max_steps,
        }

    @staticmethod
    def _missing_inputs(inputs: dict) -> list[str]:
        missing = []
        if not inputs.get("theme"):
            missing.append("theme")
        if inputs.get("budget") is None:
            missing.append("budget")
        if inputs.get("deadline_hours") is None:
            missing.append("deadline_hours")
        return missing

    # ---------------------------------------------------------------- trace
    def _trace_raw(self, payload: dict) -> None:
        with open(os.path.join(self.run_dir, "trace.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _trace_action(self, state, action: Action, obs: Observation, executed: bool,
                      fee_charged: float = 0.0) -> None:
        record = ToolCallRecord(
            step_index=state.steps_used,
            tool=action.tool if executed else "(finish)",
            params=action.params,
            thought=action.thought,
            decision_basis=action.decision_basis,
            ok=obs.ok,
            summary=obs.summary,
            error=obs.error,
            fee_charged=fee_charged if executed else 0.0,
            spent_after=state.fee_spent,
        )
        self._trace_raw(record.to_dict())
        if executed:
            state.tool_call_log.append(record.to_dict())

    # ------------------------------------------------------------- finalize
    def _finalize(self, state, notes: Optional[list[str]] = None) -> FinalResult:
        notes = notes or []
        completed = bool(state.saved_plan_path)
        est = state.estimate or {}
        result = FinalResult(
            status=FinalStatus.COMPLETED.value if completed else FinalStatus.INCOMPLETE.value,
            run_id=state.run_id,
            unfinished_reason=None if completed else (state.unfinished_reason or "未完成"),
            task_plan=state.plan_steps,
            tool_results={
                "materials": state.materials,
                "materials_source": state.materials_source,
                "script": state.script,
                "estimate": est,
            },
            cost={
                "tool_fees": state.fee_spent,
                "production": est.get("production_cost", 0.0),
                "total": est.get("projected_total", state.fee_spent),
                "budget": state.inputs.get("budget"),
                "within_budget": bool(est.get("within_budget", completed)),
            },
            duration={
                "projected_hours": est.get("projected_hours"),
                "deadline_hours": state.inputs.get("deadline_hours"),
                "within_deadline": bool(est.get("within_deadline", completed)),
            },
            saved_plan={"path": state.saved_plan_path} if state.saved_plan_path else None,
            steps_used=state.steps_used,
            max_steps=state.max_steps,
            notes=notes,
        )
        with open(os.path.join(self.run_dir, "result.json"), "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
        self._persist(state)
        return result

    # ------------------------------------------------------------ state I/O
    def _init_state(self) -> "RunState":
        from .schemas import RunState
        state = RunState(
            run_id=self.run_id,
            inputs=self.inputs,
            max_steps=self.max_steps,
            plan_steps=[{"step": k, "title": t, "status": StepStatus.PENDING.value,
                         "attempts": 0, "tool_calls": [], "detail": ""} for k, t in SKELETON],
        )
        self._persist(state)
        return state

    def _load_state(self) -> Optional["RunState"]:
        path = os.path.join(self.run_dir, "state.json")
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            return RunState.from_dict(json.load(f))

    def _persist(self, state) -> None:
        with open(os.path.join(self.run_dir, "state.json"), "w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)
