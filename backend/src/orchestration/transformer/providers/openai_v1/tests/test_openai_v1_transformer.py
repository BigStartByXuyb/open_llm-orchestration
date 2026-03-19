"""
OpenAIV1Transformer 单元测试
Unit tests for OpenAIV1Transformer — pure format conversion, no network calls.
"""

import json

import pytest

from orchestration.shared.enums import ProviderID
from orchestration.shared.errors import TransformError
from orchestration.shared.types import CanonicalTool
from orchestration.transformer.canonical import (
    assistant_message,
    assistant_tool_call_message,
    system_message,
    tool_result_message,
    user_image_message,
    user_message,
)
from orchestration.transformer.providers.openai_v1.transformer import OpenAIV1Transformer


@pytest.fixture()
def tr() -> OpenAIV1Transformer:
    return OpenAIV1Transformer(model="gpt-4o", max_tokens=2048)


class TestTransform:
    def test_simple_user_message(self, tr: OpenAIV1Transformer) -> None:
        payload = tr.transform([user_message("Hello")])
        assert payload["model"] == "gpt-4o"
        assert payload["max_tokens"] == 2048
        msgs = payload["messages"]
        assert len(msgs) == 1
        assert msgs[0] == {"role": "user", "content": "Hello"}

    def test_system_message_in_messages_array(self, tr: OpenAIV1Transformer) -> None:
        payload = tr.transform([system_message("Be helpful"), user_message("Hi")])
        msgs = payload["messages"]
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == "Be helpful"

    def test_multi_turn(self, tr: OpenAIV1Transformer) -> None:
        msgs = [
            system_message("sys"),
            user_message("q1"),
            assistant_message("a1"),
            user_message("q2"),
        ]
        payload = tr.transform(msgs)
        assert len(payload["messages"]) == 4
        roles = [m["role"] for m in payload["messages"]]
        assert roles == ["system", "user", "assistant", "user"]

    def test_empty_messages_raises(self, tr: OpenAIV1Transformer) -> None:
        with pytest.raises(TransformError):
            tr.transform([])

    def test_url_image_in_user_message(self, tr: OpenAIV1Transformer) -> None:
        msgs = [user_image_message(url="https://x.com/img.jpg", caption="Describe")]
        payload = tr.transform(msgs)
        content = payload["messages"][0]["content"]
        assert isinstance(content, list)
        text_part = next(p for p in content if p.get("type") == "text")
        img_part = next(p for p in content if p.get("type") == "image_url")
        assert text_part["text"] == "Describe"
        assert img_part["image_url"]["url"] == "https://x.com/img.jpg"

    def test_base64_image_becomes_data_uri(self, tr: OpenAIV1Transformer) -> None:
        msgs = [user_image_message(data="aGVsbG8=", media_type="image/png")]
        payload = tr.transform(msgs)
        content = payload["messages"][0]["content"]
        img_part = next(p for p in content if p.get("type") == "image_url")
        assert img_part["image_url"]["url"].startswith("data:image/png;base64,")

    def test_assistant_tool_call(self, tr: OpenAIV1Transformer) -> None:
        msgs = [
            user_message("Search"),
            assistant_tool_call_message("web_search", {"query": "cats"}, tool_call_id="c1"),
        ]
        payload = tr.transform(msgs)
        asst = payload["messages"][1]
        assert asst["role"] == "assistant"
        assert "tool_calls" in asst
        tc = asst["tool_calls"][0]
        assert tc["id"] == "c1"
        assert tc["type"] == "function"
        assert tc["function"]["name"] == "web_search"
        args = json.loads(tc["function"]["arguments"])
        assert args == {"query": "cats"}

    def test_tool_result_message(self, tr: OpenAIV1Transformer) -> None:
        msgs = [
            user_message("Search"),
            assistant_tool_call_message("search", {}, tool_call_id="c1"),
            tool_result_message("c1", "Results here"),
        ]
        payload = tr.transform(msgs)
        # Tool result becomes a separate message with role="tool"
        tool_msg = next(m for m in payload["messages"] if m.get("role") == "tool")
        assert tool_msg["tool_call_id"] == "c1"
        assert tool_msg["content"] == "Results here"


class TestTransformTools:
    def test_basic_tool(self, tr: OpenAIV1Transformer) -> None:
        tool = CanonicalTool(
            name="code_exec",
            description="Execute code",
            input_schema={"type": "object", "properties": {"code": {"type": "string"}}},
        )
        result = tr.transform_tools([tool])
        assert len(result) == 1
        assert result[0]["type"] == "function"
        func = result[0]["function"]
        assert func["name"] == "code_exec"
        assert func["description"] == "Execute code"
        assert "parameters" in func

    def test_empty_tools(self, tr: OpenAIV1Transformer) -> None:
        assert tr.transform_tools([]) == []


class TestParseResponse:
    def test_simple_text(self, tr: OpenAIV1Transformer) -> None:
        raw = {
            "choices": [{"message": {"role": "assistant", "content": "Hello!"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        result = tr.parse_response(raw)
        assert result.content == "Hello!"
        assert result.tokens_used == 15
        assert result.provider_id == ProviderID.OPENAI

    def test_null_content_with_tool_calls(self, tr: OpenAIV1Transformer) -> None:
        raw = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "search", "arguments": '{"q":"cats"}'},
                    }],
                }
            }],
            "usage": {"total_tokens": 20},
        }
        result = tr.parse_response(raw)
        # Tool calls go to tool_calls field, not stringified in content
        assert len(result.tool_calls) == 1
        tc = result.tool_calls[0]
        assert tc.tool_call_id == "c1"
        assert tc.tool_name == "search"
        assert tc.arguments == {"q": "cats"}
        assert result.content == ""  # No text content in this response

    def test_multiple_tool_calls_parsed(self, tr: OpenAIV1Transformer) -> None:
        raw = {
            "choices": [{"message": {
                "content": None,
                "tool_calls": [
                    {"id": "t1", "function": {"name": "f1", "arguments": '{"a":1}'}},
                    {"id": "t2", "function": {"name": "f2", "arguments": '{"b":2}'}},
                ],
            }}],
            "usage": {"total_tokens": 30},
        }
        result = tr.parse_response(raw)
        assert len(result.tool_calls) == 2
        assert result.tool_calls[0].tool_name == "f1"
        assert result.tool_calls[1].tool_name == "f2"

    def test_malformed_arguments_defaults_empty_dict(self, tr: OpenAIV1Transformer) -> None:
        raw = {
            "choices": [{"message": {
                "content": "thinking...",
                "tool_calls": [
                    {"id": "x", "function": {"name": "g", "arguments": "not-json"}},
                ],
            }}],
            "usage": {"total_tokens": 5},
        }
        result = tr.parse_response(raw)
        assert result.tool_calls[0].arguments == {}

    def test_no_tool_calls_returns_empty_list(self, tr: OpenAIV1Transformer) -> None:
        raw = {"choices": [{"message": {"content": "plain"}}], "usage": {}}
        result = tr.parse_response(raw)
        assert result.tool_calls == []

    def test_empty_choices_raises(self, tr: OpenAIV1Transformer) -> None:
        with pytest.raises(TransformError, match="no choices"):
            tr.parse_response({"choices": []})

    def test_missing_usage_defaults_zero(self, tr: OpenAIV1Transformer) -> None:
        raw = {"choices": [{"message": {"content": "hi"}}]}
        result = tr.parse_response(raw)
        assert result.tokens_used == 0

    def test_raw_response_preserved(self, tr: OpenAIV1Transformer) -> None:
        raw = {"choices": [{"message": {"content": "x"}}], "id": "chatcmpl-123"}
        result = tr.parse_response(raw)
        assert result.raw_response == raw


class TestProviderMetadata:
    def test_provider_id(self, tr: OpenAIV1Transformer) -> None:
        assert tr.provider_id == ProviderID.OPENAI

    def test_api_version(self, tr: OpenAIV1Transformer) -> None:
        assert tr.api_version == "v1"
