"""
DeepSeekV1Transformer 单元测试
Unit tests for DeepSeekV1Transformer.
"""

import pytest

from orchestration.shared.enums import ProviderID
from orchestration.shared.errors import TransformError
from orchestration.transformer.canonical import (
    assistant_message,
    system_message,
    user_image_message,
    user_message,
)
from orchestration.transformer.providers.deepseek_v1.transformer import DeepSeekV1Transformer


@pytest.fixture()
def tr() -> DeepSeekV1Transformer:
    return DeepSeekV1Transformer(model="deepseek-chat", max_tokens=2048)


class TestTransform:
    def test_simple_user_message(self, tr: DeepSeekV1Transformer) -> None:
        payload = tr.transform([user_message("Hello")])
        assert payload["model"] == "deepseek-chat"
        assert payload["messages"][0] == {"role": "user", "content": "Hello"}

    def test_system_message_in_array(self, tr: DeepSeekV1Transformer) -> None:
        payload = tr.transform([system_message("Be concise"), user_message("Hi")])
        assert payload["messages"][0]["role"] == "system"
        assert payload["messages"][0]["content"] == "Be concise"

    def test_image_replaced_with_notice(self, tr: DeepSeekV1Transformer) -> None:
        # DeepSeek text model doesn't support images — should note this
        msgs = [user_image_message(url="http://x.com/img.jpg", caption="Describe")]
        payload = tr.transform(msgs)
        content = payload["messages"][0]["content"]
        assert "not supported" in content.lower() or "Image" in content

    def test_empty_messages_raises(self, tr: DeepSeekV1Transformer) -> None:
        with pytest.raises(TransformError):
            tr.transform([])

    def test_reasoning_model_name(self) -> None:
        tr = DeepSeekV1Transformer(model="deepseek-reasoner")
        assert tr.model == "deepseek-reasoner"


class TestParseResponse:
    def test_simple_text(self, tr: DeepSeekV1Transformer) -> None:
        raw = {
            "choices": [{"message": {"content": "Hello!"}}],
            "usage": {"total_tokens": 15},
        }
        result = tr.parse_response(raw)
        assert result.content == "Hello!"
        assert result.provider_id == ProviderID.DEEPSEEK

    def test_reasoning_content_prepended(self, tr: DeepSeekV1Transformer) -> None:
        raw = {
            "choices": [{
                "message": {
                    "content": "The answer is 42.",
                    "reasoning_content": "Let me think step by step...",
                }
            }],
            "usage": {"total_tokens": 50},
        }
        result = tr.parse_response(raw)
        assert "<reasoning>" in result.content
        assert "The answer is 42." in result.content

    def test_tool_calls_parsed(self, tr: DeepSeekV1Transformer) -> None:
        raw = {
            "choices": [{"message": {
                "content": None,
                "tool_calls": [
                    {"id": "c1", "function": {"name": "code_exec", "arguments": '{"code":"1+1"}'}},
                ],
            }}],
            "usage": {"total_tokens": 20},
        }
        result = tr.parse_response(raw)
        assert len(result.tool_calls) == 1
        tc = result.tool_calls[0]
        assert tc.tool_call_id == "c1"
        assert tc.tool_name == "code_exec"
        assert tc.arguments == {"code": "1+1"}

    def test_no_tool_calls_returns_empty_list(self, tr: DeepSeekV1Transformer) -> None:
        raw = {"choices": [{"message": {"content": "plain"}}], "usage": {}}
        result = tr.parse_response(raw)
        assert result.tool_calls == []

    def test_empty_choices_raises(self, tr: DeepSeekV1Transformer) -> None:
        with pytest.raises(TransformError):
            tr.parse_response({"choices": []})


class TestProviderMetadata:
    def test_provider_id(self, tr: DeepSeekV1Transformer) -> None:
        assert tr.provider_id == ProviderID.DEEPSEEK

    def test_api_version(self, tr: DeepSeekV1Transformer) -> None:
        assert tr.api_version == "v1"
