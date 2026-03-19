"""
BillingRepository 单元测试（mock AsyncSession）
Unit tests for BillingRepository using mock AsyncSession.

Layer 4 unit tests: mock out the SQLAlchemy session — no real DB needed.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestration.storage.billing.billing_repo import BillingRepository
from orchestration.storage.postgres.models import UsageRow


def _make_session() -> AsyncMock:
    """创建 mock AsyncSession / Create a mock AsyncSession."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


def _make_tenant_id() -> uuid.UUID:
    return uuid.uuid4()


def _make_task_id() -> uuid.UUID:
    return uuid.uuid4()


class TestRecordUsage:
    @pytest.mark.asyncio
    async def test_record_usage_creates_row(self) -> None:
        session = _make_session()
        repo = BillingRepository(session)
        tenant_id = _make_tenant_id()
        task_id = _make_task_id()

        row = await repo.record_usage(
            tenant_id=tenant_id,
            provider_id="anthropic",
            tokens_used=1500,
            task_id=task_id,
        )

        session.add.assert_called_once_with(row)
        session.flush.assert_awaited_once()
        assert row.tenant_id == tenant_id
        assert row.task_id == task_id
        assert row.provider_id == "anthropic"
        assert row.tokens_used == 1500
        assert row.cost_usd is None

    @pytest.mark.asyncio
    async def test_record_usage_with_cost(self) -> None:
        session = _make_session()
        repo = BillingRepository(session)
        tenant_id = _make_tenant_id()

        row = await repo.record_usage(
            tenant_id=tenant_id,
            provider_id="openai",
            tokens_used=800,
            cost_usd=0.0024,
        )

        assert row.cost_usd == pytest.approx(0.0024)
        assert row.task_id is None

    @pytest.mark.asyncio
    async def test_record_usage_without_task(self) -> None:
        session = _make_session()
        repo = BillingRepository(session)
        row = await repo.record_usage(
            tenant_id=_make_tenant_id(),
            provider_id="deepseek",
            tokens_used=300,
        )
        assert row.task_id is None


class TestGetUsageByTenant:
    @pytest.mark.asyncio
    async def test_returns_empty_for_no_records(self) -> None:
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=mock_result)

        repo = BillingRepository(session)
        rows = await repo.get_usage_by_tenant(tenant_id=_make_tenant_id())
        assert rows == []

    @pytest.mark.asyncio
    async def test_returns_rows_for_tenant(self) -> None:
        tenant_id = _make_tenant_id()
        fake_rows = [
            UsageRow(tenant_id=tenant_id, provider_id="anthropic", tokens_used=100),
            UsageRow(tenant_id=tenant_id, provider_id="openai", tokens_used=200),
        ]

        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = fake_rows
        session.execute = AsyncMock(return_value=mock_result)

        repo = BillingRepository(session)
        rows = await repo.get_usage_by_tenant(tenant_id=tenant_id)
        assert len(rows) == 2
        assert rows[0].tokens_used == 100


class TestAggregateByProvider:
    @pytest.mark.asyncio
    async def test_aggregate_sums_by_provider(self) -> None:
        session = _make_session()
        # Mock aggregate result rows
        row1 = MagicMock()
        row1.provider_id = "anthropic"
        row1.total = 1500
        row2 = MagicMock()
        row2.provider_id = "openai"
        row2.total = 800

        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([row1, row2]))
        session.execute = AsyncMock(return_value=mock_result)

        repo = BillingRepository(session)
        agg = await repo.aggregate_by_provider(tenant_id=_make_tenant_id())

        assert agg == {"anthropic": 1500, "openai": 800}

    @pytest.mark.asyncio
    async def test_aggregate_empty_returns_empty_dict(self) -> None:
        session = _make_session()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([]))
        session.execute = AsyncMock(return_value=mock_result)

        repo = BillingRepository(session)
        agg = await repo.aggregate_by_provider(tenant_id=_make_tenant_id())
        assert agg == {}


class TestTotalTokensForTask:
    @pytest.mark.asyncio
    async def test_returns_zero_when_no_records(self) -> None:
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        repo = BillingRepository(session)
        total = await repo.total_tokens_for_task(
            tenant_id=_make_tenant_id(), task_id=_make_task_id()
        )
        assert total == 0

    @pytest.mark.asyncio
    async def test_returns_sum(self) -> None:
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 3700
        session.execute = AsyncMock(return_value=mock_result)

        repo = BillingRepository(session)
        total = await repo.total_tokens_for_task(
            tenant_id=_make_tenant_id(), task_id=_make_task_id()
        )
        assert total == 3700
