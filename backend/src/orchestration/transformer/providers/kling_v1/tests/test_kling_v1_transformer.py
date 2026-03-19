"""
KlingV1Transformer 单元测试
Unit tests for KlingV1Transformer — video generation format conversion.
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
from orchestration.transformer.providers.kling_v1.transformer import KlingV1Transformer


@pytest.fixture()
def tr() -> KlingV1Transformer:
    return KlingV1Transformer()


class TestTransform:
    def test_text_to_video_prompt(self, tr: KlingV1Transformer) -> None:
        payload = tr.transform([user_message("A sunset over the ocean")])
        assert payload["prompt"] == "A sunset over the ocean"

    def test_uses_last_user_message(self, tr: KlingV1Transformer) -> None:
        msgs = [
            user_message("First"),
            assistant_message("OK"),
            user_message("Final prompt"),
        ]
        payload = tr.transform(msgs)
        assert payload["prompt"] == "Final prompt"

    def test_default_settings(self, tr: KlingV1Transformer) -> None:
        payload = tr.transform([user_message("test")])
        assert payload["duration"] == "5"
        assert payload["aspect_ratio"] == "16:9"
        assert payload["mode"] == "std"

    def test_negative_prompt_prefix_parsed(self, tr: KlingV1Transformer) -> None:
        from orchestration.shared.types import CanonicalMessage, TextPart
        from orchestration.shared.enums import Role
        msg = CanonicalMessage(
            role=Role.USER,
            content=[
                TextPart(text="A sunset"),
                TextPart(text="negative: blurry, low quality"),
            ],
        )
        payload = tr.transform([msg])
        assert payload["prompt"] == "A sunset"
        assert payload["negative_prompt"] == "blurry, low quality"

    def test_image_to_video(self, tr: KlingV1Transformer) -> None:
        msgs = [user_image_message(url="https://x.com/ref.jpg", caption="Animate this")]
        payload = tr.transform(msgs)
        assert "image" in payload
        assert payload["image"]["url"] == "https://x.com/ref.jpg"
        assert payload["prompt"] == "Animate this"

    def test_base64_image_to_video(self, tr: KlingV1Transformer) -> None:
        msgs = [user_image_message(data="aGVsbG8=")]
        payload = tr.transform(msgs)
        assert payload["image"]["base64"] == "aGVsbG8="

    def test_empty_messages_raises(self, tr: KlingV1Transformer) -> None:
        with pytest.raises(TransformError):
            tr.transform([])

    def test_no_user_message_raises(self, tr: KlingV1Transformer) -> None:
        with pytest.raises(TransformError):
            tr.transform([system_message("only sys")])

    def test_custom_model(self) -> None:
        tr = KlingV1Transformer(model="kling-v2", duration="10", mode="pro")
        payload = tr.transform([user_message("epic video")])
        assert payload["model"] == "kling-v2"
        assert payload["duration"] == "10"
        assert payload["mode"] == "pro"


class TestTransformTools:
    def test_always_returns_empty(self, tr: KlingV1Transformer) -> None:
        from orchestration.shared.types import CanonicalTool
        assert tr.transform_tools([CanonicalTool(name="x", description="y", input_schema={})]) == []


class TestParseResponse:
    def test_pending_task(self, tr: KlingV1Transformer) -> None:
        raw = {
            "code": 0,
            "message": "SUBMITTED",
            "data": {
                "task_id": "task_abc123",
                "task_status": "submitted",
            },
        }
        result = tr.parse_response(raw)
        assert result.content == "task_abc123"
        assert result.metadata["is_pending"] is True
        assert result.metadata["task_id"] == "task_abc123"

    def test_completed_task_with_video(self, tr: KlingV1Transformer) -> None:
        raw = {
            "code": 0,
            "data": {
                "task_id": "task_abc",
                "task_status": "succeed",
                "task_result": {
                    "videos": [{"url": "https://cdn.kling.com/video.mp4", "duration": "5"}]
                },
            },
        }
        result = tr.parse_response(raw)
        assert result.content == "https://cdn.kling.com/video.mp4"
        assert result.metadata.get("is_pending") is not True
        assert result.metadata["video_duration"] == "5"

    def test_api_error_raises(self, tr: KlingV1Transformer) -> None:
        raw = {"code": 1002, "message": "Insufficient credits", "data": {}}
        with pytest.raises(TransformError, match="1002"):
            tr.parse_response(raw)

    def test_tokens_used_zero(self, tr: KlingV1Transformer) -> None:
        raw = {
            "code": 0,
            "data": {"task_id": "t1", "task_status": "submitted"},
        }
        result = tr.parse_response(raw)
        assert result.tokens_used == 0

    def test_provider_id(self, tr: KlingV1Transformer) -> None:
        raw = {
            "code": 0,
            "data": {"task_id": "t1", "task_status": "submitted"},
        }
        result = tr.parse_response(raw)
        assert result.provider_id == ProviderID.KLING


class TestProviderMetadata:
    def test_provider_id(self, tr: KlingV1Transformer) -> None:
        assert tr.provider_id == ProviderID.KLING

    def test_api_version(self, tr: KlingV1Transformer) -> None:
        assert tr.api_version == "v1"
