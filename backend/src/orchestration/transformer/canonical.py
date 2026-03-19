"""
CanonicalMessage 构建工具函数
CanonicalMessage builder utility functions.

Layer 3: Only imports from shared/. Pure functions — no side effects.
第 3 层：仅从 shared/ 导入。纯函数，无副作用。

These helpers are used by transformers to build CanonicalMessages from
provider responses, and by tests to build fixture messages concisely.
这些辅助函数用于 transformer 从 provider 响应构建 CanonicalMessage，
也用于测试中简洁地构建 fixture 消息。
"""

from __future__ import annotations

import uuid
from typing import Any

from orchestration.shared.enums import Role
from orchestration.shared.types import (
    CanonicalMessage,
    ContentPart,
    ImagePart,
    TextPart,
    ToolCallPart,
    ToolResultPart,
)


# ---------------------------------------------------------------------------
# Single-part message builders / 单内容块消息构建器
# ---------------------------------------------------------------------------


def system_message(text: str, *, message_id: str = "") -> CanonicalMessage:
    """
    构建 system 消息 / Build a system message with text content.
    """
    return CanonicalMessage(
        role=Role.SYSTEM,
        content=[TextPart(text=text)],
        message_id=message_id or _new_id(),
    )


def user_message(text: str, *, message_id: str = "") -> CanonicalMessage:
    """
    构建用户文本消息 / Build a user text message.
    """
    return CanonicalMessage(
        role=Role.USER,
        content=[TextPart(text=text)],
        message_id=message_id or _new_id(),
    )


def assistant_message(text: str, *, message_id: str = "") -> CanonicalMessage:
    """
    构建 assistant 文本消息 / Build an assistant text message.
    """
    return CanonicalMessage(
        role=Role.ASSISTANT,
        content=[TextPart(text=text)],
        message_id=message_id or _new_id(),
    )


def user_image_message(
    *,
    url: str = "",
    data: str = "",
    media_type: str = "image/jpeg",
    caption: str = "",
    message_id: str = "",
) -> CanonicalMessage:
    """
    构建包含图像（可选说明文字）的用户消息
    Build a user message containing an image with optional caption.
    """
    parts: list[ContentPart] = []
    if caption:
        parts.append(TextPart(text=caption))
    parts.append(ImagePart(url=url, data=data, media_type=media_type))
    return CanonicalMessage(
        role=Role.USER,
        content=parts,
        message_id=message_id or _new_id(),
    )


# ---------------------------------------------------------------------------
# Tool-related builders / 工具调用相关构建器
# ---------------------------------------------------------------------------


def assistant_tool_call_message(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    tool_call_id: str = "",
    preceding_text: str = "",
    message_id: str = "",
) -> CanonicalMessage:
    """
    构建包含工具调用的 assistant 消息
    Build an assistant message containing a tool call.

    preceding_text: Optional text content before the tool call (some providers
    allow mixed text+tool_call in one message).
    preceding_text：工具调用前的可选文本内容（某些 provider 允许同一消息中混合文本和工具调用）。
    """
    parts: list[ContentPart] = []
    if preceding_text:
        parts.append(TextPart(text=preceding_text))
    parts.append(
        ToolCallPart(
            tool_call_id=tool_call_id or _new_id(),
            tool_name=tool_name,
            arguments=arguments,
        )
    )
    return CanonicalMessage(
        role=Role.ASSISTANT,
        content=parts,
        message_id=message_id or _new_id(),
    )


def tool_result_message(
    tool_call_id: str,
    content: str,
    *,
    is_error: bool = False,
    message_id: str = "",
) -> CanonicalMessage:
    """
    构建工具结果消息 / Build a tool result message.
    """
    return CanonicalMessage(
        role=Role.TOOL,
        content=[
            ToolResultPart(
                tool_call_id=tool_call_id,
                content=content,
                is_error=is_error,
            )
        ],
        message_id=message_id or _new_id(),
    )


# ---------------------------------------------------------------------------
# Multi-part builder / 多内容块构建器
# ---------------------------------------------------------------------------


def build_message(
    role: Role,
    parts: list[ContentPart],
    *,
    message_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> CanonicalMessage:
    """
    通用消息构建器，支持任意 ContentPart 组合
    General-purpose message builder supporting any combination of ContentParts.
    """
    return CanonicalMessage(
        role=role,
        content=parts,
        message_id=message_id or _new_id(),
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# Conversation helpers / 对话辅助函数
# ---------------------------------------------------------------------------


def total_char_count(messages: list[CanonicalMessage]) -> int:
    """
    计算消息列表的总字符数（用于截断决策）
    Calculate total char count for a list of messages (used for truncation decisions).
    """
    return sum(m.char_count() for m in messages)


def truncate_to_char_limit(
    messages: list[CanonicalMessage],
    limit: int,
    *,
    preserve_system: bool = True,
) -> list[CanonicalMessage]:
    """
    滑动窗口截断：保留最新消息，丢弃最旧消息，直到总字符数 ≤ limit
    Sliding window truncation: keep newest messages, drop oldest, until total ≤ limit.

    If preserve_system=True, system messages are always kept regardless of limit.
    如果 preserve_system=True，system 消息始终保留，不受 limit 影响。

    Returns the truncated message list (newest messages at the end).
    返回截断后的消息列表（最新消息在末尾）。
    """
    if not messages:
        return []

    system_msgs = [m for m in messages if m.role == Role.SYSTEM] if preserve_system else []
    non_system = [m for m in messages if m.role != Role.SYSTEM] if preserve_system else messages

    system_chars = sum(m.char_count() for m in system_msgs)
    remaining_limit = limit - system_chars

    if remaining_limit <= 0:
        # System messages alone exceed limit — keep them all anyway
        # System 消息本身超限 — 无论如何保留
        return system_msgs

    # Walk from newest to oldest, accumulate until limit
    # 从最新到最旧遍历，累积直到达到上限
    kept: list[CanonicalMessage] = []
    accumulated = 0
    for msg in reversed(non_system):
        msg_chars = msg.char_count()
        if accumulated + msg_chars > remaining_limit:
            break
        kept.append(msg)
        accumulated += msg_chars

    kept.reverse()
    return system_msgs + kept


# ---------------------------------------------------------------------------
# Private helpers / 私有辅助函数
# ---------------------------------------------------------------------------


def _new_id() -> str:
    """生成短 UUID 作为消息 ID / Generate a short UUID for message ID."""
    return str(uuid.uuid4())[:8]
