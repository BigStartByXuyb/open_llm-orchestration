"""
SessionRepository — 对话会话数据访问层（含 RLS 注入）
SessionRepository — Conversation session data access layer (with RLS injection).

Layer 4: Only imports from shared/ and storage/postgres/.

RLS 规则 / RLS rules:
  每个事务开头注入 tenant_id，RLS 策略确保只能看到本租户数据。
  Inject tenant_id at the start of each transaction; RLS policy enforces isolation.
  若 tenant_id 为空，DB 查询报错（默认拒绝策略），不会静默返回全表。
  If tenant_id is empty, the DB query fails (deny_by_default policy), never silent full-table access.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text, desc
from sqlalchemy.ext.asyncio import AsyncSession

from orchestration.shared.errors import TenantIsolationError
from orchestration.shared.types import CanonicalMessage
from orchestration.storage.postgres.models import SessionRow
from orchestration.storage.postgres.serializer import deserialize_messages, serialize_messages


class SessionRepository:
    """
    对话会话 CRUD（带 RLS 注入）
    Conversation session CRUD (with RLS injection).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _inject_tenant(self, tenant_id: str) -> None:
        """
        注入租户 ID 到当前事务（RLS 必须）
        Inject tenant ID into current transaction (required by RLS).
        """
        if not tenant_id:
            raise TenantIsolationError("tenant_id must not be empty")
        await self._session.execute(
            text("SET LOCAL app.current_tenant_id = :tid"),
            {"tid": tenant_id},
        )

    async def create(
        self,
        tenant_id: str,
        messages: list[CanonicalMessage] | None = None,
    ) -> SessionRow:
        """
        创建新会话 / Create a new session.
        """
        await self._inject_tenant(tenant_id)
        msgs = messages or []
        char_count = sum(m.char_count() for m in msgs)
        row = SessionRow(
            session_id=uuid.uuid4(),
            tenant_id=uuid.UUID(tenant_id),
            messages=serialize_messages(msgs),
            char_count=char_count,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def get(self, session_id: uuid.UUID, tenant_id: str) -> SessionRow | None:
        """
        按 ID 查询会话（RLS 确保只能访问本租户数据）
        Get session by ID (RLS ensures only own-tenant data is visible).
        """
        await self._inject_tenant(tenant_id)
        result = await self._session.execute(
            select(SessionRow).where(SessionRow.session_id == session_id)
        )
        return result.scalar_one_or_none()

    async def get_messages(self, session_id: uuid.UUID, tenant_id: str) -> list[CanonicalMessage]:
        """
        获取会话消息列表（反序列化）
        Get session messages (deserialized).
        """
        row = await self.get(session_id, tenant_id)
        if row is None:
            return []
        return deserialize_messages(row.messages or [])

    async def get_messages_paged(
        self,
        session_id: uuid.UUID,
        tenant_id: str,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[CanonicalMessage]:
        """
        获取会话消息的分页子集（反序列化）
        Get a paginated subset of session messages (deserialized).

        offset: 从第 offset 条消息开始（0-based）/ Start from message at index offset (0-based).
        limit:  最多返回 limit 条；None 表示不限 / Max messages to return; None = no limit.

        用途：ws.py 加载最近 MAX_HISTORY_ROUNDS 轮历史，防止大会话 OOM。
        Usage: ws.py loads last MAX_HISTORY_ROUNDS rounds to prevent OOM for long sessions.
        """
        all_messages = await self.get_messages(session_id, tenant_id)
        if not all_messages:
            return []
        sliced = all_messages[offset:]
        if limit is not None:
            sliced = sliced[:limit]
        return sliced

    async def append_messages(
        self,
        session_id: uuid.UUID,
        tenant_id: str,
        new_messages: list[CanonicalMessage],
    ) -> SessionRow:
        """
        追加消息到会话，更新 char_count
        Append messages to session, update char_count.
        """
        await self._inject_tenant(tenant_id)
        row = await self.get(session_id, tenant_id)
        if row is None:
            raise KeyError(f"Session {session_id} not found")

        existing = deserialize_messages(row.messages or [])
        all_messages = existing + new_messages
        row.messages = serialize_messages(all_messages)
        row.char_count = sum(m.char_count() for m in all_messages)
        row.updated_at = datetime.now(timezone.utc)
        await self._session.flush()
        return row

    async def update_messages(
        self,
        session_id: uuid.UUID,
        tenant_id: str,
        messages: list[CanonicalMessage],
    ) -> SessionRow:
        """
        完整替换会话消息（用于截断/摘要后更新）
        Fully replace session messages (used after truncation/summary).
        """
        await self._inject_tenant(tenant_id)
        row = await self.get(session_id, tenant_id)
        if row is None:
            raise KeyError(f"Session {session_id} not found")

        row.messages = serialize_messages(messages)
        row.char_count = sum(m.char_count() for m in messages)
        row.updated_at = datetime.now(timezone.utc)
        await self._session.flush()
        return row

    async def list_sessions(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SessionRow]:
        """
        列出租户的所有会话（按 updated_at 倒序）
        List all sessions for a tenant (ordered by updated_at desc).
        """
        await self._inject_tenant(tenant_id)
        result = await self._session.execute(
            select(SessionRow)
            .order_by(desc(SessionRow.updated_at))
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def delete(self, session_id: uuid.UUID, tenant_id: str) -> bool:
        """
        删除会话；返回是否存在 / Delete session; returns whether it existed.
        """
        await self._inject_tenant(tenant_id)
        row = await self.get(session_id, tenant_id)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True
