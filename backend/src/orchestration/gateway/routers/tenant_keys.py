"""
租户 API Key 管理路由 — GET/PUT/DELETE /tenant/keys
Tenant API key management router — GET/PUT/DELETE /tenant/keys.

Layer 1: Uses deps for all external access.
第 1 层：通过 deps 访问所有外部资源。

用途 / Purpose:
  允许每个租户配置自己的 provider API Key，运行时覆盖平台全局配置。
  Allows each tenant to configure per-provider API keys to override the platform global config
  at runtime.

安全说明 / Security note:
  列出时 API Key 仅显示末尾 4 位（其余以 ● 掩码），防止泄露完整密钥。
  When listing, API keys are masked (only last 4 chars shown) to prevent full key exposure.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from orchestration.gateway.deps import (
    RunContextDep,
    TenantKeyRepoDep,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tenant/keys", tags=["tenant-keys"])

_VALID_PROVIDERS = frozenset({
    "anthropic", "openai", "deepseek", "gemini", "jimeng", "kling",
})


# ---------------------------------------------------------------------------
# Request / Response schemas / 请求/响应模型
# ---------------------------------------------------------------------------


class TenantKeyUpsertRequest(BaseModel):
    api_key: str = Field(
        description="Provider API Key（明文，存储时不加密）/ Provider API key (plaintext, stored unencrypted)"
    )


class TenantKeyInfo(BaseModel):
    provider_id: str
    api_key_masked: str  # e.g. "●●●●●●●●abcd"
    configured: bool


class TenantKeyListResponse(BaseModel):
    keys: list[TenantKeyInfo]


class TenantKeyUpsertResponse(BaseModel):
    provider_id: str
    configured: bool


class TenantKeyDeleteResponse(BaseModel):
    provider_id: str
    deleted: bool


# ---------------------------------------------------------------------------
# Helpers / 辅助函数
# ---------------------------------------------------------------------------


def _mask_key(api_key: str) -> str:
    """显示末尾 4 位，其余用 ● 替代 / Show last 4 chars, mask the rest with ●."""
    if len(api_key) <= 4:
        return "●" * len(api_key)
    return "●" * (len(api_key) - 4) + api_key[-4:]


# ---------------------------------------------------------------------------
# Endpoints / 端点
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=TenantKeyListResponse,
)
async def list_tenant_keys(
    context: RunContextDep,
    tenant_key_repo: TenantKeyRepoDep,
) -> TenantKeyListResponse:
    """
    列出当前租户已配置的所有 provider API Key（显示掩码后的密钥值）
    List all configured provider API keys for the current tenant (masked).
    """
    rows = await tenant_key_repo.list_all(context.tenant_id)
    row_map = {r.provider_id: r for r in rows}

    keys = []
    for provider_id in sorted(_VALID_PROVIDERS):
        row = row_map.get(provider_id)
        if row:
            keys.append(TenantKeyInfo(
                provider_id=provider_id,
                api_key_masked=_mask_key(row.api_key),
                configured=True,
            ))
        else:
            keys.append(TenantKeyInfo(
                provider_id=provider_id,
                api_key_masked="",
                configured=False,
            ))

    return TenantKeyListResponse(keys=keys)


@router.put(
    "/{provider_id}",
    response_model=TenantKeyUpsertResponse,
    status_code=200,
    responses={400: {"description": "Unknown provider"}},
)
async def upsert_tenant_key(
    provider_id: str,
    body: TenantKeyUpsertRequest,
    context: RunContextDep,
    tenant_key_repo: TenantKeyRepoDep,
) -> TenantKeyUpsertResponse:
    """
    配置或更新指定 provider 的 API Key
    Configure or update the API key for a specific provider.
    """
    if provider_id not in _VALID_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider '{provider_id}'. Valid: {sorted(_VALID_PROVIDERS)}",
        )
    if not body.api_key.strip():
        raise HTTPException(status_code=400, detail="api_key must not be empty")

    await tenant_key_repo.upsert(
        tenant_id=context.tenant_id,
        provider_id=provider_id,
        api_key=body.api_key,
    )

    logger.info(
        "Tenant API key upserted: tenant_id=%s provider_id=%s",
        context.tenant_id, provider_id,
    )

    return TenantKeyUpsertResponse(provider_id=provider_id, configured=True)


@router.delete(
    "/{provider_id}",
    response_model=TenantKeyDeleteResponse,
)
async def delete_tenant_key(
    provider_id: str,
    context: RunContextDep,
    tenant_key_repo: TenantKeyRepoDep,
) -> TenantKeyDeleteResponse:
    """
    删除指定 provider 的 API Key（不存在时返回 deleted=false，不报错）
    Delete the API key for a specific provider (returns deleted=false if not found, no error).
    """
    deleted = await tenant_key_repo.delete(context.tenant_id, provider_id)

    logger.info(
        "Tenant API key delete: tenant_id=%s provider_id=%s deleted=%s",
        context.tenant_id, provider_id, deleted,
    )

    return TenantKeyDeleteResponse(provider_id=provider_id, deleted=deleted)
