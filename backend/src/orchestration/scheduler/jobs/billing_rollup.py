"""
billing_rollup_job — 每日计费汇总 Job
billing_rollup_job — Daily billing rollup job.

Layer 4: Only imports from shared/ and stdlib.
第 4 层：只导入 shared/ 和标准库。

职责 / Responsibilities:
  - 定期汇总各租户的 token 用量（按 provider 聚合）
    Periodically aggregate token usage per tenant (by provider)
  - 写入汇总日志（当前实现：logger；后续可扩展为写入汇总表）
    Write rollup log (current impl: logger; can be extended to write a summary table)
  - 可供 SchedulerManager 注册为 cron job（每天 03:00 UTC）
    Can be registered with SchedulerManager as a cron job (03:00 UTC daily)

设计说明 / Design notes:
  此 job 不直接依赖 AppContainer——通过 session_factory_fn 注入数据库访问，
  满足 Layer 4 边界约束（不导入 wiring/）。
  This job does not depend on AppContainer directly — database access is injected
  via session_factory_fn, satisfying Layer 4 boundary constraints (no wiring/ import).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


async def billing_rollup_job(
    session_factory: Callable[[], Any],
) -> None:
    """
    汇总所有租户的 token 用量并记录日志
    Aggregate token usage for all tenants and log a summary.

    session_factory: 异步 session 工厂（context manager）
                     Async session factory (context manager).
                     由 wiring 层注入，满足 Layer 4 约束。
                     Injected by wiring layer, satisfying Layer 4 constraints.
    """
    from orchestration.storage.billing.billing_repo import BillingRepository  # noqa: PLC0415
    from orchestration.storage.postgres.models import UsageRow  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    run_at = datetime.now(timezone.utc)
    logger.info("billing_rollup_job started at %s", run_at.isoformat())

    try:
        async with session_factory() as session:
            # Fetch distinct tenant IDs that have usage records
            # 获取有用量记录的租户 ID
            result = await session.execute(
                select(UsageRow.tenant_id).distinct()
            )
            tenant_ids = [row[0] for row in result]

            if not tenant_ids:
                logger.info("billing_rollup_job: no usage records found — skipping")
                return

            total_tokens_all = 0
            for tenant_id in tenant_ids:
                repo = BillingRepository(session)
                aggregated = await repo.aggregate_by_provider(tenant_id)
                tenant_total = sum(aggregated.values())
                total_tokens_all += tenant_total
                logger.info(
                    "billing_rollup_job: tenant=%s  total_tokens=%d  by_provider=%s",
                    tenant_id,
                    tenant_total,
                    {k: v for k, v in sorted(aggregated.items())},
                )

            logger.info(
                "billing_rollup_job complete: %d tenants processed, %d total tokens",
                len(tenant_ids),
                total_tokens_all,
            )

    except Exception as exc:
        logger.error("billing_rollup_job failed: %s", exc, exc_info=True)
        raise
