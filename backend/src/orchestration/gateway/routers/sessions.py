"""
会话路由 — GET /sessions/{session_id}, DELETE /sessions/{session_id}
Session router — GET /sessions/{session_id}, DELETE /sessions/{session_id}.

Layer 1: Uses deps for all external access.
"""

from __future__ import annotations

import uuid
import logging

from fastapi import APIRouter, HTTPException

from orchestration.gateway.deps import RunContextDep, SessionRepoDep
from orchestration.gateway.schemas.task_request import (
    SessionResponse,
    SessionListItem,
    SessionListResponse,
    ErrorResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get(
    "",
    response_model=SessionListResponse,
)
async def list_sessions(
    context: RunContextDep,
    session_repo: SessionRepoDep,
    limit: int = 50,
    offset: int = 0,
) -> SessionListResponse:
    """
    列出当前租户的所有会话（按最近更新倒序）
    List all sessions for the current tenant (ordered by most recently updated).
    """
    tenant_id = context.tenant_id
    rows = await session_repo.list_sessions(tenant_id, limit=limit, offset=offset)
    items = [
        SessionListItem(
            session_id=str(row.session_id),
            message_count=len(row.messages or []),
            char_count=row.char_count,
            created_at=row.created_at.isoformat() if row.created_at else None,
            updated_at=row.updated_at.isoformat() if row.updated_at else None,
        )
        for row in rows
    ]
    return SessionListResponse(sessions=items, total=len(items))


@router.get(
    "/{session_id}",
    response_model=SessionResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_session(
    session_id: str,
    context: RunContextDep,
    session_repo: SessionRepoDep,
) -> SessionResponse:
    """
    获取会话信息（消息数、字符数）
    Get session info (message count, char count).
    """
    tenant_id = context.tenant_id
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session_id format")

    row = await session_repo.get(sid, tenant_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    messages = row.messages or []
    return SessionResponse(
        session_id=str(row.session_id),
        tenant_id=str(row.tenant_id),
        message_count=len(messages),
        char_count=row.char_count,
        created_at=row.created_at.isoformat() if row.created_at else None,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


@router.delete(
    "/{session_id}",
    status_code=204,
    responses={404: {"model": ErrorResponse}},
)
async def delete_session(
    session_id: str,
    context: RunContextDep,
    session_repo: SessionRepoDep,
) -> None:
    """
    删除会话及其所有消息历史
    Delete session and all its message history.
    """
    tenant_id = context.tenant_id
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session_id format")

    deleted = await session_repo.delete(sid, tenant_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
