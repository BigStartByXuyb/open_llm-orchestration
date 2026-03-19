"""
序列化/反序列化单元测试
Unit tests for CanonicalMessage serialization/deserialization.
"""

from __future__ import annotations

import pytest

from orchestration.shared.enums import Role
from orchestration.shared.types import (
    CanonicalMessage,
    ImagePart,
    TextPart,
    ToolCallPart,
    ToolResultPart,
)
from orchestration.storage.postgres.serializer import (
    deserialize_messages,
    serialize_messages,
)


def make_message(role: Role, *parts: object) -> CanonicalMessage:
    return CanonicalMessage(role=role, content=list(parts))  # type: ignore[arg-type]


class TestRoundTrip:
    def test_text_part_round_trip(self) -> None:
        msg = make_message(Role.USER, TextPart(text="Hello, world!"))
        [restored] = deserialize_messages(serialize_messages([msg]))
        assert restored.role == Role.USER
        assert len(restored.content) == 1
        assert isinstance(restored.content[0], TextPart)
        assert restored.content[0].text == "Hello, world!"

    def test_image_part_round_trip(self) -> None:
        msg = make_message(
            Role.USER,
            ImagePart(url="https://example.com/img.png", media_type="image/png"),
        )
        [restored] = deserialize_messages(serialize_messages([msg]))
        part = restored.content[0]
        assert isinstance(part, ImagePart)
        assert part.url == "https://example.com/img.png"
        assert part.media_type == "image/png"

    def test_tool_call_part_round_trip(self) -> None:
        msg = make_message(
            Role.ASSISTANT,
            ToolCallPart(
                tool_call_id="call_1",
                tool_name="web_search",
                arguments={"query": "LLM"},
            ),
        )
        [restored] = deserialize_messages(serialize_messages([msg]))
        part = restored.content[0]
        assert isinstance(part, ToolCallPart)
        assert part.tool_call_id == "call_1"
        assert part.tool_name == "web_search"
        assert part.arguments == {"query": "LLM"}

    def test_tool_result_part_round_trip(self) -> None:
        msg = make_message(
            Role.TOOL,
            ToolResultPart(tool_call_id="call_1", content="result text", is_error=False),
        )
        [restored] = deserialize_messages(serialize_messages([msg]))
        part = restored.content[0]
        assert isinstance(part, ToolResultPart)
        assert part.content == "result text"
        assert part.is_error is False

    def test_multiple_messages_and_parts(self) -> None:
        msgs = [
            make_message(Role.SYSTEM, TextPart(text="System prompt")),
            make_message(Role.USER, TextPart(text="User input")),
            make_message(
                Role.ASSISTANT,
                TextPart(text="Thinking..."),
                ToolCallPart(tool_call_id="c1", tool_name="search", arguments={}),
            ),
        ]
        restored = deserialize_messages(serialize_messages(msgs))
        assert len(restored) == 3
        assert restored[2].role == Role.ASSISTANT
        assert len(restored[2].content) == 2

    def test_metadata_preserved(self) -> None:
        msg = CanonicalMessage(
            role=Role.USER,
            content=[TextPart(text="hi")],
            message_id="msg-123",
            metadata={"source": "test"},
        )
        [restored] = deserialize_messages(serialize_messages([msg]))
        assert restored.message_id == "msg-123"
        assert restored.metadata == {"source": "test"}

    def test_unknown_content_part_skipped(self) -> None:
        """未知 type 的 ContentPart 在反序列化时应被跳过（CanonicalMessage 演进规则）。"""
        raw = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "hello"},
                    {"type": "future_unknown_type", "data": "..."},
                ],
                "message_id": "",
                "schema_version": 1,
                "metadata": {},
            }
        ]
        [msg] = deserialize_messages(raw)
        assert len(msg.content) == 1
        assert isinstance(msg.content[0], TextPart)

    def test_empty_messages_list(self) -> None:
        assert deserialize_messages(serialize_messages([])) == []
