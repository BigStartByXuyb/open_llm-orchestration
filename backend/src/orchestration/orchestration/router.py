"""
能力路由器 — 为每个 SubTask 分配 provider_id 和 transformer_version
Capability router — assigns provider_id and transformer_version to each SubTask.

Layer 2: Static rules for Phase 1; scoring engine in Phase 2.
第 2 层：第一期使用静态规则；评分引擎在第二期。
"""

from __future__ import annotations

from orchestration.shared.enums import Capability, ProviderID
from orchestration.shared.types import SubTask, TaskPlan

# Default routing table: Capability → (provider_id, transformer_version)
# 默认路由表：能力类型 → (provider_id, transformer_version)
_DEFAULT_ROUTING_TABLE: dict[Capability, tuple[ProviderID, str]] = {
    Capability.TEXT: (ProviderID.ANTHROPIC, "v3"),
    Capability.CODE: (ProviderID.ANTHROPIC, "v3"),
    Capability.SEARCH: (ProviderID.SKILL, "v1"),
    Capability.IMAGE_GEN: (ProviderID.JIMENG, "v1"),
    Capability.VIDEO_GEN: (ProviderID.KLING, "v1"),
    Capability.ANALYSIS: (ProviderID.OPENAI, "v1"),
}

# Default skill_id assigned when a capability routes to ProviderID.SKILL
# but the subtask has no explicit skill_id set by the decomposer.
# 当能力路由到 ProviderID.SKILL 但分解器未设置 skill_id 时使用的默认 skill_id。
_DEFAULT_CAPABILITY_SKILL_ID: dict[Capability, str] = {
    Capability.SEARCH: "web_search",
}


class CapabilityRouter:
    """
    能力路由器 — 为每个 SubTask 分配 provider_id 和 transformer_version
    Capability router — assigns provider_id and transformer_version to each SubTask.

    Routing priority:
      1. If subtask.skill_id is in known_skill_ids → route to SKILL
      2. Look up capability in routing_table
      3. Fallback to ANTHROPIC/v3
    路由优先级：
      1. 若 subtask.skill_id 在已知 skill_ids 中 → 路由到 SKILL
      2. 在路由表中查找能力类型
      3. 回退到 ANTHROPIC/v3
    """

    def __init__(
        self,
        routing_table: dict[Capability, tuple[ProviderID, str]] | None = None,
        known_skill_ids: set[str] | None = None,
    ) -> None:
        self._table: dict[Capability, tuple[ProviderID, str]] = (
            routing_table if routing_table is not None else dict(_DEFAULT_ROUTING_TABLE)
        )
        self._known_skill_ids: set[str] = known_skill_ids or set()

    def route(self, subtask: SubTask) -> SubTask:
        """
        为子任务分配 provider_id 和 transformer_version
        Assign provider_id and transformer_version to a subtask.

        Returns a new SubTask with routing filled in; original is unchanged.
        返回填有路由信息的新 SubTask；原对象不变。
        """
        if subtask.skill_id and subtask.skill_id in self._known_skill_ids:
            provider_id = ProviderID.SKILL
            transformer_version = "v1"
            skill_id = subtask.skill_id
        else:
            provider_id, transformer_version = self._table.get(
                subtask.capability, (ProviderID.ANTHROPIC, "v3")
            )
            # If routed to SKILL but no explicit skill_id, assign the default
            # for this capability so the executor can look it up in the registry.
            # 若路由到 SKILL 但无显式 skill_id，使用能力默认值供 executor 查找。
            skill_id = subtask.skill_id or (
                _DEFAULT_CAPABILITY_SKILL_ID.get(subtask.capability, "")
                if provider_id == ProviderID.SKILL
                else subtask.skill_id
            )

        return SubTask(
            subtask_id=subtask.subtask_id,
            description=subtask.description,
            capability=subtask.capability,
            context_slice=subtask.context_slice,
            provider_id=provider_id,
            transformer_version=transformer_version,
            depends_on=subtask.depends_on,
            skill_id=skill_id,
            status=subtask.status,
            metadata=subtask.metadata,
        )

    def route_plan(self, plan: TaskPlan) -> TaskPlan:
        """
        为任务计划中的所有子任务分配路由 / Route all subtasks in a task plan.
        """
        routed = [self.route(st) for st in plan.subtasks]
        return TaskPlan(
            plan_id=plan.plan_id,
            subtasks=routed,
            summary=plan.summary,
            metadata=plan.metadata,
        )

    def update_routing(
        self, capability: Capability, provider_id: ProviderID, version: str
    ) -> None:
        """
        更新路由表中某能力的配置（用于租户级覆盖）
        Update routing for a capability (for per-tenant overrides).
        """
        self._table[capability] = (provider_id, version)

    def register_skill(self, skill_id: str) -> None:
        """
        注册已知 Skill ID / Register a known skill ID for SKILL routing.
        """
        self._known_skill_ids.add(skill_id)
