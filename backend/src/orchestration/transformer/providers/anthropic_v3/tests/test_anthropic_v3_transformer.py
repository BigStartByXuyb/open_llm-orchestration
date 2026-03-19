"""
AnthropicV3Transformer 单元测试
Unit tests for AnthropicV3Transformer — pure format conversion, no network calls.
"""

import pytest

from orchestration.shared.enums import ProviderID, Role
from orchestration.shared.errors import TransformError
from orchestration.shared.types import (
    CanonicalMessage,
    CanonicalTool,
    ImagePart,
    TextPart,
    ToolCallPart,
    ToolResultPart,
)
from orchestration.transformer.canonical import (
    assistant_message,
    assistant_tool_call_message,
    system_message,
    tool_result_message,
    user_image_message,
    user_message,
)
from orchestration.transformer.providers.anthropic_v3.transformer import AnthropicV3Transformer


@pytest.fixture()
def tr() -> AnthropicV3Transformer:
    return AnthropicV3Transformer(model="claude-sonnet-4-6", max_tokens=1024)


# ---------------------------------------------------------------------------
# transform() tests
# ---------------------------------------------------------------------------


class TestTransform:
    def test_simple_user_message(self, tr: AnthropicV3Transformer) -> None:
        msgs = [user_message("Hello")]
        payload = tr.transform(msgs)
        assert payload["model"] == "claude-sonnet-4-6"
        assert payload["max_tokens"] == 1024
        assert len(payload["messages"]) == 1
        assert payload["messages"][0]["role"] == "user"
        assert payload["messages"][0]["content"] == "Hello"

    def test_system_prompt_separated(self, tr: AnthropicV3Transformer) -> None:
        msgs = [system_message("You are helpful."), user_message("Hi")]
        payload = tr.transform(msgs)
        assert payload["system"] == "You are helpful."
        # System message should NOT appear in messages[]
        assert all(m["role"] != "system" for m in payload["messages"])
        assert len(payload["messages"]) == 1

    def test_multiple_system_messages_joined(self, tr: AnthropicV3Transformer) -> None:
        msgs = [
            system_message("Part 1."),
            system_message("Part 2."),
            user_message("Hi"),
        ]
        payload = tr.transform(msgs)
        assert payload["system"] == "Part 1.\n\nPart 2."

    def test_no_system_prompt_no_system_key(self, tr: AnthropicV3Transformer) -> None:
        msgs = [user_message("Hello")]
        payload = tr.transform(msgs)
        assert "system" not in payload

    def test_multi_turn_conversation(self, tr: AnthropicV3Transformer) -> None:
        msgs = [
            user_message("What is 2+2?"),
            assistant_message("4"),
            user_message("And 3+3?"),
        ]
        payload = tr.transform(msgs)
        assert len(payload["messages"]) == 3
        assert payload["messages"][0]["role"] == "user"
        assert payload["messages"][1]["role"] == "assistant"
        assert payload["messages"][2]["role"] == "user"

    def test_assistant_message_content(self, tr: AnthropicV3Transformer) -> None:
        msgs = [user_message("hi"), assistant_message("hello there")]
        payload = tr.transform(msgs)
        assert payload["messages"][1]["content"] == "hello there"

    def test_empty_messages_raises(self, tr: AnthropicV3Transformer) -> None:
        with pytest.raises(TransformError, match="at least one non-system message"):
            tr.transform([])

    def test_only_system_messages_raises(self, tr: AnthropicV3Transformer) -> None:
        with pytest.raises(TransformError):
            tr.transform([system_message("sys only")])

    def test_user_url_image(self, tr: AnthropicV3Transformer) -> None:
        msgs = [user_image_message(url="https://example.com/img.jpg", caption="What is this?")]
        payload = tr.transform(msgs)
        content = payload["messages"][0]["content"]
        assert isinstance(content, list)
        text_block = next(b for b in content if b.get("type") == "text")
        img_block = next(b for b in content if b.get("type") == "image")
        assert text_block["text"] == "What is this?"
        assert img_block["source"]["type"] == "url"
        assert img_block["source"]["url"] == "https://example.com/img.jpg"

    def test_user_base64_image(self, tr: AnthropicV3Transformer) -> None:
        msgs = [user_image_message(data="aGVsbG8=", media_type="image/png")]
        payload = tr.transform(msgs)
        content = payload["messages"][0]["content"]
        img_block = next(b for b in content if b.get("type") == "image")
        assert img_block["source"]["type"] == "base64"
        assert img_block["source"]["media_type"] == "image/png"
        assert img_block["source"]["data"] == "aGVsbG8="

    def test_tool_call_in_assistant_message(self, tr: AnthropicV3Transformer) -> None:
        msgs = [
            user_message("Search for cats"),
            assistant_tool_call_message(
                tool_name="web_search",
                arguments={"query": "cats"},
                tool_call_id="call_1",
            ),
        ]
        payload = tr.transform(msgs)
        asst_msg = payload["messages"][1]
        assert asst_msg["role"] == "assistant"
        content = asst_msg["content"]
        assert isinstance(content, list)
        tool_use = next(b for b in content if b.get("type") == "tool_use")
        assert tool_use["id"] == "call_1"
        assert tool_use["name"] == "web_search"
        assert tool_use["input"] == {"query": "cats"}

    def test_tool_result_as_user_message(self, tr: AnthropicV3Transformer) -> None:
        msgs = [
            user_message("Search"),
            assistant_tool_call_message("search", {}, tool_call_id="c1"),
            tool_result_message("c1", "Results here"),
        ]
        payload = tr.transform(msgs)
        # Tool result should be converted to a user message
        last_msg = payload["messages"][-1]
        assert last_msg["role"] == "user"
        content = last_msg["content"]
        tool_result_block = next(b for b in content if b.get("type") == "tool_result")
        assert tool_result_block["tool_use_id"] == "c1"
        assert tool_result_block["content"] == "Results here"


# ---------------------------------------------------------------------------
# transform_tools() tests
# ---------------------------------------------------------------------------


class TestTransformTools:
    def test_basic_tool(self, tr: AnthropicV3Transformer) -> None:
        tool = CanonicalTool(
            name="web_search",
            description="Search the web",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        )
        result = tr.transform_tools([tool])
        assert len(result) == 1
        assert result[0]["name"] == "web_search"
        assert result[0]["description"] == "Search the web"
        assert "input_schema" in result[0]

    def test_empty_tools(self, tr: AnthropicV3Transformer) -> None:
        assert tr.transform_tools([]) == []

    def test_multiple_tools(self, tr: AnthropicV3Transformer) -> None:
        tools = [
            CanonicalTool(name="t1", description="d1", input_schema={}),
            CanonicalTool(name="t2", description="d2", input_schema={}),
        ]
        result = tr.transform_tools(tools)
        assert len(result) == 2
        names = [t["name"] for t in result]
        assert "t1" in names and "t2" in names


# ---------------------------------------------------------------------------
# parse_response() tests
# ---------------------------------------------------------------------------


class TestParseResponse:
    def test_simple_text_response(self, tr: AnthropicV3Transformer) -> None:
        raw = {
            "id": "msg_1",
            "content": [{"type": "text", "text": "Hello world"}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        result = tr.parse_response(raw)
        assert result.content == "Hello world"
        assert result.tokens_used == 15
        assert result.provider_id == ProviderID.ANTHROPIC
        assert result.transformer_version == "v3"

    def test_multiple_text_blocks(self, tr: AnthropicV3Transformer) -> None:
        raw = {
            "content": [
                {"type": "text", "text": "Part 1"},
                {"type": "text", "text": "Part 2"},
            ],
            "usage": {"input_tokens": 5, "output_tokens": 5},
        }
        result = tr.parse_response(raw)
        assert result.content == "Part 1Part 2"

    def test_tool_use_populates_tool_calls(self, tr: AnthropicV3Transformer) -> None:
        raw = {
            "content": [
                {"type": "text", "text": "Let me search"},
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "web_search",
                    "input": {"query": "cats"},
                },
            ],
            "usage": {"input_tokens": 10, "output_tokens": 20},
        }
        result = tr.parse_response(raw)
        # Text content preserved; tool_use goes into tool_calls not content
        assert result.content == "Let me search"
        assert result.tokens_used == 30
        assert len(result.tool_calls) == 1
        tc = result.tool_calls[0]
        assert tc.tool_call_id == "toolu_1"
        assert tc.tool_name == "web_search"
        assert tc.arguments == {"query": "cats"}

    def test_multiple_tool_calls(self, tr: AnthropicV3Transformer) -> None:
        raw = {
            "content": [
                {"type": "tool_use", "id": "c1", "name": "search", "input": {"q": "x"}},
                {"type": "tool_use", "id": "c2", "name": "code_exec", "input": {"code": "1+1"}},
            ],
            "usage": {"input_tokens": 5, "output_tokens": 10},
        }
        result = tr.parse_response(raw)
        assert result.content == ""
        assert len(result.tool_calls) == 2
        names = [tc.tool_name for tc in result.tool_calls]
        assert "search" in names and "code_exec" in names

    def test_no_tool_calls_returns_empty_list(self, tr: AnthropicV3Transformer) -> None:
        raw = {"content": [{"type": "text", "text": "plain text"}], "usage": {}}
        result = tr.parse_response(raw)
        assert result.tool_calls == []

    def test_empty_content_blocks(self, tr: AnthropicV3Transformer) -> None:
        raw = {"content": [], "usage": {"input_tokens": 5, "output_tokens": 0}}
        result = tr.parse_response(raw)
        assert result.content == ""

    def test_missing_usage_defaults_to_zero(self, tr: AnthropicV3Transformer) -> None:
        raw = {"content": [{"type": "text", "text": "hi"}]}
        result = tr.parse_response(raw)
        assert result.tokens_used == 0

    def test_raw_response_preserved(self, tr: AnthropicV3Transformer) -> None:
        raw = {"content": [{"type": "text", "text": "x"}], "model": "claude-sonnet-4-6"}
        result = tr.parse_response(raw)
        assert result.raw_response == raw

    def test_invalid_response_raises_transform_error(self, tr: AnthropicV3Transformer) -> None:
        with pytest.raises(TransformError):
            tr.parse_response({"content": None})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Provider ID and version
# ---------------------------------------------------------------------------


class TestProviderMetadata:
    def test_provider_id(self, tr: AnthropicV3Transformer) -> None:
        assert tr.provider_id == ProviderID.ANTHROPIC

    def test_api_version(self, tr: AnthropicV3Transformer) -> None:
        assert tr.api_version == "v3"

    def test_repr(self, tr: AnthropicV3Transformer) -> None:
        r = repr(tr)
        assert "anthropic" in r
        assert "v3" in r
