"""
CanonicalMessage ↔ JSONB 序列化/反序列化
CanonicalMessage ↔ JSONB serialization / deserialization.

Layer 4: Only imports from shared/.

Design / 设计:
  - 使用 `type` 字段作为 ContentPart 鉴别符 / Uses `type` field as ContentPart discriminator
  - 所有字段都是基本 Python 类型，可直接 JSON 序列化
    All fields are basic Python types, directly JSON-serializable
  - 反序列化时遇到未知 type 跳过（CanonicalMessage 演进规则）
    Unknown type values are skipped on deserialization (CanonicalMessage evolution rule)
"""

from __future__ import annotations

from typing import Any

from orchestration.shared.enums import ContentPartType, Role
from orchestration.shared.types import (
    CanonicalMessage,
    ContentPart,
    ImagePart,
    TextPart,
    ToolCallPart,
    ToolResultPart,
)


# ---------------------------------------------------------------------------
# ContentPart serialization / ContentPart 序列化
# ---------------------------------------------------------------------------

def serialize_content_part(part: ContentPart) -> dict[str, Any]:
    """将单个 ContentPart 序列化为 dict / Serialize a single ContentPart to dict."""
    if isinstance(part, TextPart):
        return {"type": part.type.value, "text": part.text}
    if isinstance(part, ImagePart):
        return {
            "type": part.type.value,
            "url": part.url,
            "data": part.data,
            "media_type": part.media_type,
        }
    if isinstance(part, ToolCallPart):
        return {
            "type": part.type.value,
            "tool_call_id": part.tool_call_id,
            "tool_name": part.tool_name,
            "arguments": part.arguments,
        }
    if isinstance(part, ToolResultPart):
        return {
            "type": part.type.value,
            "tool_call_id": part.tool_call_id,
            "content": part.content,
            "is_error": part.is_error,
        }
    # 未知类型回退 / Unknown type fallback
    return {"type": "unknown"}


def deserialize_content_part(data: dict[str, Any]) -> ContentPart | None:
    """
    将 dict 反序列化为 ContentPart；遇到未知 type 返回 None。
    Deserialize dict to ContentPart; returns None for unknown types.
    """
    type_str = data.get("type", "")
    if type_str == ContentPartType.TEXT.value:
        return TextPart(text=data["text"])
    if type_str == ContentPartType.IMAGE.value:
        return ImagePart(
            url=data.get("url", ""),
            data=data.get("data", ""),
            media_type=data.get("media_type", "image/jpeg"),
        )
    if type_str == ContentPartType.TOOL_CALL.value:
        return ToolCallPart(
            tool_call_id=data["tool_call_id"],
            tool_name=data["tool_name"],
            arguments=data.get("arguments", {}),
        )
    if type_str == ContentPartType.TOOL_RESULT.value:
        return ToolResultPart(
            tool_call_id=data["tool_call_id"],
            content=data.get("content", ""),
            is_error=data.get("is_error", False),
        )
    # 演进规则：未知 type 跳过而非报错 / Evolution rule: skip unknown types
    return None


# ---------------------------------------------------------------------------
# CanonicalMessage serialization / CanonicalMessage 序列化
# ---------------------------------------------------------------------------

def serialize_message(msg: CanonicalMessage) -> dict[str, Any]:
    """将 CanonicalMessage 序列化为 JSON-safe dict / Serialize CanonicalMessage to JSON-safe dict."""
    return {
        "role": msg.role.value,
        "content": [serialize_content_part(p) for p in msg.content],
        "message_id": msg.message_id,
        "schema_version": msg.schema_version,
        "metadata": msg.metadata,
    }


def deserialize_message(data: dict[str, Any]) -> CanonicalMessage:
    """将 dict 反序列化为 CanonicalMessage / Deserialize dict to CanonicalMessage."""
    role = Role(data["role"])
    raw_parts = data.get("content", [])
    content: list[ContentPart] = []
    for part_data in raw_parts:
        part = deserialize_content_part(part_data)
        if part is not None:  # 跳过未知 type / skip unknown types
            content.append(part)
    return CanonicalMessage(
        role=role,
        content=content,
        message_id=data.get("message_id", ""),
        schema_version=data.get("schema_version", 1),
        metadata=data.get("metadata", {}),
    )


def serialize_messages(messages: list[CanonicalMessage]) -> list[dict[str, Any]]:
    """序列化消息列表 / Serialize a list of messages."""
    return [serialize_message(m) for m in messages]


def deserialize_messages(data: list[dict[str, Any]]) -> list[CanonicalMessage]:
    """反序列化消息列表 / Deserialize a list of messages."""
    return [deserialize_message(d) for d in data]
