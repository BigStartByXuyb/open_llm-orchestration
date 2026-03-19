"""
transformer/canonical.py 单元测试
Unit tests for canonical message builder utilities.
"""

import pytest

from orchestration.shared.enums import Role
from orchestration.shared.types import ImagePart, TextPart, ToolCallPart, ToolResultPart
from orchestration.transformer.canonical import (
    assistant_message,
    assistant_tool_call_message,
    build_message,
    system_message,
    tool_result_message,
    total_char_count,
    truncate_to_char_limit,
    user_image_message,
    user_message,
)


class TestMessageBuilders:
    def test_system_message(self) -> None:
        msg = system_message("Be helpful")
        assert msg.role == Role.SYSTEM
        assert len(msg.content) == 1
        assert isinstance(msg.content[0], TextPart)
        assert msg.content[0].text == "Be helpful"
        assert msg.message_id != ""

    def test_user_message(self) -> None:
        msg = user_message("Hello")
        assert msg.role == Role.USER

    def test_assistant_message(self) -> None:
        msg = assistant_message("Hi there")
        assert msg.role == Role.ASSISTANT

    def test_user_image_with_caption(self) -> None:
        msg = user_image_message(url="https://x.com/img.jpg", caption="What is this?")
        assert msg.role == Role.USER
        assert len(msg.content) == 2
        assert isinstance(msg.content[0], TextPart)
        assert isinstance(msg.content[1], ImagePart)
        assert msg.content[0].text == "What is this?"
        assert msg.content[1].url == "https://x.com/img.jpg"

    def test_user_image_without_caption(self) -> None:
        msg = user_image_message(data="aGVsbG8=", media_type="image/png")
        assert len(msg.content) == 1
        assert isinstance(msg.content[0], ImagePart)

    def test_assistant_tool_call_message(self) -> None:
        msg = assistant_tool_call_message(
            tool_name="search",
            arguments={"query": "test"},
            tool_call_id="c1",
        )
        assert msg.role == Role.ASSISTANT
        tc_part = next(p for p in msg.content if isinstance(p, ToolCallPart))
        assert tc_part.tool_name == "search"
        assert tc_part.tool_call_id == "c1"
        assert tc_part.arguments == {"query": "test"}

    def test_assistant_tool_call_with_preceding_text(self) -> None:
        msg = assistant_tool_call_message(
            "search", {}, preceding_text="Let me search for that"
        )
        assert isinstance(msg.content[0], TextPart)
        assert isinstance(msg.content[1], ToolCallPart)

    def test_tool_result_message(self) -> None:
        msg = tool_result_message("c1", "Here are results")
        assert msg.role == Role.TOOL
        tr_part = msg.content[0]
        assert isinstance(tr_part, ToolResultPart)
        assert tr_part.tool_call_id == "c1"
        assert tr_part.content == "Here are results"
        assert not tr_part.is_error

    def test_tool_result_error(self) -> None:
        msg = tool_result_message("c1", "Failed", is_error=True)
        assert msg.content[0].is_error  # type: ignore[union-attr]

    def test_build_message_generic(self) -> None:
        parts = [TextPart(text="hello"), TextPart(text=" world")]
        msg = build_message(Role.USER, parts)
        assert len(msg.content) == 2

    def test_explicit_message_id(self) -> None:
        msg = user_message("x", message_id="custom-id")
        assert msg.message_id == "custom-id"

    def test_auto_generated_message_id(self) -> None:
        msg = user_message("x")
        assert len(msg.message_id) > 0


class TestTotalCharCount:
    def test_sum_of_char_counts(self) -> None:
        msgs = [
            user_message("Hello"),     # 5
            assistant_message("Hi"),   # 2
        ]
        assert total_char_count(msgs) == 7

    def test_empty_list(self) -> None:
        assert total_char_count([]) == 0


class TestTruncateToCharLimit:
    def test_within_limit_unchanged(self) -> None:
        msgs = [user_message("Hello"), assistant_message("Hi")]
        result = truncate_to_char_limit(msgs, limit=100)
        assert len(result) == 2

    def test_truncates_oldest_first(self) -> None:
        msgs = [
            user_message("A" * 100),   # 100 chars
            assistant_message("B" * 100),  # 100 chars
            user_message("C" * 100),   # 100 chars
        ]
        # Limit to 200 chars — should keep newest 2 messages
        result = truncate_to_char_limit(msgs, limit=200)
        assert len(result) == 2
        # The first (oldest) should be dropped
        assert any(isinstance(m.content[0], TextPart) and "B" in m.content[0].text for m in result)
        assert any(isinstance(m.content[0], TextPart) and "C" in m.content[0].text for m in result)

    def test_system_preserved_regardless_of_limit(self) -> None:
        msgs = [
            system_message("Important system prompt"),
            user_message("A" * 500),
            assistant_message("B" * 500),
        ]
        result = truncate_to_char_limit(msgs, limit=50, preserve_system=True)
        # System message should always be present
        assert any(m.role == Role.SYSTEM for m in result)

    def test_system_not_preserved_when_flag_false(self) -> None:
        msgs = [
            system_message("sys"),
            user_message("A" * 100),
        ]
        result = truncate_to_char_limit(msgs, limit=5, preserve_system=False)
        # With limit=5, nothing fits
        assert all(m.role != Role.SYSTEM for m in result) or len(result) == 0

    def test_empty_list_returns_empty(self) -> None:
        result = truncate_to_char_limit([], limit=100)
        assert result == []

    def test_exact_limit(self) -> None:
        msgs = [user_message("HELLO")]  # exactly 5 chars
        result = truncate_to_char_limit(msgs, limit=5)
        assert len(result) == 1
