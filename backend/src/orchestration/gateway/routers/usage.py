"""
用量统计路由 — GET /usage
Usage statistics router — GET /usage.

Layer 1: Uses deps for all external access.
第 1 层：通过 deps 访问所有外部资源。

Returns per-provider token aggregates for the authenticated tenant.
返回当前租户的按 provider 聚合 token 用量。
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel

from orchestration.gateway.deps import (
    BillingRepoDep,
    RunContextDep,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/usage", tags=["usage"])


class ProviderUsage(BaseModel):
    provider_id: str
    tokens: int


class UsageSummaryResponse(BaseModel):
    total_tokens: int
    by_provider: list[ProviderUsage]
    since: str | None


@router.get(
    "",
    response_model=UsageSummaryResponse,
)
async def get_usage(
    context: RunContextDep,
    billing_repo: BillingRepoDep,
    since: str | None = Query(
        default=None,
        description="ISO 8601 datetime filter — return records at or after this time",
    ),
) -> UsageSummaryResponse:
    """
    获取当前租户 token 用量统计（按 provider 聚合）
    Get token usage statistics for the current tenant, aggregated by provider.

    Optional query parameter:
      since=<ISO 8601 datetime> — filter to records at or after this timestamp.
      可选参数：since=<ISO 8601 datetime> — 过滤此时间戳之后的记录。

    Response:
      total_tokens  — sum across all providers
      by_provider   — sorted list of {provider_id, tokens}
      since         — echo of the filter param (null if none)
    """
    since_dt: datetime | None = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError:
            since_dt = None

    tenant_id = context.tenant_id
    aggregated: dict[str, int] = await billing_repo.aggregate_by_provider(
        tenant_id, since=since_dt
    )

    by_provider = [
        ProviderUsage(provider_id=pid, tokens=tokens)
        for pid, tokens in sorted(aggregated.items())
    ]
    total = sum(v for v in aggregated.values())

    return UsageSummaryResponse(
        total_tokens=total,
        by_provider=by_provider,
        since=since,
    )
