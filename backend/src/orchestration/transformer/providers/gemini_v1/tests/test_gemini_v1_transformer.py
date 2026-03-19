"""
GeminiV1Transformer 单元测试
Unit tests for GeminiV1Transformer.
"""

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
from orchestration.transformer.providers.gemini_v1.transformer import GeminiV1Transformer


@pytest.fixture()
def tr() -> GeminiV1Transformer:
    return GeminiV1Transformer(model="gemini-2.0-flash", max_tokens=4096)


class TestTransform:
    def test_simple_user_message(self, tr: GeminiV1Transformer) -> None:
        payload = tr.transform([user_message("Hello")])
        assert "contents" in payload
        assert payload["contents"][0]["role"] == "user"
        parts = payload["contents"][0]["parts"]
        assert any(p.get("text") == "Hello" for p in parts)

    def test_system_instruction_separated(self, tr: GeminiV1Transformer) -> None:
        payload = tr.transform([system_message("Be helpful"), user_message("Hi")])
        assert "system_instruction" in payload
        assert "Be helpful" in payload["system_instruction"]["parts"][0]["text"]
        # System message should not appear in contents[]
        assert all(c["role"] != "system" for c in payload["contents"])

    def test_assistant_becomes_model_role(self, tr: GeminiV1Transformer) -> None:
        msgs = [user_message("Q"), assistant_message("A")]
        payload = tr.transform(msgs)
        roles = [c["role"] for c in payload["contents"]]
        assert "model" in roles
        assert "assistant" not in roles

    def test_empty_messages_raises(self, tr: GeminiV1Transformer) -> None:
        with pytest.raises(TransformError):
            tr.transform([])

    def test_base64_image(self, tr: GeminiV1Transformer) -> None:
        msgs = [user_image_message(data="aGVsbG8=", media_type="image/jpeg")]
        payload = tr.transform(msgs)
        parts = payload["contents"][0]["parts"]
        img_part = next(p for p in parts if "inline_data" in p)
        assert img_part["inline_data"]["data"] == "aGVsbG8="
        assert img_part["inline_data"]["mime_type"] == "image/jpeg"

    def test_url_image(self, tr: GeminiV1Transformer) -> None:
        msgs = [user_image_message(url="gs://bucket/img.jpg")]
        payload = tr.transform(msgs)
        parts = payload["contents"][0]["parts"]
        file_part = next(p for p in parts if "file_data" in p)
        assert file_part["file_data"]["file_uri"] == "gs://bucket/img.jpg"

    def test_tool_call_in_model_message(self, tr: GeminiV1Transformer) -> None:
        msgs = [
            user_message("Search"),
            assistant_tool_call_message("web_search", {"query": "cats"}, tool_call_id="c1"),
        ]
        payload = tr.transform(msgs)
        model_content = next(c for c in payload["contents"] if c["role"] == "model")
        fc_part = next(p for p in model_content["parts"] if "functionCall" in p)
        assert fc_part["functionCall"]["name"] == "web_search"
        assert fc_part["functionCall"]["args"] == {"query": "cats"}

    def test_tool_result_as_user_role(self, tr: GeminiV1Transformer) -> None:
        msgs = [
            user_message("Search"),
            assistant_tool_call_message("search", {}, tool_call_id="c1"),
            tool_result_message("c1", "Found results"),
        ]
        payload = tr.transform(msgs)
        user_contents = [c for c in payload["contents"] if c["role"] == "user"]
        # Last user content should have functionResponse
        last_user = user_contents[-1]
        fr_part = next(p for p in last_user["parts"] if "functionResponse" in p)
        assert fr_part["functionResponse"]["response"]["content"] == "Found results"

    def test_generation_config_present(self, tr: GeminiV1Transformer) -> None:
        payload = tr.transform([user_message("hi")])
        assert "generationConfig" in payload
        assert payload["generationConfig"]["maxOutputTokens"] == 4096


class TestTransformTools:
    def test_basic_tools(self, tr: GeminiV1Transformer) -> None:
        tools = [CanonicalTool(name="t1", description="d1", input_schema={"type": "object"})]
        result = tr.transform_tools(tools)
        assert len(result) == 1
        assert "function_declarations" in result[0]
        decls = result[0]["function_declarations"]
        assert decls[0]["name"] == "t1"

    def test_empty_tools(self, tr: GeminiV1Transformer) -> None:
        assert tr.transform_tools([]) == []


class TestParseResponse:
    def test_simple_text(self, tr: GeminiV1Transformer) -> None:
        raw = {
            "candidates": [{
                "content": {"parts": [{"text": "Hello!"}], "role": "model"}
            }],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
        }
        result = tr.parse_response(raw)
        assert result.content == "Hello!"
        assert result.tokens_used == 15
        assert result.provider_id == ProviderID.GEMINI

    def test_function_call_in_response(self, tr: GeminiV1Transformer) -> None:
        raw = {
            "candidates": [{
                "content": {
                    "parts": [
                        {"functionCall": {"name": "search", "args": {"q": "test"}}}
                    ],
                    "role": "model"
                }
            }],
            "usageMetadata": {},
        }
        result = tr.parse_response(raw)
        assert "search" in result.content

    def test_no_candidates_raises(self, tr: GeminiV1Transformer) -> None:
        with pytest.raises(TransformError, match="no candidates"):
            tr.parse_response({"candidates": []})


class TestProviderMetadata:
    def test_provider_id(self, tr: GeminiV1Transformer) -> None:
        assert tr.provider_id == ProviderID.GEMINI

    def test_api_version(self, tr: GeminiV1Transformer) -> None:
        assert tr.api_version == "v1"
