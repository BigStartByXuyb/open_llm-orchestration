"""
Webhook 被动触发路由 — POST /webhooks/{event_type}
Webhook passive trigger router — POST /webhooks/{event_type}.

Layer 1: Uses deps for all external access.
第 1 层：通过 deps 访问所有外部资源。

Any external system can POST to /webhooks/{event_type} to create an
orchestration task. The request body may contain:
  message   — task instruction string (optional)
  metadata  — arbitrary dict passed into task input_data (optional)

If WEBHOOK_SECRET is configured the caller must supply a matching
X-Webhook-Secret header, otherwise the request is rejected with 401.
"""

from __future__ import annotations

import uuid
import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from orchestration.shared.config import get_settings
from orchestration.shared.enums import TaskStatus
from orchestration.gateway.deps import (
    RunContextDep,
    SessionRepoDep,
    TaskRepoDep,
    TaskStateStoreDep,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class WebhookTaskResponse(BaseModel):
    task_id: str
    session_id: str
    status: TaskStatus
    event_type: str


@router.post(
    "/{event_type}",
    response_model=WebhookTaskResponse,
    status_code=202,
    responses={401: {"description": "Invalid or missing webhook secret"}},
)
async def receive_webhook(
    event_type: str,
    request: Request,
    context: RunContextDep,
    task_repo: TaskRepoDep,
    session_repo: SessionRepoDep,
    task_state: TaskStateStoreDep,
    x_webhook_secret: str | None = Header(default=None),
) -> WebhookTaskResponse:
    """
    接收外部 Webhook 事件并创建编排任务
    Receive an external webhook event and create an orchestration task.

    The task is created with status=pending. Poll GET /tasks/{task_id}
    or connect via WebSocket /ws/{task_id} for progress updates.
    任务创建时状态为 pending。可通过 GET /tasks/{task_id} 轮询或 WebSocket 获取进度。
    """
    settings = get_settings()
    if settings.WEBHOOK_SECRET and x_webhook_secret != settings.WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid or missing webhook secret")

    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        body = {}

    message: str = body.get("message") or f"Webhook event received: {event_type}"
    metadata: dict[str, Any] = dict(body.get("metadata") or {})
    metadata.setdefault("event_type", event_type)
    metadata.setdefault("source", "webhook")

    tenant_id = context.tenant_id

    # Always create a fresh session for webhook-triggered tasks
    # Webhook 触发的任务始终创建新 session
    session_row = await session_repo.create(tenant_id=tenant_id)
    session_id_str = str(session_row.session_id)
    session_uuid = uuid.UUID(session_id_str)

    task_row = await task_repo.create(
        tenant_id=tenant_id,
        input_data={"message": message, "metadata": metadata},
        session_id=session_uuid,
    )
    task_id = str(task_row.task_id)

    await task_state.set_status(task_id, "pending", trace_id=context.trace_id)

    logger.info(
        "Webhook task created: task_id=%s event_type=%s tenant_id=%s",
        task_id,
        event_type,
        tenant_id,
    )

    return WebhookTaskResponse(
        task_id=task_id,
        session_id=session_id_str,
        status=TaskStatus.PENDING,
        event_type=event_type,
    )
