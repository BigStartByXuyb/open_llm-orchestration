"""
TenantRepository — 租户数据访问层
TenantRepository — Tenant data access layer.

Layer 4: Only imports from shared/ and storage/postgres/.

租户表不启用 RLS（平台级全局数据）。
The tenants table does NOT use RLS (it's platform-level global data).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestration.storage.postgres.models import TenantRow


class TenantRepository:
    """
    租户 CRUD 操作
    Tenant CRUD operations.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        name: str,
        settings: dict | None = None,
    ) -> TenantRow:
        """
        创建租户 / Create a new tenant.
        """
        row = TenantRow(
            tenant_id=uuid.uuid4(),
            name=name,
            settings=settings or {},
            created_at=datetime.now(timezone.utc),
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def get(self, tenant_id: uuid.UUID) -> TenantRow | None:
        """
        按 ID 查询租户 / Get tenant by ID.
        """
        result = await self._session.execute(
            select(TenantRow).where(TenantRow.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def get_all(self) -> list[TenantRow]:
        """
        获取所有租户 / Get all tenants.
        """
        result = await self._session.execute(select(TenantRow))
        return list(result.scalars().all())

    async def delete(self, tenant_id: uuid.UUID) -> bool:
        """
        删除租户；返回是否成功 / Delete tenant; returns whether it existed.
        """
        row = await self.get(tenant_id)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True
