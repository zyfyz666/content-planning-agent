"""业务工具集：素材检索、脚本生成、成本估算、兜底素材、方案保存。

约定：
- 每个工具的签名统一为 run(params, state, env) -> Observation；
- 费用/工时只在成功路径上记入 state（失败调用不计费，但计入步数）；
- env 提供合成数据（素材库、价格表）与故障注入器，便于测试注入失败。
"""
from __future__ import annotations

import json
import os
from typing import Callable, Optional

from .schemas import Observation, RunState


class ToolError(Exception):
    pass


class FaultInjector:
    """按 `工具名:次数` 注入失败；次数 -1 表示始终失败。"""

    def __init__(self, spec: Optional[str] = None):
        self.remaining: dict[str, int] = {}
        if spec:
            for part in spec.split(","):
                part = part.strip()
                if not part or ":" not in part:
                    continue
                name, cnt = part.split(":", 1)
                self.remaining[name.strip()] = int(cnt)

    def should_fail(self, tool: str) -> bool:
        n = self.remaining.get(tool)
        if n is None:
            return False
        if n == -1:
            return True
        if n > 0:
            self.remaining[tool] = n - 1
            return True
        return False


class AgentEnv:
    """工具运行环境：数据文件、注入器、运行目录。"""

    def __init__(self, data_dir: str, run_dir_fn, injector: Optional[FaultInjector] = None):
        self.injector = injector or FaultInjector()
        self.run_dir_fn = run_dir_fn
        with open(os.path.join(data_dir, "tool_costs.json"), encoding="utf-8") as f:
            self.tool_costs = json.load(f)
        with open(os.path.join(data_dir, "materials.json"), encoding="utf-8") as f:
            self.materials_db = json.load(f)
        with open(os.path.join(data_dir, "plan_pricing.json"), encoding="utf-8") as f:
            self.pricing = json.load(f)

    def tool_cost(self, tool: str) -> float:
        return float(self.tool_costs["tools"][tool]["cost"])

    def tool_hours(self, tool: str, tier: str = "standard") -> float:
        d = self.tool_costs["tools"][tool]["duration_hours"]
        return float(d[tier] if isinstance(d, dict) else d)

    def charge(self, tool: str, state: RunState, tier: str = "standard") -> None:
        fee = self.tool_cost(tool)
        state.fee_spent = round(state.fee_spent + fee, 2)
        state.hours_spent = round(state.hours_spent + self.tool_hours(tool, tier), 2)


class Tool:
    name: str = ""
    description: str = ""
    params_schema: dict = {}

    def run(self, params: dict, state: RunState, env: AgentEnv) -> Observation:
        raise NotImplementedError


class ToolRegistry:
    def __init__(self, tools: list[Tool]):
        self._tools: dict[str, Tool] = {t.name: t for t in tools}

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def specs(self) -> list[dict]:
        return [
            {"name": t.name, "description": t.description, "params": t.params_schema}
            for t in self._tools.values()
        ]


class SearchMaterialsTool(Tool):
    name = "search_materials"
    description = "按主题检索素材库，返回最相关的素材列表（费用0.5，耗时1h；失败可重试）"
    params_schema = {
        "type": "object",
        "properties": {"theme": {"type": "string", "description": "活动主题关键词"}},
        "required": ["theme"],
    }

    def run(self, params, state, env) -> Observation:
        if env.injector.should_fail(self.name):
            raise ToolError("素材库服务超时（模拟故障）")
        env.charge(self.name, state)
        theme = str(params.get("theme") or state.inputs.get("theme") or "")
        scored = []
        for m in env.materials_db["materials"]:
            score = sum(1 for tag in m["tags"] if tag in theme)
            if score > 0:
                scored.append(dict(m, relevance=round(score, 1)))
        scored.sort(key=lambda x: -x["relevance"])
        picked = scored[:3]
        if not picked:
            picked = [dict(m) for m in env.materials_db["materials"] if "通用" in m["tags"]][:3]
        state.materials = picked
        state.materials_source = "search"
        titles = "; ".join(f"{m['id']} {m['title']}" for m in picked)
        return Observation(ok=True, summary=f"检索到 {len(picked)} 条素材：{titles}",
                           data={"materials": picked})


class FallbackMaterialsTool(Tool):
    name = "use_fallback_materials"
    description = "素材检索失败时的替代方案：改用内置通用模板素材（免费，耗时0.2h）"
    params_schema = {"type": "object", "properties": {}}

    def run(self, params, state, env) -> Observation:
        if env.injector.should_fail(self.name):
            raise ToolError("模板素材服务不可用（模拟故障）")
        fallback = [dict(m) for m in env.materials_db["fallback_materials"]]
        state.materials = fallback
        state.materials_source = "fallback"
        return Observation(ok=True, summary=f"改用 {len(fallback)} 条内置通用模板素材（F001-F003）",
                           data={"materials": fallback})


class GenerateScriptTool(Tool):
    name = "generate_script"
    description = (
        "基于已检索素材生成指定档位(tier)的活动脚本；"
        "premium 档制作费 12 单位/制作 6h，standard 档制作费 8 单位/制作 4h；脚本生成本身计费 0.5"
    )
    params_schema = {
        "type": "object",
        "properties": {"tier": {"type": "string", "enum": ["premium", "standard"],
                                "description": "premium=完整方案, standard=轻量方案"}},
        "required": ["tier"],
    }

    def run(self, params, state, env) -> Observation:
        if env.injector.should_fail(self.name):
            raise ToolError(f"脚本生成服务超时（模拟故障，tier={params.get('tier')}）")
        tier = str(params.get("tier", "standard"))
        if tier not in env.pricing["tiers"]:
            return Observation(ok=False, summary=f"未知档位 {tier}", data={}, error="unknown_tier")
        env.charge(self.name, state, tier=tier)
        pricing = env.pricing["tiers"][tier]
        mats = state.materials or []
        script = {
            "tier": tier,
            "theme": state.inputs.get("theme"),
            "hook": f"【{state.inputs.get('theme')}】3秒抓眼开场",
            "beats": ["痛点引入", "产品卖点展示", "行动号召"],
            "cta": "点击左下角立即参与",
            "based_on_materials": [m["id"] for m in mats],
            "uses_fallback": state.materials_source == "fallback",
        }
        state.script = script
        state.current_tier = tier
        state.estimate = None  # 脚本变更后，旧估算失效（步骤依赖：estimate 依赖 script）
        if tier not in state.tried_tiers:
            state.tried_tiers.append(tier)
        return Observation(
            ok=True,
            summary=f"已生成 {tier} 档脚本（素材{len(mats)}条）；该档位制作费 {pricing['production_cost']}、制作 {pricing['production_hours']}h",
            data={"script": script},
        )


class EstimateCostTool(Tool):
    name = "estimate_cost"
    description = "估算当前脚本档位的总费用与总工期，并判断预算/截止时间可行性（免费）"
    params_schema = {"type": "object", "properties": {}}

    def run(self, params, state, env) -> Observation:
        if env.injector.should_fail(self.name):
            raise ToolError("定价服务不可用（模拟故障）")
        if not state.script:
            return Observation(ok=False, summary="尚无脚本，请先调用 generate_script", data={}, error="no_script")
        tier = state.script["tier"]
        pricing = env.pricing["tiers"][tier]
        env.charge(self.name, state)
        budget = float(state.inputs["budget"])
        deadline = float(state.inputs["deadline_hours"])
        projected_total = round(state.fee_spent + pricing["production_cost"], 2)
        projected_hours = round(state.hours_spent + pricing["production_hours"] + 0.2, 2)
        est = {
            "tier": tier,
            "tool_fees_so_far": state.fee_spent,
            "production_cost": pricing["production_cost"],
            "projected_total": projected_total,
            "budget": budget,
            "within_budget": projected_total <= budget,
            "budget_gap": round(max(0.0, projected_total - budget), 2),
            "projected_hours": projected_hours,
            "deadline_hours": deadline,
            "within_deadline": projected_hours <= deadline,
            "deadline_gap_hours": round(max(0.0, projected_hours - deadline), 2),
        }
        est["feasible"] = est["within_budget"] and est["within_deadline"]
        state.estimate = est
        problems = []
        if not est["within_budget"]:
            problems.append(f"超预算 {est['budget_gap']}")
        if not est["within_deadline"]:
            problems.append(f"超工期 {est['deadline_gap_hours']}h")
        summary = (f"{tier} 方案估算：总费用 {projected_total}/{budget}，总工期 {projected_hours}h/{deadline}h"
                   + ("" if est["feasible"] else "；不可行（" + "、".join(problems) + "）"))
        return Observation(ok=True, summary=summary, data={"estimate": est})


class SavePlanTool(Tool):
    name = "save_plan"
    description = ("保存最终活动方案（免费）；硬校验：总费用超预算或总工期超截止时间则拒绝保存并返回原因")
    params_schema = {
        "type": "object",
        "properties": {"headline": {"type": "string", "description": "方案标题（可选）"}},
    }

    def __init__(self, run_dir_fn):
        self._run_dir_fn = run_dir_fn

    def run(self, params, state, env) -> Observation:
        if env.injector.should_fail(self.name):
            raise ToolError("存储服务不可用（模拟故障）")
        if not state.script or not state.estimate:
            return Observation(ok=False, summary="缺少脚本或估算结果，无法保存", data={}, error="missing_prereq")
        est = state.estimate
        if not est["feasible"]:
            return Observation(
                ok=False,
                summary="保存被拒绝：方案超出预算或截止时间（硬校验）",
                data={"estimate": est},
                error="budget_deadline_guard",
            )
        run_dir = self._run_dir_fn()
        os.makedirs(run_dir, exist_ok=True)
        plan = {
            "plan_id": f"plan-{state.run_id}",
            "title": params.get("headline") or f"「{state.inputs.get('theme')}」内容活动方案",
            "tier": est["tier"],
            "includes": env.pricing["tiers"][est["tier"]]["includes"],
            "theme": state.inputs.get("theme"),
            "budget": est["budget"],
            "deadline_hours": est["deadline_hours"],
            "cost": {"tool_fees": est["tool_fees_so_far"], "production": est["production_cost"],
                     "total": est["projected_total"]},
            "duration_hours": est["projected_hours"],
            "script": state.script,
            "materials": state.materials,
        }
        path_json = os.path.join(run_dir, "plan.json")
        with open(path_json, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)
        state.saved_plan_path = path_json
        return Observation(
            ok=True,
            summary=f"方案已保存：{path_json}（总费用 {est['projected_total']}/{est['budget']}，总工期 {est['projected_hours']}h）",
            data={"plan_path": path_json, "plan_id": plan["plan_id"]},
        )
