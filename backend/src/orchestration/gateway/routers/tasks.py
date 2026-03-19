"""
任务路由 — POST /tasks, GET /tasks/{task_id}
Task router — POST /tasks, GET /tasks/{task_id}.

Layer 1: Uses deps for all external access.
"""

from __future__ import annotations

import asyncio
import json
import uuid
import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse

from orchestration.shared.enums import TaskStatus
from orchestration.shared.types import Role, TextPart, CanonicalMessage
from orchestration.gateway.deps import (
    ContainerDep,
    RunContextDep,
    TaskRepoDep,
    SessionRepoDep,
    TaskStateStoreDep,
)
from orchestration.gateway.schemas.task_request import (
    TaskCreateRequest,
    TaskCreateResponse,
    TaskStatusResponse,
    ErrorResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post(
    "",
    response_model=TaskCreateResponse,
    status_code=202,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
async def create_task(
    body: TaskCreateRequest,
    context: RunContextDep,
    task_repo: TaskRepoDep,
    session_repo: SessionRepoDep,
    task_state: TaskStateStoreDep,
) -> TaskCreateResponse:
    """
    创建新任务并异步开始编排
    Create a new task and start orchestration asynchronously.

    The task is created with status=pending. The caller should connect
    via WebSocket /ws/{task_id} to receive real-time progress events.
    任务创建时状态为 pending。调用方应通过 WebSocket /ws/{task_id} 接收实时进度事件。
    """
    tenant_id = context.tenant_id

    # Resolve or create session
    # 解析或创建会话
    session_id_str = body.session_id
    if session_id_str:
        try:
            session_uuid = uuid.UUID(session_id_str)
            session_row = await session_repo.get(session_uuid, tenant_id)
            if session_row is None:
                raise HTTPException(status_code=404, detail=f"Session '{session_id_str}' not found")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid session_id format")
    else:
        # Create new session
        session_row = await session_repo.create(tenant_id=tenant_id)
        session_id_str = str(session_row.session_id)

    session_uuid = uuid.UUID(session_id_str)

    # Create task record
    # 创建任务记录
    task_row = await task_repo.create(
        tenant_id=tenant_id,
        input_data={"message": body.message, "metadata": body.metadata},
        session_id=session_uuid,
    )
    task_id = str(task_row.task_id)

    # Persist pending status in Redis (fast cache for WS polling)
    # 在 Redis 中持久化 pending 状态（WS 轮询的快速缓存）
    await task_state.set_status(
        task_id,
        "pending",
        trace_id=context.trace_id,
    )

    logger.info(
        "Task created: task_id=%s session_id=%s tenant_id=%s",
        task_id, session_id_str, tenant_id,
    )

    return TaskCreateResponse(
        task_id=task_id,
        session_id=session_id_str,
        status=TaskStatus.PENDING,
    )


@router.get(
    "/{task_id}",
    response_model=TaskStatusResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_task_status(
    task_id: str,
    context: RunContextDep,
    task_repo: TaskRepoDep,
    task_state: TaskStateStoreDep,
) -> TaskStatusResponse:
    """
    查询任务状态
    Get task status.

    Reads from Redis cache first, falls back to PostgreSQL.
    优先从 Redis 缓存读取，降级到 PostgreSQL。
    """
    tenant_id = context.tenant_id

    # Fast path: check Redis
    # 快速路径：检查 Redis
    redis_data = await task_state.get_status(task_id)
    if redis_data is not None:
        return TaskStatusResponse(
            task_id=task_id,
            session_id="",  # Redis doesn't cache session_id
            status=TaskStatus(redis_data["status"]),
            error=redis_data.get("error"),
            metadata=redis_data.get("extra") or {},
        )

    # Slow path: PostgreSQL
    # 慢速路径：PostgreSQL
    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task_id format")

    task_row = await task_repo.get(task_uuid, tenant_id)
    if task_row is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

    result_text: str | None = None
    if task_row.result and isinstance(task_row.result, dict):
        result_text = task_row.result.get("summary")

    return TaskStatusResponse(
        task_id=str(task_row.task_id),
        session_id=str(task_row.session_id) if task_row.session_id else "",
        status=TaskStatus(task_row.status),
        result=result_text,
        error=task_row.error_message,
    )


@router.get(
    "/{task_id}/stream",
    summary="Task status SSE stream",
    responses={200: {"content": {"text/event-stream": {}}}},
    response_class=StreamingResponse,
)
async def stream_task_status(
    task_id: str,
    context: RunContextDep,
    task_state: TaskStateStoreDep,
    last_seq: int = Query(default=0, description="Last received seq; replay events after this seq"),
    poll_interval: float = Query(default=0.5, ge=0.1, le=5.0),
) -> StreamingResponse:
    """
    SSE 流式任务状态端点（Sprint 18）。
    SSE streaming task status endpoint (Sprint 18).

    推送 task 状态变更事件，直到 task 完成（done / failed）或客户端断开连接。
    Pushes task status change events until task is done/failed or client disconnects.

    重连方式 / Reconnect: 客户端断线后携带 `last_seq` 重连，服务端从 `last_seq+1` 开始重放缓冲事件。
    After disconnect, reconnect with `last_seq` to replay missed buffered WS events.
    """

    async def _event_generator():
        # First, replay any buffered WS events the client missed
        # 首先，重放客户端错过的缓冲 WS 事件
        if last_seq > 0:
            try:
                missed_events = await task_state.get_events_after(task_id, last_seq)
                for evt_json in missed_events:
                    yield f"data: {evt_json}\n\n"
            except Exception as exc:
                logger.warning("Failed to get missed events for %s: %s", task_id, exc)

        # Stream live status updates
        # 流式推送实时状态更新
        last_status: str | None = None
        terminal_statuses = {"done", "failed", "cancelled"}

        while True:
            try:
                data = await task_state.get_status(task_id)
                if data is not None:
                    current_status = data.get("status", "")
                    if current_status != last_status:
                        last_status = current_status
                        event_data = json.dumps({
                            "event": "status",
                            "task_id": task_id,
                            "status": current_status,
                            "updated_at": data.get("updated_at", ""),
                            "error": data.get("error", "") or None,
                        })
                        yield f"data: {event_data}\n\n"

                    if current_status in terminal_statuses:
                        yield "data: {\"event\": \"done\"}\n\n"
                        return
                else:
                    # Task not yet in Redis; send heartbeat
                    yield ": heartbeat\n\n"
            except Exception as exc:
                logger.warning("SSE stream error for task %s: %s", task_id, exc)
                yield f"data: {{\"event\": \"error\", \"message\": \"{exc}\"}}\n\n"
                return

            await asyncio.sleep(poll_interval)

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
