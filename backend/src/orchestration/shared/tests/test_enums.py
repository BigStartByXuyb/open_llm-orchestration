"""
shared/enums.py 单元测试
Unit tests for shared/enums.py
"""

import pytest

from orchestration.shared.enums import (
    Capability,
    ContentPartType,
    ProviderID,
    Role,
    TaskStatus,
)


class TestRole:
    def test_values(self) -> None:
        assert Role.SYSTEM == "system"
        assert Role.USER == "user"
        assert Role.ASSISTANT == "assistant"
        assert Role.TOOL == "tool"

    def test_is_str(self) -> None:
        # StrEnum values should be usable as strings directly
        assert f"{Role.USER}" == "user"

    def test_membership(self) -> None:
        assert "system" in Role._value2member_map_
        assert "unknown" not in Role._value2member_map_


class TestProviderID:
    def test_all_providers_present(self) -> None:
        expected = {"anthropic", "openai", "deepseek", "gemini", "jimeng", "kling", "skill"}
        actual = {p.value for p in ProviderID}
        assert actual == expected

    def test_skill_pseudo_provider(self) -> None:
        assert ProviderID.SKILL == "skill"

    def test_str_equality(self) -> None:
        assert ProviderID.ANTHROPIC == "anthropic"


class TestCapability:
    def test_all_capabilities(self) -> None:
        values = {c.value for c in Capability}
        assert "text" in values
        assert "image_gen" in values
        assert "video_gen" in values
        assert "code" in values
        assert "search" in values
        assert "analysis" in values


class TestTaskStatus:
    def test_terminal_states(self) -> None:
        terminal = {TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.CANCELLED}
        assert TaskStatus.PENDING not in terminal
        assert TaskStatus.RUNNING not in terminal

    def test_transition_values(self) -> None:
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.RUNNING == "running"
        assert TaskStatus.DONE == "done"
        assert TaskStatus.FAILED == "failed"
        assert TaskStatus.CANCELLED == "cancelled"


class TestContentPartType:
    def test_all_types(self) -> None:
        values = {t.value for t in ContentPartType}
        assert values == {"text", "image", "tool_call", "tool_result"}
