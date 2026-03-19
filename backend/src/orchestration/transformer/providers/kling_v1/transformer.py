"""
KlingV1Transformer — 可灵（Kling AI）视频生成 API v1 格式转换器
KlingV1Transformer — Converts canonical messages to Kling video generation API format.

Layer 3: Only imports from shared/ and transformer/.
第 3 层：仅从 shared/ 和 transformer/ 导入。

Kling AI (可灵) is Kuaishou's video generation service.
可灵是快手的视频生成服务。

API characteristics / API 特性:
  - Text-to-video OR image-to-video generation
    文本生成视频或图像生成视频
  - Asynchronous: submit task → poll for result (returns task_id)
    异步：提交任务 → 轮询结果（返回 task_id）
  - Does NOT support tool calling or multi-turn conversation
    不支持工具调用或多轮对话
  - Extracts last user message as video prompt
    从最后一条用户消息提取视频提示词
  - Optional: negative_prompt, duration, aspect_ratio, cfg_scale
    可选：负向提示词、时长、宽高比、引导系数

Reference: https://app.klingai.com/global/dev/api-doc
"""

from __future__ import annotations

from typing import Any

from orchestration.shared.enums import ProviderID
from orchestration.shared.errors import TransformError
from orchestration.shared.types import (
    CanonicalMessage,
    CanonicalTool,
    ImagePart,
    ProviderResult,
    TextPart,
)
from orchestration.transformer.base import BaseTransformer


class KlingV1Transformer(BaseTransformer):
    """
    可灵视频生成 API v1 格式转换器（异步任务模式）
    Transformer for Kling AI video generation API (async task mode).

    The adapter handles polling separately; this transformer only handles
    request building and response parsing.
    Adapter 单独处理轮询；此 transformer 仅处理请求构建和响应解析。
    """

    provider_id: ProviderID = ProviderID.KLING
    api_version: str = "v1"

    DEFAULT_MODEL = "kling-v1"
    DEFAULT_DURATION = "5"       # seconds as string per API spec
    DEFAULT_ASPECT_RATIO = "16:9"
    DEFAULT_CFG_SCALE = 0.5
    DEFAULT_MODE = "std"         # "std" or "pro"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        duration: str = DEFAULT_DURATION,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        cfg_scale: float = DEFAULT_CFG_SCALE,
        mode: str = DEFAULT_MODE,
    ) -> None:
        self.model = model
        self.duration = duration
        self.aspect_ratio = aspect_ratio
        self.cfg_scale = cfg_scale
        self.mode = mode

    def transform(self, messages: list[CanonicalMessage]) -> dict[str, Any]:
        """
        从对话历史中提取视频生成提示词，构建可灵 API 请求
        Extract video generation prompt from conversation history and build Kling API request.

        Supports text-to-video and image-to-video:
        支持文本生成视频和图像生成视频：
          - If last user message contains text: text-to-video
            如果最后一条用户消息包含文本：文本生成视频
          - If last user message contains image: image-to-video
            如果最后一条用户消息包含图像：图像生成视频
        """
        prompt = ""
        image_url = ""
        image_data = ""
        image_media_type = "image/jpeg"
        negative_prompt = ""

        # Find the last user message
        # 找到最后一条用户消息
        for msg in reversed(messages):
            if msg.role.value == "user":
                for part in msg.content:
                    if isinstance(part, TextPart) and part.text:
                        # Check if it's a negative prompt (prefixed with "negative:")
                        # 检查是否为负向提示词（以 "negative:" 为前缀）
                        if part.text.startswith("negative:"):
                            negative_prompt = part.text[len("negative:"):].strip()
                        else:
                            prompt = part.text
                    elif isinstance(part, ImagePart):
                        image_url = part.url
                        image_data = part.data
                        image_media_type = part.media_type
                break

        if not prompt and not image_url and not image_data:
            raise TransformError(
                "Kling video generation requires either a text prompt or an image in the last user message"
            )

        payload: dict[str, Any] = {
            "model": self.model,
            "duration": self.duration,
            "aspect_ratio": self.aspect_ratio,
            "cfg_scale": self.cfg_scale,
            "mode": self.mode,
        }

        if prompt:
            payload["prompt"] = prompt

        if negative_prompt:
            payload["negative_prompt"] = negative_prompt

        # Image-to-video: provide image as reference
        # 图像生成视频：提供图像作为参考
        if image_url or image_data:
            image_payload: dict[str, Any] = {}
            if image_url:
                image_payload["url"] = image_url
            if image_data:
                image_payload["base64"] = image_data
            payload["image"] = image_payload

        return payload

    def transform_tools(self, tools: list[CanonicalTool]) -> list[dict[str, Any]]:
        """
        可灵不支持工具调用，始终返回空列表
        Kling does not support tool calling — always returns empty list.
        """
        return []

    def parse_response(self, raw: dict[str, Any]) -> ProviderResult:
        """
        解析可灵 API 响应（任务提交响应，包含 task_id）
        Parse Kling API response (task submission response containing task_id).

        This parses the INITIAL task submission response.
        Task polling and final video URL extraction is handled by the Adapter.
        这解析的是初始任务提交响应。
        任务轮询和最终视频 URL 提取由 Adapter 处理。

        Initial submission response format / 初始提交响应格式:
        {
          "code": 0,
          "message": "SUBMITTED",
          "request_id": "xxx",
          "data": {"task_id": "yyy", "task_status": "submitted"}
        }

        Final completed task response format / 最终完成响应格式:
        {
          "code": 0,
          "data": {
            "task_id": "yyy",
            "task_status": "succeed",
            "task_result": {"videos": [{"url": "https://...", "duration": "5"}]}
          }
        }
        """
        try:
            code = raw.get("code", 0)
            if code != 0:
                message = raw.get("message", "Unknown error")
                raise TransformError(f"Kling API error {code}: {message}")

            data = raw.get("data", {})
            task_id = data.get("task_id", "")
            task_status = data.get("task_status", "")

            # Check if this is a completed task with video results
            # 检查是否是包含视频结果的已完成任务
            task_result = data.get("task_result", {})
            videos = task_result.get("videos", [])

            if videos:
                # Completed task — extract video URL
                # 已完成任务 — 提取视频 URL
                video_url = videos[0].get("url", "")
                duration = videos[0].get("duration", "")
                content = video_url
                metadata = {
                    "task_id": task_id,
                    "task_status": task_status,
                    "videos": videos,
                    "video_duration": duration,
                }
            else:
                # Submitted/processing task — return task_id as content
                # 已提交/处理中任务 — 以 task_id 作为内容返回
                content = task_id
                metadata = {
                    "task_id": task_id,
                    "task_status": task_status,
                    "is_pending": True,  # Adapter will poll until complete
                }

            return ProviderResult(
                subtask_id="",
                provider_id=self.provider_id,
                content=content,
                transformer_version=self.api_version,
                tokens_used=0,  # Video generation doesn't use tokens
                raw_response=raw,
                metadata=metadata,
            )
        except TransformError:
            raise
        except (KeyError, TypeError) as exc:
            raise TransformError(
                f"Failed to parse Kling response: {exc}. Raw: {str(raw)[:200]}"
            ) from exc
