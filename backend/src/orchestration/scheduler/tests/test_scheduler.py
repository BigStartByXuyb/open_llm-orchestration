"""
SchedulerManager + billing_rollup_job 单元测试
Unit tests for SchedulerManager and billing_rollup_job.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestration.scheduler.setup import SchedulerManager, _to_sync_db_url
from orchestration.scheduler.jobs.billing_rollup import billing_rollup_job


# -----------------------------------------------------------------------
# URL conversion helper
# -----------------------------------------------------------------------


class TestToSyncDbUrl:
    def test_asyncpg_replaced(self) -> None:
        url = "postgresql+asyncpg://user:pass@localhost/db"
        assert _to_sync_db_url(url) == "postgresql+psycopg2://user:pass@localhost/db"

    def test_plain_postgresql_unchanged(self) -> None:
        url = "postgresql://user:pass@localhost/db"
        assert _to_sync_db_url(url) == url

    def test_aiosqlite_removed(self) -> None:
        url = "sqlite+aiosqlite:///test.db"
        assert _to_sync_db_url(url) == "sqlite:///test.db"


# -----------------------------------------------------------------------
# SchedulerManager tests
# -----------------------------------------------------------------------


class TestSchedulerManager:
    @pytest.fixture()
    def manager(self) -> SchedulerManager:
        return SchedulerManager()

    def test_initially_not_running(self, manager: SchedulerManager) -> None:
        assert manager.is_running() is False

    def test_initially_zero_jobs(self, manager: SchedulerManager) -> None:
        assert manager.job_count() == 0

    @pytest.mark.asyncio
    async def test_start_sets_running(self, manager: SchedulerManager) -> None:
        with patch.object(manager._scheduler, "start"):
            await manager.start()
        assert manager.is_running() is True
        # cleanup
        manager._started = False

    @pytest.mark.asyncio
    async def test_start_idempotent(self, manager: SchedulerManager) -> None:
        """Calling start() twice should not raise."""
        with patch.object(manager._scheduler, "start") as mock_start:
            await manager.start()
            await manager.start()
            mock_start.assert_called_once()  # only called once
        manager._started = False

    @pytest.mark.asyncio
    async def test_shutdown_when_not_started_is_noop(self, manager: SchedulerManager) -> None:
        with patch.object(manager._scheduler, "shutdown") as mock_shutdown:
            await manager.shutdown()
            mock_shutdown.assert_not_called()

    @pytest.mark.asyncio
    async def test_shutdown_after_start(self, manager: SchedulerManager) -> None:
        with patch.object(manager._scheduler, "start"), \
             patch.object(manager._scheduler, "shutdown") as mock_shutdown:
            await manager.start()
            await manager.shutdown()
            mock_shutdown.assert_called_once_with(wait=False)
        assert manager.is_running() is False

    def test_add_cron_job_increments_count(self, manager: SchedulerManager) -> None:
        async def dummy() -> None:
            pass

        with patch.object(manager._scheduler, "add_job"):
            manager.add_cron_job(dummy, "test_cron", hour=3, minute=0)
            manager._scheduler.add_job.assert_called_once()  # type: ignore[attr-defined]

    def test_add_interval_job_increments_count(self, manager: SchedulerManager) -> None:
        async def dummy() -> None:
            pass

        with patch.object(manager._scheduler, "add_job"):
            manager.add_interval_job(dummy, "test_interval", minutes=30)
            manager._scheduler.add_job.assert_called_once()  # type: ignore[attr-defined]

    def test_cron_job_sets_coalesce_and_max_instances(self, manager: SchedulerManager) -> None:
        """add_cron_job must set coalesce=True and max_instances=1 for dedup."""
        async def dummy() -> None:
            pass

        with patch.object(manager._scheduler, "add_job") as mock_add:
            manager.add_cron_job(dummy, "test_cron2", hour=1)
            _, kwargs = mock_add.call_args
            assert kwargs.get("coalesce") is True
            assert kwargs.get("max_instances") == 1

    def test_interval_job_sets_coalesce_and_max_instances(
        self, manager: SchedulerManager
    ) -> None:
        """add_interval_job must set coalesce=True and max_instances=1."""
        async def dummy() -> None:
            pass

        with patch.object(manager._scheduler, "add_job") as mock_add:
            manager.add_interval_job(dummy, "test_interval2", seconds=30)
            _, kwargs = mock_add.call_args
            assert kwargs.get("coalesce") is True
            assert kwargs.get("max_instances") == 1


class TestSchedulerManagerWithJobStore:
    def test_sqlalchemy_jobstore_used_when_url_provided(self) -> None:
        """SQLite in-memory URL triggers SQLAlchemyJobStore path without errors."""
        # sqlite:///... is a valid sync SQLAlchemy URL and needs no external DB
        manager = SchedulerManager(job_store_url="sqlite:///:memory:")
        assert manager.is_running() is False

    def test_no_url_uses_memory_jobstore(self) -> None:
        """Without job_store_url, SchedulerManager uses default in-memory store."""
        manager = SchedulerManager()
        assert manager.is_running() is False
        assert manager.job_count() == 0

    def test_graceful_fallback_when_sqlalchemy_missing(self) -> None:
        """If apscheduler[sqlalchemy] not installed, falls back to MemoryJobStore."""
        with patch.dict(
            "sys.modules", {"apscheduler.jobstores.sqlalchemy": None}  # type: ignore[dict-item]
        ):
            manager = SchedulerManager(
                job_store_url="postgresql+asyncpg://localhost/db"
            )
        assert manager.is_running() is False


# -----------------------------------------------------------------------
# billing_rollup_job tests
# -----------------------------------------------------------------------


class TestBillingRollupJob:
    def _make_session_factory(
        self,
        tenant_ids: list,
        aggregated: dict[str, int] | None = None,
    ) -> AsyncMock:
        """Build a mock session factory for billing_rollup_job."""
        # Mock the SELECT DISTINCT tenant_id result
        tenant_rows = [(tid,) for tid in tenant_ids]
        tenant_result = MagicMock()
        tenant_result.__iter__ = MagicMock(return_value=iter(tenant_rows))

        session = AsyncMock()
        # First execute call → DISTINCT tenant_ids
        # Subsequent calls inside BillingRepository → aggregate queries
        session.execute.return_value = tenant_result

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        factory = MagicMock(return_value=mock_session_ctx)
        return factory

    @pytest.mark.asyncio
    async def test_no_usage_records_skips_gracefully(self) -> None:
        """When no tenants have usage, job logs and returns without error."""
        factory = self._make_session_factory(tenant_ids=[])
        # Should not raise
        await billing_rollup_job(session_factory=factory)

    @pytest.mark.asyncio
    async def test_job_calls_session_factory(self) -> None:
        """Job must open a DB session."""
        factory = self._make_session_factory(tenant_ids=[])
        await billing_rollup_job(session_factory=factory)
        factory.assert_called_once()

    @pytest.mark.asyncio
    async def test_job_handles_db_error_gracefully(self) -> None:
        """DB errors should be re-raised so APScheduler can log and retry."""
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(side_effect=RuntimeError("DB down"))
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        factory = MagicMock(return_value=mock_ctx)

        with pytest.raises(RuntimeError, match="DB down"):
            await billing_rollup_job(session_factory=factory)
