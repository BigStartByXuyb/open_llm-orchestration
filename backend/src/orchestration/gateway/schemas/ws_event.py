"""
WebSocket 事件类型定义
WebSocket event type definitions.

Layer 1: No internal imports.

断线重连占坑：所有事件携带 seq: int 字段，第二期补完基于 seq 的增量同步。
Reconnect placeholder: all events carry seq: int, incremental sync based on
seq will be added in Phase 2.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class BlockCreatedEvent(BaseModel):
    """子任务已创建 / Subtask created."""

    type: Literal["block_created"] = "block_created"
    seq: int
    block_id: str
    title: str
    worker_type: str  # "text" | "code" | "search" | "image" | "video" | "analysis"


class BlockStreamingEvent(BaseModel):
    """子任务流式输出块 / Subtask streaming delta."""

    type: Literal["block_streaming"] = "block_streaming"
    seq: int
    block_id: str
    delta: str


class BlockDoneEvent(BaseModel):
    """子任务已完成 / Subtask completed."""

    type: Literal["block_done"] = "block_done"
    seq: int
    block_id: str
    content: Any
    provider_used: str
    transformer_version: str
    tokens_used: int
    latency_ms: float
    trace_id: str = ""


class SummaryStartEvent(BaseModel):
    """汇总阶段开始 / Summary phase started."""

    type: Literal["summary_start"] = "summary_start"
    seq: int


class SummaryDeltaEvent(BaseModel):
    """汇总流式输出块 / Summary streaming delta."""

    type: Literal["summary_delta"] = "summary_delta"
    seq: int
    delta: str


class SummaryDoneEvent(BaseModel):
    """汇总完成 / Summary completed."""

    type: Literal["summary_done"] = "summary_done"
    seq: int
    full_text: str


class ErrorEvent(BaseModel):
    """错误事件 / Error event."""

    type: Literal["error"] = "error"
    seq: int
    message: str
    code: str = "internal_error"
    block_id: str | None = None


# Union type for all WebSocket events / 所有 WebSocket 事件的联合类型
WSEvent = (
    BlockCreatedEvent
    | BlockStreamingEvent
    | BlockDoneEvent
    | SummaryStartEvent
    | SummaryDeltaEvent
    | SummaryDoneEvent
    | ErrorEvent
)
