"""
BaseTransformer ABC — 所有 provider transformer 的抽象基类
BaseTransformer ABC — abstract base class for all provider transformers.

Layer 3: Only imports from shared/. No knowledge of providers/.
第 3 层：仅从 shared/ 导入，不知道 providers/。

Subclasses implement the three abstract methods to handle:
  1. transform()       → CanonicalMessage list → provider-specific request dict
  2. transform_tools() → CanonicalTool list    → provider-specific tools list
  3. parse_response()  → provider raw dict     → ProviderResult

Each provider+version combination is its own subpackage (e.g., anthropic_v3/).
Old versions are never modified; new versions get new subpackages.
每个 provider+版本 组合是独立子包。旧版本永不修改；新版本创建新子包。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from orchestration.shared.enums import ProviderID
from orchestration.shared.errors import TransformError
from orchestration.shared.types import (
    CanonicalMessage,
    CanonicalTool,
    ContentPart,
    ImagePart,
    TextPart,
    ToolCallPart,
    ToolResultPart,
    ProviderResult,
)


class BaseTransformer(ABC):
    """
    所有 provider transformer 的抽象基类
    Abstract base class for all provider transformers.

    Concrete transformers must:
    具体 transformer 必须：
      - Set class-level `provider_id` and `api_version`
        设置类级别的 `provider_id` 和 `api_version`
      - Implement all three abstract methods
        实现全部三个抽象方法
      - Only raise `TransformError` (never ProviderError or raw exceptions)
        只抛 `TransformError`（不抛 ProviderError 或原始异常）
    """

    provider_id: ProviderID
    api_version: str

    # -----------------------------------------------------------------------
    # Abstract interface / 抽象接口
    # -----------------------------------------------------------------------

    @abstractmethod
    def transform(self, messages: list[CanonicalMessage]) -> dict[str, Any]:
        """
        将 CanonicalMessage 列表转换为 provider 专有请求 payload
        Convert CanonicalMessage list to provider-specific request payload.

        Args / 参数:
            messages: Ordered conversation history in canonical format.
                      规范格式的有序对话历史。

        Returns / 返回:
            Provider-specific request dict (ready to be sent as HTTP body).
            Provider 专有请求 dict（可直接作为 HTTP body 发送）。

        Raises / 抛出:
            TransformError: If messages cannot be converted to provider format.
                           如果消息无法转换为 provider 格式。
        """
        ...

    @abstractmethod
    def transform_tools(self, tools: list[CanonicalTool]) -> list[dict[str, Any]]:
        """
        将工具定义列表转换为 provider 专有格式
        Convert tool definitions to provider-specific format.

        Returns empty list if provider doesn't support function calling.
        如果 provider 不支持函数调用，返回空列表。

        Raises / 抛出:
            TransformError: If tool definitions cannot be converted.
        """
        ...

    @abstractmethod
    def parse_response(self, raw: dict[str, Any]) -> ProviderResult:
        """
        将 provider 原始响应解析为标准 ProviderResult
        Parse provider raw response into standardized ProviderResult.

        Args / 参数:
            raw: HTTP-success response body from provider (already parsed JSON).
                 来自 provider 的 HTTP 成功响应体（已解析的 JSON）。
                 HTTP errors are handled by Adapter before reaching this method.
                 HTTP 错误由 Adapter 在调用此方法前处理。

        Raises / 抛出:
            TransformError: If response cannot be parsed.
        """
        ...

    # -----------------------------------------------------------------------
    # Shared helper methods / 共享辅助方法
    # -----------------------------------------------------------------------

    def _safe_transform(self, messages: list[CanonicalMessage]) -> dict[str, Any]:
        """
        带错误包装的 transform 调用
        Transform with error wrapping — wraps unexpected exceptions in TransformError.
        """
        try:
            return self.transform(messages)
        except TransformError:
            raise
        except Exception as exc:
            raise TransformError(
                f"[{self.provider_id}/{self.api_version}] Unexpected transform error: {exc}"
            ) from exc

    def _safe_parse(self, raw: dict[str, Any]) -> ProviderResult:
        """
        带错误包装的 parse_response 调用
        Parse response with error wrapping.
        """
        try:
            return self.parse_response(raw)
        except TransformError:
            raise
        except Exception as exc:
            raise TransformError(
                f"[{self.provider_id}/{self.api_version}] Unexpected parse error: {exc}"
            ) from exc

    @staticmethod
    def _extract_text(parts: list[ContentPart]) -> str:
        """
        从 ContentPart 列表中提取所有文本内容并拼接
        Extract and concatenate all text content from ContentPart list.
        """
        return "".join(p.text for p in parts if isinstance(p, TextPart))

    @staticmethod
    def _has_images(parts: list[ContentPart]) -> bool:
        """检查是否包含图像内容 / Check if parts contain image content."""
        return any(isinstance(p, ImagePart) for p in parts)

    @staticmethod
    def _has_tool_calls(parts: list[ContentPart]) -> bool:
        """检查是否包含工具调用 / Check if parts contain tool calls."""
        return any(isinstance(p, ToolCallPart) for p in parts)

    @staticmethod
    def _has_tool_results(parts: list[ContentPart]) -> bool:
        """检查是否包含工具结果 / Check if parts contain tool results."""
        return any(isinstance(p, ToolResultPart) for p in parts)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(provider={self.provider_id}, version={self.api_version})"
