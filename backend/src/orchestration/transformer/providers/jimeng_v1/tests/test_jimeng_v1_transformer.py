"""
JimengV1Transformer 单元测试
Unit tests for JimengV1Transformer — image generation format conversion.
"""

import pytest

from orchestration.shared.enums import ProviderID
from orchestration.shared.errors import TransformError
from orchestration.transformer.canonical import assistant_message, system_message, user_message
from orchestration.transformer.providers.jimeng_v1.transformer import JimengV1Transformer


@pytest.fixture()
def tr() -> JimengV1Transformer:
    return JimengV1Transformer()


class TestTransform:
    def test_extracts_last_user_message_as_prompt(self, tr: JimengV1Transformer) -> None:
        msgs = [user_message("Generate a cat image")]
        payload = tr.transform(msgs)
        assert payload["prompt"] == "Generate a cat image"

    def test_uses_last_user_message_only(self, tr: JimengV1Transformer) -> None:
        msgs = [
            user_message("First message"),
            assistant_message("OK"),
            user_message("Final prompt: a sunset"),
        ]
        payload = tr.transform(msgs)
        assert payload["prompt"] == "Final prompt: a sunset"

    def test_system_message_ignored(self, tr: JimengV1Transformer) -> None:
        msgs = [system_message("Generate images"), user_message("A cat")]
        payload = tr.transform(msgs)
        assert payload["prompt"] == "A cat"

    def test_default_dimensions(self, tr: JimengV1Transformer) -> None:
        payload = tr.transform([user_message("prompt")])
        assert payload["width"] == 1024
        assert payload["height"] == 1024

    def test_custom_dimensions(self) -> None:
        tr = JimengV1Transformer(width=512, height=768)
        payload = tr.transform([user_message("portrait")])
        assert payload["width"] == 512
        assert payload["height"] == 768

    def test_model_version_in_payload(self, tr: JimengV1Transformer) -> None:
        payload = tr.transform([user_message("test")])
        assert "model_version" in payload

    def test_no_user_message_raises(self, tr: JimengV1Transformer) -> None:
        with pytest.raises(TransformError, match="text prompt"):
            tr.transform([system_message("only system")])

    def test_empty_messages_raises(self, tr: JimengV1Transformer) -> None:
        with pytest.raises(TransformError):
            tr.transform([])


class TestTransformTools:
    def test_always_returns_empty(self, tr: JimengV1Transformer) -> None:
        from orchestration.shared.types import CanonicalTool
        tools = [CanonicalTool(name="x", description="y", input_schema={})]
        assert tr.transform_tools(tools) == []


class TestParseResponse:
    def test_single_image_url(self, tr: JimengV1Transformer) -> None:
        raw = {
            "data": {
                "algorithm_base_resp": {"status_code": 0, "status_message": "Success"},
                "image_urls": ["https://cdn.example.com/img1.jpg"],
            }
        }
        result = tr.parse_response(raw)
        assert result.content == "https://cdn.example.com/img1.jpg"
        assert result.provider_id == ProviderID.JIMENG
        assert result.metadata["image_count"] == 1

    def test_multiple_image_urls_joined(self, tr: JimengV1Transformer) -> None:
        raw = {
            "data": {
                "algorithm_base_resp": {"status_code": 0, "status_message": "Success"},
                "image_urls": ["https://cdn.example.com/1.jpg", "https://cdn.example.com/2.jpg"],
            }
        }
        result = tr.parse_response(raw)
        assert "\n" in result.content
        assert result.metadata["image_count"] == 2

    def test_api_error_raises_transform_error(self, tr: JimengV1Transformer) -> None:
        raw = {
            "data": {
                "algorithm_base_resp": {"status_code": 1001, "status_message": "Quota exceeded"},
                "image_urls": [],
            }
        }
        with pytest.raises(TransformError, match="1001"):
            tr.parse_response(raw)

    def test_no_image_urls_raises(self, tr: JimengV1Transformer) -> None:
        raw = {
            "data": {
                "algorithm_base_resp": {"status_code": 0},
                "image_urls": [],
            }
        }
        with pytest.raises(TransformError, match="no image"):
            tr.parse_response(raw)

    def test_tokens_used_zero(self, tr: JimengV1Transformer) -> None:
        raw = {
            "data": {
                "algorithm_base_resp": {"status_code": 0},
                "image_urls": ["https://x.com/img.jpg"],
            }
        }
        result = tr.parse_response(raw)
        assert result.tokens_used == 0


class TestProviderMetadata:
    def test_provider_id(self, tr: JimengV1Transformer) -> None:
        assert tr.provider_id == ProviderID.JIMENG

    def test_api_version(self, tr: JimengV1Transformer) -> None:
        assert tr.api_version == "v1"
