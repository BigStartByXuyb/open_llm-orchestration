"""
JimengV1Transformer — 极梦（即梦 AI）图像生成 API v1 格式转换器
JimengV1Transformer — Converts canonical messages to Jimeng image generation API format.

Layer 3: Only imports from shared/ and transformer/.
第 3 层：仅从 shared/ 和 transformer/ 导入。

Jimeng (即梦 AI) is ByteDance's image generation service.
极梦是字节跳动的图像生成服务。

API characteristics / API 特性:
  - Text-to-image generation (prompt → image URL)
    文本生成图像（提示词 → 图像 URL）
  - No conversational context — each call is stateless
    无对话上下文 — 每次调用无状态
  - Extracts the last user message as the image prompt
    从最后一条用户消息提取图像提示词
  - Returns image URL(s) in response
    响应中返回图像 URL
  - Does NOT support tool calling
    不支持工具调用

Reference: https://www.volcengine.com/docs/85621/1290118
"""

from __future__ import annotations

from typing import Any

from orchestration.shared.enums import ProviderID
from orchestration.shared.errors import TransformError
from orchestration.shared.types import (
    CanonicalMessage,
    CanonicalTool,
    ProviderResult,
    TextPart,
)
from orchestration.transformer.base import BaseTransformer


class JimengV1Transformer(BaseTransformer):
    """
    极梦图像生成 API v1 格式转换器
    Transformer for Jimeng (即梦 AI) image generation API.

    Only the last user message's text content is used as the image prompt.
    仅使用最后一条用户消息的文本内容作为图像提示词。
    """

    provider_id: ProviderID = ProviderID.JIMENG
    api_version: str = "v1"

    DEFAULT_MODEL = "jimeng-3.0"
    DEFAULT_WIDTH = 1024
    DEFAULT_HEIGHT = 1024
    DEFAULT_SAMPLE_STRENGTH = 0.5

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        width: int = DEFAULT_WIDTH,
        height: int = DEFAULT_HEIGHT,
        sample_strength: float = DEFAULT_SAMPLE_STRENGTH,
    ) -> None:
        self.model = model
        self.width = width
        self.height = height
        self.sample_strength = sample_strength

    def transform(self, messages: list[CanonicalMessage]) -> dict[str, Any]:
        """
        从对话历史中提取图像生成提示词，构建极梦 API 请求
        Extract image generation prompt from conversation history and build Jimeng API request.

        Only the last user message is used as the prompt.
        仅使用最后一条用户消息作为提示词。
        """
        # Find the last user message with text content
        # 找到最后一条包含文本内容的用户消息
        prompt = ""
        for msg in reversed(messages):
            if msg.role.value == "user":
                text_parts = [p.text for p in msg.content if isinstance(p, TextPart) and p.text]
                if text_parts:
                    prompt = " ".join(text_parts)
                    break

        if not prompt:
            raise TransformError(
                "Jimeng image generation requires a text prompt in the last user message"
            )

        return {
            "model_version": self.model,
            "prompt": prompt,
            "width": self.width,
            "height": self.height,
            "sample_strength": self.sample_strength,
            "req_key": "jimeng_high_aes_general_v30",  # API key for model selection
        }

    def transform_tools(self, tools: list[CanonicalTool]) -> list[dict[str, Any]]:
        """
        极梦不支持工具调用，始终返回空列表
        Jimeng does not support tool calling — always returns empty list.
        """
        return []

    def parse_response(self, raw: dict[str, Any]) -> ProviderResult:
        """
        解析极梦 API 响应，提取图像 URL
        Parse Jimeng API response and extract image URL(s).

        Response format / 响应格式:
        {
          "data": {
            "algorithm_base_resp": {"status_code": 0, "status_message": "Success"},
            "image_urls": ["https://..."],
            "binary_data_base64": ["..."]  # Optional
          }
        }
        """
        try:
            data = raw.get("data", {})

            # Check API-level status code
            # 检查 API 级别状态码
            base_resp = data.get("algorithm_base_resp", {})
            status_code = base_resp.get("status_code", 0)
            if status_code != 0:
                status_msg = base_resp.get("status_message", "Unknown error")
                raise TransformError(f"Jimeng API error {status_code}: {status_msg}")

            image_urls = data.get("image_urls", [])
            if not image_urls:
                raise TransformError("Jimeng response contains no image URLs")

            # Primary result: first image URL as content
            # 主结果：第一个图像 URL 作为内容
            content = image_urls[0]
            if len(image_urls) > 1:
                content = "\n".join(image_urls)

            return ProviderResult(
                subtask_id="",
                provider_id=self.provider_id,
                content=content,
                transformer_version=self.api_version,
                tokens_used=0,  # Image generation doesn't use tokens
                raw_response=raw,
                metadata={"image_urls": image_urls, "image_count": len(image_urls)},
            )
        except TransformError:
            raise
        except (KeyError, TypeError) as exc:
            raise TransformError(
                f"Failed to parse Jimeng response: {exc}. Raw: {str(raw)[:200]}"
            ) from exc
