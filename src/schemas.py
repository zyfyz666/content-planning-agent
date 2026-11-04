"""核心数据结构：任务输入、动作、观察、运行状态与最终结果。"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class StepStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class FinalStatus(str, Enum):
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"


@dataclass
class TaskInput:
    """用户输入：主题、预算、截止时间。"""
    theme: Optional[str] = None
    budget: Optional[float] = None
    deadline_hours: Optional[float] = None

    def missing_fields(self) -> list[str]:
        missing = []
        if not self.theme:
            missing.append("theme")
        if self.budget is None:
            missing.append("budget")
        if self.deadline_hours is None:
            missing.append("deadline_hours")
        return missing

    def to_dict(self) -> dict:
        return {
            "theme": self.theme,
            "budget": self.budget,
            "deadline_hours": self.deadline_hours,
        }


@dataclass
class Action:
    """模型的一步决策：调用某个工具，或结束。"""
    kind: str          # "tool" | "finish"
    tool: Optional[str] = None
    params: dict = field(default_factory=dict)
    thought: str = ""
    decision_basis: str = ""            # 决策依据（写入 trace）
    final_status: Optional[str] = None  # completed | incomplete（kind=finish 时）
    reason: str = ""

    @property
    def is_finish(self) -> bool:
        return self.kind == "finish"


@dataclass
class Observation:
    """工具执行结果（模型下一轮会看到）。"""
    ok: bool
    summary: str
    data: dict = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class PlanStep:
    """预设执行骨架中的一个步骤，状态由实际工具结果驱动。"""
    key: str          # materials / script / estimate / save
    title: str
    status: StepStatus = StepStatus.PENDING
    attempts: int = 0
    tool_calls: list[str] = field(default_factory=list)
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "step": self.key,
            "title": self.title,
            "status": self.status.value,
            "attempts": self.attempts,
            "tool_calls": self.tool_calls,
            "detail": self.detail,
        }


@dataclass
class ToolCallRecord:
    """一次工具调用记录（写入 trace 与状态）。"""
    step_index: int
    tool: str
    params: dict
    thought: str
    decision_basis: str
    ok: bool
    summary: str
    error: Optional[str]
    fee_charged: float
    spent_after: float

    def to_dict(self) -> dict:
        return {
            "step_index": self.step_index,
            "tool": self.tool,
            "params": self.params,
            "thought": self.thought,
            "decision_basis": self.decision_basis,
            "ok": self.ok,
            "observation_summary": self.summary,
            "error": self.error,
            "fee_charged": self.fee_charged,
            "spent_after": self.spent_after,
        }


@dataclass
class RunState:
    """跨步持久化的运行状态，支持失败续跑与重复执行幂等。"""
    run_id: str
    inputs: dict
    max_steps: int
    steps_used: int = 0
    fee_spent: float = 0.0
    hours_spent: float = 0.0
    materials: Optional[list] = None
    materials_source: Optional[str] = None
    script: Optional[dict] = None
    estimate: Optional[dict] = None
    current_tier: Optional[str] = None
    tried_tiers: list = field(default_factory=list)
    fail_counts: dict = field(default_factory=dict)
    plan_steps: list = field(default_factory=list)      # PlanStep.to_dict() 字典列表
    tool_call_log: list = field(default_factory=list)   # ToolCallRecord.to_dict() 列表
    model_fail_streak: int = 0
    finished: bool = False
    final_status: Optional[str] = None
    unfinished_reason: Optional[str] = None
    saved_plan_path: Optional[str] = None

    def fail_count(self, tool: str) -> int:
        return self.fail_counts.get(tool, 0)

    def record_fail(self, tool: str) -> None:
        self.fail_counts[tool] = self.fail_counts.get(tool, 0) + 1

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "inputs": self.inputs,
            "max_steps": self.max_steps,
            "steps_used": self.steps_used,
            "fee_spent": self.fee_spent,
            "hours_spent": self.hours_spent,
            "materials": self.materials,
            "materials_source": self.materials_source,
            "script": self.script,
            "estimate": self.estimate,
            "current_tier": self.current_tier,
            "tried_tiers": self.tried_tiers,
            "fail_counts": self.fail_counts,
            "plan_steps": [s if isinstance(s, dict) else s.to_dict() for s in self.plan_steps],
            "tool_call_log": [c if isinstance(c, dict) else c.to_dict() for c in self.tool_call_log],
            "model_fail_streak": self.model_fail_streak,
            "finished": self.finished,
            "final_status": self.final_status,
            "unfinished_reason": self.unfinished_reason,
            "saved_plan_path": self.saved_plan_path,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RunState":
        st = cls(
            run_id=d["run_id"],
            inputs=d["inputs"],
            max_steps=d["max_steps"],
        )
        for k in ("steps_used", "fee_spent", "hours_spent", "materials", "materials_source",
                  "script", "estimate", "current_tier", "tried_tiers", "fail_counts",
                  "plan_steps", "tool_call_log", "model_fail_streak", "finished",
                  "final_status", "unfinished_reason", "saved_plan_path"):
            if k in d:
                setattr(st, k, d[k])
        return st


@dataclass
class FinalResult:
    """交付结果：状态、任务计划、工具结果、费用合计、已保存方案/未完成原因。"""
    status: str
    run_id: str
    unfinished_reason: Optional[str] = None
    task_plan: list = field(default_factory=list)
    tool_results: dict = field(default_factory=dict)
    cost: dict = field(default_factory=dict)
    duration: dict = field(default_factory=dict)
    saved_plan: Optional[dict] = None
    steps_used: int = 0
    max_steps: int = 0
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "unfinished_reason": self.unfinished_reason,
            "run_id": self.run_id,
            "task_plan": self.task_plan,
            "tool_results": self.tool_results,
            "cost": self.cost,
            "duration": self.duration,
            "saved_plan": self.saved_plan,
            "steps_used": self.steps_used,
            "max_steps": self.max_steps,
            "notes": self.notes,
        }
