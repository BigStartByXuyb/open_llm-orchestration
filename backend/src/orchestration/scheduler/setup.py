"""
SchedulerManager — APScheduler 集成（AsyncIOScheduler）
SchedulerManager — APScheduler integration (AsyncIOScheduler).

Layer 4: Only imports from shared/ and stdlib.
第 4 层：只导入 shared/ 和标准库。

职责 / Responsibilities:
  - 封装 APScheduler AsyncIOScheduler 生命周期（start/shutdown）
    Wrap APScheduler AsyncIOScheduler lifecycle (start/shutdown)
  - 提供统一的 add_job 接口，便于 wiring 层注册 job
    Provide uniform add_job interface for wiring layer to register jobs
  - 支持 cron / interval / date 三种触发器
    Support cron / interval / date trigger types
  - 当提供 job_store_url 时使用 SQLAlchemyJobStore 实现多 worker 去重
    Use SQLAlchemyJobStore for distributed deduplication when job_store_url is provided

Usage / 使用方式:
    # 单 worker — 纯内存 JobStore（无 URL）
    manager = SchedulerManager()

    # 多 worker — 共享数据库 JobStore（去重）
    manager = SchedulerManager(job_store_url="postgresql+psycopg2://...")

    manager.add_cron_job(my_async_fn, "daily_rollup", hour=3, minute=0)
    await manager.start()
    # ... serve requests ...
    await manager.shutdown()
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


def _to_sync_db_url(url: str) -> str:
    """
    将异步 SQLAlchemy URL 转换为同步 URL，供 APScheduler SQLAlchemyJobStore 使用。
    Convert async SQLAlchemy URL to sync URL for APScheduler SQLAlchemyJobStore.

    Examples:
        postgresql+asyncpg://...  →  postgresql+psycopg2://...
        postgresql://...          →  postgresql://...  (unchanged)
    """
    return url.replace("+asyncpg", "+psycopg2").replace("+aiosqlite", "")


class SchedulerManager:
    """
    调度器管理器 — 包装 APScheduler AsyncIOScheduler
    Scheduler manager — wraps APScheduler AsyncIOScheduler.

    多 worker 模式 / Multi-worker mode:
        当传入 job_store_url 时，使用 SQLAlchemyJobStore（共享数据库）。
        APScheduler 通过数据库行级锁确保同一 job 在调度窗口内只被一个 worker 执行。
        When job_store_url is provided, SQLAlchemyJobStore (shared DB) is used.
        APScheduler uses DB-level locking so each job fires only once across workers.

    单 worker 模式 / Single-worker mode:
        无 job_store_url 时，退回到纯内存 MemoryJobStore。
        Without job_store_url, falls back to in-memory MemoryJobStore.
    """

    def __init__(self, job_store_url: str | None = None) -> None:
        """
        初始化调度器
        Initialize the scheduler.

        job_store_url: 同步 SQLAlchemy DB URL（如 postgresql+psycopg2://...）。
                       None → 内存 JobStore（单 worker）。
                       Sync SQLAlchemy DB URL. None → in-memory (single worker).
        """
        jobstores: dict[str, Any] = {}

        if job_store_url:
            try:
                from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore  # noqa: PLC0415

                sync_url = _to_sync_db_url(job_store_url)
                jobstores["default"] = SQLAlchemyJobStore(url=sync_url)
                logger.info(
                    "SchedulerManager: using SQLAlchemyJobStore for distributed deduplication"
                )
            except ImportError:
                logger.warning(
                    "apscheduler[sqlalchemy] not installed — falling back to MemoryJobStore. "
                    "Install with: pip install 'apscheduler[sqlalchemy]' psycopg2-binary"
                )

        if jobstores:
            self._scheduler = AsyncIOScheduler(jobstores=jobstores)
        else:
            self._scheduler = AsyncIOScheduler()
        self._started = False

    # ------------------------------------------------------------------
    # Lifecycle / 生命周期
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """
        启动调度器（已启动时为空操作）
        Start the scheduler (no-op if already started).
        """
        if self._started:
            return
        self._scheduler.start()
        self._started = True
        logger.info(
            "SchedulerManager started — %d jobs registered",
            len(self._scheduler.get_jobs()),
        )

    async def shutdown(self, wait: bool = False) -> None:
        """
        关闭调度器
        Shutdown the scheduler.

        wait: True → 等待当前运行的 job 完成 / True → wait for running jobs to finish
        """
        if not self._started:
            return
        self._scheduler.shutdown(wait=wait)
        self._started = False
        logger.info("SchedulerManager shutdown complete")

    # ------------------------------------------------------------------
    # Job registration / Job 注册
    # ------------------------------------------------------------------

    def add_cron_job(
        self,
        func: Callable[..., Coroutine[Any, Any, Any]],
        job_id: str,
        *,
        hour: int | str = "*",
        minute: int | str = 0,
        second: int | str = 0,
        **kwargs: Any,
    ) -> None:
        """
        注册 Cron 定时 job
        Register a cron-triggered job.

        coalesce=True 确保错过的触发点只补跑一次；
        max_instances=1 防止上一轮未完成时触发新实例。
        coalesce=True ensures missed fires are coalesced into one run;
        max_instances=1 prevents overlap if a run takes too long.

        例 / Example:
          add_cron_job(my_fn, "daily_rollup", hour=3, minute=0)  # 每天 03:00
        """
        trigger = CronTrigger(hour=hour, minute=minute, second=second)
        self._scheduler.add_job(
            func,
            trigger=trigger,
            id=job_id,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            **kwargs,
        )
        logger.info("Cron job registered: id=%s  hour=%s minute=%s", job_id, hour, minute)

    def add_interval_job(
        self,
        func: Callable[..., Coroutine[Any, Any, Any]],
        job_id: str,
        *,
        seconds: int = 0,
        minutes: int = 0,
        hours: int = 0,
        **kwargs: Any,
    ) -> None:
        """
        注册间隔执行 job
        Register an interval-triggered job.
        """
        trigger = IntervalTrigger(hours=hours, minutes=minutes, seconds=seconds)
        self._scheduler.add_job(
            func,
            trigger=trigger,
            id=job_id,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            **kwargs,
        )
        logger.info(
            "Interval job registered: id=%s  every %dh %dm %ds",
            job_id, hours, minutes, seconds,
        )

    def job_count(self) -> int:
        """返回已注册 job 数量 / Return number of registered jobs."""
        return len(self._scheduler.get_jobs())

    def is_running(self) -> bool:
        """返回调度器是否已启动 / Return whether the scheduler is running."""
        return self._started
