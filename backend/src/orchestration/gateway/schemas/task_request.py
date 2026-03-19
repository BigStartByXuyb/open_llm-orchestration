"""
任务请求/响应 Pydantic 模型
Task request/response Pydantic models.

Layer 1: No internal imports beyond shared enums.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from orchestration.shared.enums import TaskStatus


# ---------------------------------------------------------------------------
# Task creation / 任务创建
# ---------------------------------------------------------------------------


class TaskCreateRequest(BaseModel):
    """POST /tasks 请求体 / Request body for POST /tasks."""

    message: str = Field(
        ...,
        min_length=1,
        max_length=100_000,
        description="用户消息内容 / User message content",
    )
    session_id: str = Field(
        default="",
        description="会话 ID（空则创建新会话）/ Session ID (empty → create new session)",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="额外元数据 / Additional metadata",
    )


class TaskCreateResponse(BaseModel):
    """POST /tasks 响应体 / Response body for POST /tasks."""

    task_id: str
    session_id: str
    status: TaskStatus
    message: str = "Task created"


# ---------------------------------------------------------------------------
# Task status / 任务状态
# ---------------------------------------------------------------------------


class TaskStatusResponse(BaseModel):
    """GET /tasks/{task_id} 响应体 / Response body for GET /tasks/{task_id}."""

    task_id: str
    session_id: str
    status: TaskStatus
    result: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Session / 会话
# ---------------------------------------------------------------------------


class SessionResponse(BaseModel):
    """会话信息响应 / Session info response."""

    session_id: str
    tenant_id: str
    message_count: int
    char_count: int
    created_at: str | None = None
    updated_at: str | None = None


class SessionListItem(BaseModel):
    """会话列表条目 / Session list item."""

    session_id: str
    message_count: int
    char_count: int
    created_at: str | None = None
    updated_at: str | None = None


class SessionListResponse(BaseModel):
    """GET /sessions 响应体 / Response body for GET /sessions."""

    sessions: list[SessionListItem]
    total: int


# ---------------------------------------------------------------------------
# Plugin / 插件
# ---------------------------------------------------------------------------


class PluginInfo(BaseModel):
    """插件信息 / Plugin info."""

    plugin_id: str
    version: str
    skills: list[str]


class SkillInfo(BaseModel):
    """Skill 信息 / Skill info."""

    skill_id: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]


class PluginListResponse(BaseModel):
    """GET /plugins 响应体 / Response body for GET /plugins."""

    plugins: list[PluginInfo]
    total: int


# ---------------------------------------------------------------------------
# Error / 错误
# ---------------------------------------------------------------------------


class ErrorResponse(BaseModel):
    """标准错误响应 / Standard error response."""

    error: str
    code: str = "internal_error"
    detail: str | None = None
