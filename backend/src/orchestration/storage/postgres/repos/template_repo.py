"""
路由模板仓库 — 存储每租户的路由模板
Template repository — per-tenant routing template storage.

Layer 4: Only imports from shared/ and storage/postgres/.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestration.shared.errors import TenantIsolationError
from orchestration.storage.postgres.models import TemplateRow


class TemplateRepository:
    """每次请求新建实例（session 由调用方注入） / New instance per request (session injected by caller)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _inject_tenant(self, tenant_id: Any) -> None:
        if not tenant_id:
            raise TenantIsolationError("tenant_id must not be empty")
        # SET does not support bind parameters in PostgreSQL; embed the validated UUID directly
        await self._session.execute(
            text(f"SET LOCAL app.current_tenant_id = '{tenant_id}'")
        )

    async def list_all(self, tenant_id: Any) -> list[TemplateRow]:
        await self._inject_tenant(tenant_id)
        stmt = (
            select(TemplateRow)
            .where(TemplateRow.tenant_id == tenant_id)
            .order_by(TemplateRow.created_at)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get(self, id: uuid.UUID, tenant_id: Any) -> TemplateRow | None:
        await self._inject_tenant(tenant_id)
        stmt = select(TemplateRow).where(
            TemplateRow.id == id,
            TemplateRow.tenant_id == tenant_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        tenant_id: Any,
        name: str,
        capabilities: dict,
    ) -> TemplateRow:
        await self._inject_tenant(tenant_id)
        row = TemplateRow(
            tenant_id=tenant_id,
            name=name,
            capabilities=capabilities,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def update(
        self,
        id: uuid.UUID,
        tenant_id: Any,
        name: str,
        capabilities: dict,
    ) -> TemplateRow | None:
        row = await self.get(id, tenant_id)
        if row is None:
            return None
        row.name = name
        row.capabilities = capabilities
        await self._session.flush()
        return row

    async def delete(self, id: uuid.UUID, tenant_id: Any) -> bool:
        await self._inject_tenant(tenant_id)
        stmt = delete(TemplateRow).where(
            TemplateRow.id == id,
            TemplateRow.tenant_id == tenant_id,
        )
        result = await self._session.execute(stmt)
        return (result.rowcount or 0) > 0
