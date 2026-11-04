"""模型层：统一的 decide(view) -> Action 接口。

- MockPlannerLLM：确定性规则策略，逐轮根据状态与最近观察决定下一步，
  仅用于离线验证流程与回归测试；不证明真实模型决策效果（边界见 docs）。
- OpenAICompatLLM：调用 OpenAI 兼容 API（如 CSU/DeepSeek），由模型每轮
  观察状态后自主选择动作或结束，构成"模型选择动作 → 执行工具 → 观察 →
  调整下一步"的 ReAct 决策循环。
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

from .schemas import Action

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)  # 项目 .env 优先于外层环境变量
except ImportError:  # pragma: no cover
    pass


class LLMError(Exception):
    pass


SYSTEM_PROMPT_TEMPLATE = """你是一个内容活动规划 Agent，帮助运营人员在预算与截止时间内产出一份内容活动方案。

可用工具（params 为 JSON Schema）：
{tool_specs}

每一轮你必须输出严格 JSON（不要输出 JSON 以外的任何文字）：
调用工具：{{"thought": "一句话决策依据", "action": "<工具名>", "params": {{...}}}}
结束任务：{{"thought": "一句话总结", "action": "finish", "final_status": "completed|incomplete", "reason": "结论或未完成原因（含缺口金额/小时数）"}}

决策规则：
1. theme/budget/deadline_hours 缺失时不要调用任何付费工具，直接 finish(incomplete) 并列出缺失字段。
2. 已成功产出的素材/脚本/估算结果不会丢失，不要重复执行已成功的步骤。
3. 若估算超出预算或工期：优先把脚本档位从 premium 降级为 standard 后重新生成、重新估算；若已无更低档位，则 finish(incomplete) 并明确给出缺口。
4. 工具失败可重试一次；素材检索持续失败时可改用 use_fallback_materials 兜底；仍失败则停止并说明原因。
5. save_plan 成功后立即 finish(completed)。
6. 有步数上限（见 steps_used/max_steps），请在步数耗尽前收敛。
"""


class BasePlannerLLM:
    def decide(self, view: dict) -> Action:
        raise NotImplementedError

    def name(self) -> str:
        return "base"


class MockPlannerLLM(BasePlannerLLM):
    """离线 Mock：确定性规则策略，逐轮决策，保证测试可离线复现。"""

    def name(self) -> str:
        return "mock-policy"

    def decide(self, view: dict) -> Action:
        inputs = view["inputs"]
        st = view["state"]
        fc = view["fail_counts"]
        missing = [k for k in ("theme", "budget", "deadline_hours") if inputs.get(k) in (None, "")]

        if missing:
            return Action(
                kind="finish", final_status="incomplete",
                thought="必填信息缺失，无法做成本/工期判断，直接结束",
                decision_basis="输入校验：缺少必填字段 → 不调用付费工具，直接结束",
                reason=f"输入信息不足：缺少 {', '.join(missing)}，无法制定可执行方案",
            )
        if st.get("saved_plan_path"):
            return Action(kind="finish", final_status="completed",
                          thought="方案已保存，任务完成",
                          decision_basis="save_plan 已成功 → 结束")

        # 1) 素材阶段
        if st["materials"] is None:
            n_fail = fc.get("search_materials", 0)
            if n_fail < 2:
                basis = ("尚无素材 → 调用 search_materials" if n_fail == 0
                         else "检索失败 1 次 → 重试 search_materials（最多重试 1 次）")
                return Action(kind="tool", tool="search_materials",
                              params={"theme": inputs.get("theme")}, thought=basis,
                              decision_basis=basis)
            if fc.get("use_fallback_materials", 0) == 0:
                return Action(kind="tool", tool="use_fallback_materials", params={},
                              thought="检索重试仍失败 → 改用内置模板素材兜底（替代方案）",
                              decision_basis="检索连续失败 → 切换兜底素材")
            return Action(kind="finish", final_status="incomplete",
                          thought="素材检索与兜底均失败，无法继续",
                          decision_basis="所有素材来源不可用 → 停止",
                          reason="素材检索与模板兜底均失败，无法生成脚本；已保留此前成功步骤的结果")

        # 2) 脚本阶段
        if st["script"] is None:
            if fc.get("generate_script", 0) >= 2:
                return Action(kind="finish", final_status="incomplete",
                              thought="脚本生成连续 2 次失败，停止",
                              decision_basis="generate_script 连续失败 ≥2 → 停止，保留素材结果",
                              reason="generate_script 连续 2 次失败，无法产出脚本；素材检索结果已保留")
            budget = float(inputs["budget"])
            tier = "premium" if budget >= 10 else "standard"
            tried = st.get("tried_tiers") or []
            if fc.get("generate_script", 0) >= 1 and tier in tried:
                tier = "standard" if tier == "premium" else "premium"
            return Action(kind="tool", tool="generate_script", params={"tier": tier},
                          thought=f"素材就绪 → 生成 {tier} 档脚本",
                          decision_basis=f"素材就绪 → generate_script(tier={tier}，预算 {budget})")

        # 3) 估算阶段
        if st["estimate"] is None:
            return Action(kind="tool", tool="estimate_cost", params={},
                          thought="脚本就绪 → 估算成本与工期",
                          decision_basis="脚本就绪 → estimate_cost")

        est = st["estimate"]
        if est["feasible"]:
            return Action(kind="tool", tool="save_plan",
                          params={"headline": f"「{inputs.get('theme')}」内容活动方案"},
                          thought="估算在预算与工期内 → 保存方案",
                          decision_basis="估算可行 → save_plan")

        # 4) 超限 → 重规划：降级档位
        if st.get("current_tier") == "premium" and "standard" not in (st.get("tried_tiers") or []):
            return Action(
                kind="tool", tool="generate_script", params={"tier": "standard"},
                thought=f"估算不可行（{_estimate_reason(est)}）→ 降级 standard 重生成脚本",
                decision_basis="估算超限 → 改选更低价位档位（重规划）",
            )
        return Action(
            kind="finish", final_status="incomplete",
            thought="已无更低价位档位，无法在预算/工期内完成",
            decision_basis="无替代档位 → 停止并给出缺口",
            reason="无可行方案：" + _gap_text(est) + "；已尝试档位：" + ",".join(st.get("tried_tiers") or []),
        )


class OpenAICompatLLM(BasePlannerLLM):
    """真实模型（OpenAI 兼容协议）。模型根据每轮观察自主决定下一步。"""

    def __init__(self, model: Optional[str] = None, temperature: float = 0.2):
        from openai import OpenAI
        self.model = model or os.environ.get("AGENT_MODEL", "DeepSeek")
        self.base_url = os.environ.get("OPENAI_BASE_URL", "")
        self.api_key = os.environ.get("OPENAI_API_KEY", "")
        if not self.base_url or not self.api_key:
            raise LLMError("缺少 OPENAI_BASE_URL / OPENAI_API_KEY（请配置 .env）")
        self.temperature = temperature
        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=120)

    def name(self) -> str:
        return f"openai-compatible:{self.model}"

    def decide(self, view: dict) -> Action:
        specs = json.dumps(view["tool_specs"], ensure_ascii=False, indent=2)
        system = SYSTEM_PROMPT_TEMPLATE.format(tool_specs=specs)
        user_payload = {
            "task": view["task"],
            "inputs": view["inputs"],
            "state": view["state"],
            "fail_counts": view["fail_counts"],
            "last_observation": view["last_observation"],
            "steps_used": view["steps_used"],
            "max_steps": view["max_steps"],
        }
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
                ],
                temperature=self.temperature,
                max_tokens=1500,
            )
        except LLMError:
            raise
        except Exception as exc:  # 网络/限流/鉴权等 API 异常统一转为 LLMError
            raise LLMError(f"模型 API 调用失败：{type(exc).__name__}: {exc}") from exc
        raw = resp.choices[0].message.content or ""
        data = _extract_json_dict(raw)
        action = _parse_action(data)
        if not action.decision_basis:
            action.decision_basis = action.thought
        return action


def _estimate_reason(est: dict) -> str:
    return _estimate_reason_str(est)


def _estimate_reason_str(est: dict) -> str:
    parts = []
    if not est["within_budget"]:
        parts.append(f"超预算 {est['budget_gap']}")
    if not est["within_deadline"]:
        parts.append(f"超工期 {est['deadline_gap_hours']}h")
    return "、".join(parts)


def _gap_text(est: dict) -> str:
    parts = []
    if not est["within_budget"]:
        parts.append(f"预算缺口 {est['budget_gap']}（需 {est['projected_total']}，仅有 {est['budget']}）")
    if not est["within_deadline"]:
        parts.append(f"工期缺口 {est['deadline_gap_hours']}h（需 {est['projected_hours']}h，截止 {est['deadline_hours']}h）")
    return "；".join(parts)


def _extract_json_dict(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise LLMError(f"模型输出中没有 JSON：{text[:200]}")
    return json.loads(text[start : end + 1])


def _parse_action(data: dict) -> Action:
    action = str(data.get("action", "")).strip()
    thought = str(data.get("thought", ""))
    if not action:
        raise LLMError(f"模型输出缺少 action 字段：{data}")
    if action in ("finish", "done", "stop"):
        status = data.get("final_status") or "incomplete"
        if status not in ("completed", "incomplete"):
            status = "incomplete"
        return Action(kind="finish", thought=thought, final_status=status,
                      reason=str(data.get("reason", "")),
                      decision_basis=thought or "模型决定结束")
    params = data.get("params") or {}
    if not isinstance(params, dict):
        params = {}
    return Action(kind="tool", tool=action, params=params, thought=thought, decision_basis=thought)


def make_llm(mode: str) -> BasePlannerLLM:
    if mode == "mock":
        return MockPlannerLLM()
    if mode == "real":
        return OpenAICompatLLM()
    raise ValueError(f"未知模型模式: {mode}")
