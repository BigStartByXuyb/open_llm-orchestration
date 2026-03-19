"""
CapabilityRouter 单元测试
Unit tests for CapabilityRouter — pure logic, no mocking needed.
"""

from __future__ import annotations

import pytest

from orchestration.shared.enums import Capability, ProviderID, TaskStatus
from orchestration.shared.types import SubTask, TaskPlan
from orchestration.orchestration.router import CapabilityRouter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _subtask(
    capability: Capability,
    subtask_id: str = "st_1",
    skill_id: str = "",
    depends_on: list[str] | None = None,
) -> SubTask:
    return SubTask(
        subtask_id=subtask_id,
        description="test",
        capability=capability,
        context_slice=[],
        depends_on=depends_on or [],
        skill_id=skill_id,
        status=TaskStatus.PENDING,
    )


# ---------------------------------------------------------------------------
# Default routing rules
# ---------------------------------------------------------------------------


class TestDefaultRouting:
    def test_text_routes_to_anthropic_v3(self) -> None:
        router = CapabilityRouter()
        routed = router.route(_subtask(Capability.TEXT))
        assert routed.provider_id == ProviderID.ANTHROPIC
        assert routed.transformer_version == "v3"

    def test_code_routes_to_anthropic_v3(self) -> None:
        router = CapabilityRouter()
        routed = router.route(_subtask(Capability.CODE))
        assert routed.provider_id == ProviderID.ANTHROPIC
        assert routed.transformer_version == "v3"

    def test_search_routes_to_skill(self) -> None:
        router = CapabilityRouter()
        routed = router.route(_subtask(Capability.SEARCH))
        assert routed.provider_id == ProviderID.SKILL

    def test_image_gen_routes_to_jimeng(self) -> None:
        router = CapabilityRouter()
        routed = router.route(_subtask(Capability.IMAGE_GEN))
        assert routed.provider_id == ProviderID.JIMENG
        assert routed.transformer_version == "v1"

    def test_video_gen_routes_to_kling(self) -> None:
        router = CapabilityRouter()
        routed = router.route(_subtask(Capability.VIDEO_GEN))
        assert routed.provider_id == ProviderID.KLING
        assert routed.transformer_version == "v1"

    def test_analysis_routes_to_openai(self) -> None:
        router = CapabilityRouter()
        routed = router.route(_subtask(Capability.ANALYSIS))
        assert routed.provider_id == ProviderID.OPENAI
        assert routed.transformer_version == "v1"


# ---------------------------------------------------------------------------
# Skill routing
# ---------------------------------------------------------------------------


class TestSkillRouting:
    def test_registered_skill_routes_to_skill_provider(self) -> None:
        router = CapabilityRouter(known_skill_ids={"web_search"})
        routed = router.route(_subtask(Capability.TEXT, skill_id="web_search"))
        assert routed.provider_id == ProviderID.SKILL
        assert routed.transformer_version == "v1"

    def test_unregistered_skill_id_falls_through_to_capability(self) -> None:
        router = CapabilityRouter()  # no registered skills
        routed = router.route(_subtask(Capability.TEXT, skill_id="unknown_skill"))
        # Falls through to capability routing for TEXT → ANTHROPIC
        assert routed.provider_id == ProviderID.ANTHROPIC

    def test_empty_skill_id_not_treated_as_skill(self) -> None:
        router = CapabilityRouter(known_skill_ids={"web_search"})
        routed = router.route(_subtask(Capability.IMAGE_GEN, skill_id=""))
        assert routed.provider_id == ProviderID.JIMENG

    def test_register_skill_adds_to_known_ids(self) -> None:
        router = CapabilityRouter()
        router.register_skill("my_skill")
        routed = router.route(_subtask(Capability.ANALYSIS, skill_id="my_skill"))
        assert routed.provider_id == ProviderID.SKILL


# ---------------------------------------------------------------------------
# Subtask fields preserved
# ---------------------------------------------------------------------------


class TestFieldPreservation:
    def test_route_preserves_all_subtask_fields(self) -> None:
        router = CapabilityRouter()
        original = _subtask(
            Capability.TEXT, subtask_id="st_42", depends_on=["st_1"]
        )
        original = SubTask(
            subtask_id="st_42",
            description="detailed description",
            capability=Capability.TEXT,
            context_slice=[],
            depends_on=["st_1"],
            skill_id="",
            status=TaskStatus.RUNNING,
            metadata={"key": "val"},
        )
        routed = router.route(original)
        assert routed.subtask_id == "st_42"
        assert routed.description == "detailed description"
        assert routed.depends_on == ["st_1"]
        assert routed.status == TaskStatus.RUNNING
        assert routed.metadata == {"key": "val"}


# ---------------------------------------------------------------------------
# route_plan
# ---------------------------------------------------------------------------


class TestRoutePlan:
    def test_route_plan_routes_all_subtasks(self) -> None:
        router = CapabilityRouter()
        plan = TaskPlan(
            plan_id="p1",
            subtasks=[
                _subtask(Capability.TEXT, "st_1"),
                _subtask(Capability.IMAGE_GEN, "st_2"),
            ],
            summary="test plan",
        )
        routed = router.route_plan(plan)
        assert routed.plan_id == "p1"
        assert routed.summary == "test plan"
        assert routed.subtasks[0].provider_id == ProviderID.ANTHROPIC
        assert routed.subtasks[1].provider_id == ProviderID.JIMENG

    def test_route_plan_preserves_metadata(self) -> None:
        router = CapabilityRouter()
        plan = TaskPlan(
            plan_id="p2",
            subtasks=[_subtask(Capability.CODE)],
            summary="",
            metadata={"origin": "test"},
        )
        routed = router.route_plan(plan)
        assert routed.metadata == {"origin": "test"}


# ---------------------------------------------------------------------------
# update_routing
# ---------------------------------------------------------------------------


class TestUpdateRouting:
    def test_update_routing_overrides_default(self) -> None:
        router = CapabilityRouter()
        router.update_routing(Capability.TEXT, ProviderID.DEEPSEEK, "v1")
        routed = router.route(_subtask(Capability.TEXT))
        assert routed.provider_id == ProviderID.DEEPSEEK
        assert routed.transformer_version == "v1"

    def test_update_routing_does_not_affect_other_capabilities(self) -> None:
        router = CapabilityRouter()
        router.update_routing(Capability.TEXT, ProviderID.DEEPSEEK, "v1")
        routed_code = router.route(_subtask(Capability.CODE))
        assert routed_code.provider_id == ProviderID.ANTHROPIC

    def test_custom_routing_table(self) -> None:
        custom = {
            Capability.TEXT: (ProviderID.GEMINI, "v1"),
        }
        router = CapabilityRouter(routing_table=custom)
        routed = router.route(_subtask(Capability.TEXT))
        assert routed.provider_id == ProviderID.GEMINI

    def test_fallback_to_anthropic_for_unknown_capability(self) -> None:
        # Use empty routing table to force fallback
        router = CapabilityRouter(routing_table={})
        routed = router.route(_subtask(Capability.TEXT))
        assert routed.provider_id == ProviderID.ANTHROPIC
        assert routed.transformer_version == "v3"
