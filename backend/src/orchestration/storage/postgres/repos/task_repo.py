"""
TaskRepository — 任务记录数据访问层（含 RLS 注入）
TaskRepository — Task record data access layer (with RLS injection).

Layer 4: Only imports from shared/ and storage/postgres/.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestration.shared.enums import TaskStatus
from orchestration.shared.errors import TenantIsolationError
from orchestration.storage.postgres.models import TaskRow


class TaskRepository:
    """
    任务 CRUD（带 RLS 注入）
    Task CRUD (with RLS injection).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _inject_tenant(self, tenant_id: str) -> None:
        if not tenant_id:
            raise TenantIsolationError("tenant_id must not be empty")
        await self._session.execute(
            text("SET LOCAL app.current_tenant_id = :tid"),
            {"tid": tenant_id},
        )

    async def create(
        self,
        tenant_id: str,
        input_data: dict,
        *,
        session_id: uuid.UUID | None = None,
    ) -> TaskRow:
        """
        创建任务记录，状态为 pending
        Create task record with pending status.
        """
        await self._inject_tenant(tenant_id)
        row = TaskRow(
            task_id=uuid.uuid4(),
            tenant_id=uuid.UUID(tenant_id),
            session_id=session_id,
            status=TaskStatus.PENDING.value,
            input_data=input_data,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def get(self, task_id: uuid.UUID, tenant_id: str) -> TaskRow | None:
        """
        按 ID 查询任务（RLS 隔离）
        Get task by ID (RLS isolated).
        """
        await self._inject_tenant(tenant_id)
        result = await self._session.execute(
            select(TaskRow).where(TaskRow.task_id == task_id)
        )
        return result.scalar_one_or_none()

    async def update_status(
        self,
        task_id: uuid.UUID,
        tenant_id: str,
        status: TaskStatus,
        *,
        result: dict | None = None,
        error_message: str | None = None,
        task_plan: dict | None = None,
    ) -> TaskRow:
        """
        更新任务状态（及可选结果/错误/计划）
        Update task status (and optionally result/error/plan).
        """
        await self._inject_tenant(tenant_id)
        row = await self.get(task_id, tenant_id)
        if row is None:
            raise KeyError(f"Task {task_id} not found")

        row.status = status.value
        row.updated_at = datetime.now(timezone.utc)
        if result is not None:
            row.result = result
        if error_message is not None:
            row.error_message = error_message
        if task_plan is not None:
            row.task_plan = task_plan
        await self._session.flush()
        return row

    async def list_by_tenant(
        self,
        tenant_id: str,
        *,
        status: TaskStatus | None = None,
        limit: int = 50,
    ) -> list[TaskRow]:
        """
        列出租户任务（可按状态过滤）
        List tenant tasks (optionally filtered by status).
        """
        await self._inject_tenant(tenant_id)
        stmt = select(TaskRow).order_by(TaskRow.created_at.desc()).limit(limit)
        if status is not None:
            stmt = stmt.where(TaskRow.status == status.value)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
