"""
BillingRepository — 用量计费记录仓库
BillingRepository — usage billing record repository.

Layer 4: Only imports from shared/ and storage/postgres/.

职责 / Responsibilities:
  - 写入 token 用量记录（每个 block_done 事件触发一次）
    Write token usage records (triggered once per block_done event)
  - 按租户聚合用量统计（供前端 /usage 页面使用）
    Aggregate usage statistics by tenant (used by frontend /usage page)
  - 按 provider 分组统计（供计费计算使用）
    Group statistics by provider (used for billing calculation)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestration.shared.errors import TenantIsolationError
from orchestration.storage.postgres.models import UsageRow


class BillingRepository:
    """
    计费记录仓库 — 每次请求新建实例（session 由调用方注入）
    Billing record repository — new instance per request (session injected by caller).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _inject_tenant(self, tenant_id: Any) -> None:
        if not tenant_id:
            raise TenantIsolationError("tenant_id must not be empty")
        await self._session.execute(
            text(f"SET LOCAL app.current_tenant_id = '{tenant_id}'")
        )

    async def record_usage(
        self,
        tenant_id: uuid.UUID,
        provider_id: str,
        tokens_used: int,
        task_id: uuid.UUID | None = None,
        cost_usd: float | None = None,
    ) -> UsageRow:
        """
        写入一条 token 用量记录
        Write a single token usage record.

        通常在 block_done 事件时调用，每个子任务完成后记录一次。
        Typically called on block_done event, once per completed subtask.
        """
        await self._inject_tenant(tenant_id)
        row = UsageRow(
            tenant_id=tenant_id,
            task_id=task_id,
            provider_id=provider_id,
            tokens_used=tokens_used,
            cost_usd=cost_usd,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get_usage_by_tenant(
        self,
        tenant_id: uuid.UUID,
        since: datetime | None = None,
        limit: int = 1000,
    ) -> list[UsageRow]:
        """
        查询租户用量记录（可按时间范围过滤）
        Query usage records for a tenant (optionally filtered by time range).
        """
        await self._inject_tenant(tenant_id)
        stmt = (
            select(UsageRow)
            .where(UsageRow.tenant_id == tenant_id)
            .order_by(UsageRow.created_at.desc())
            .limit(limit)
        )
        if since is not None:
            stmt = stmt.where(UsageRow.created_at >= since)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def aggregate_by_provider(
        self,
        tenant_id: uuid.UUID | str,
        since: datetime | None = None,
    ) -> dict[str, int]:
        """
        按 provider 聚合 token 用量（{provider_id: total_tokens}）
        Aggregate token usage by provider ({provider_id: total_tokens}).

        用于前端 /usage 页面显示各 provider 的用量分布。
        Used for frontend /usage page to display provider usage breakdown.
        """
        await self._inject_tenant(tenant_id)
        stmt = (
            select(UsageRow.provider_id, func.sum(UsageRow.tokens_used).label("total"))
            .where(UsageRow.tenant_id == tenant_id)
            .group_by(UsageRow.provider_id)
        )
        if since is not None:
            stmt = stmt.where(UsageRow.created_at >= since)
        result = await self._session.execute(stmt)
        return {row.provider_id: int(row.total) for row in result}

    async def total_tokens_for_task(
        self,
        tenant_id: uuid.UUID,
        task_id: uuid.UUID,
    ) -> int:
        """
        查询指定任务的总 token 用量
        Get total token usage for a specific task.
        """
        await self._inject_tenant(tenant_id)
        stmt = (
            select(func.sum(UsageRow.tokens_used))
            .where(UsageRow.tenant_id == tenant_id)
            .where(UsageRow.task_id == task_id)
        )
        result = await self._session.execute(stmt)
        total = result.scalar()
        return int(total) if total is not None else 0
