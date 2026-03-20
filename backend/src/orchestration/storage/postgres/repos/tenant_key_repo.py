"""
租户 API Key 仓库 — 存储每租户的 provider API Key
Tenant API key repository — per-tenant provider API key storage.

Layer 4: Only imports from shared/ and storage/postgres/.
第 4 层：只导入 shared/ 和 storage/postgres/。

每个租户可以为每个 provider 配置自己的 API Key，运行时覆盖平台全局配置。
Each tenant can configure their own API key per provider, overriding the platform global config
at runtime.

N-08: API keys are encrypted at rest when ORCH_TENANT_KEY_ENCRYPTION_KEY is configured.
When the key is empty (dev mode), plaintext is stored with a WARNING.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestration.shared.errors import TenantIsolationError
from orchestration.storage.postgres.models import TenantKeyRow

logger = logging.getLogger(__name__)


def _get_fernet() -> Any | None:
    """
    返回 Fernet 实例（如果已配置加密密钥），否则返回 None。
    Return Fernet instance if encryption key is configured, else None.
    """
    from orchestration.shared.config import get_settings  # noqa: PLC0415
    key = get_settings().TENANT_KEY_ENCRYPTION_KEY.strip()
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet  # noqa: PLC0415
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as exc:
        logger.warning("Failed to initialize Fernet for tenant key encryption: %s", exc)
        return None


class TenantKeyRepository:
    """
    租户 API 密钥仓库 — 每次请求新建实例（session 由调用方注入）
    Tenant API key repository — new instance per request (session injected by caller).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _inject_tenant(self, tenant_id: Any) -> None:
        if not tenant_id:
            raise TenantIsolationError("tenant_id must not be empty")
        await self._session.execute(
            text(f"SET LOCAL app.current_tenant_id = '{tenant_id}'")
        )

    # ------------------------------------------------------------------
    # Encryption helpers / 加密辅助方法
    # ------------------------------------------------------------------

    def _encrypt(self, plaintext: str) -> str:
        """
        使用 Fernet 加密 API Key；未配置加密时明文存储并发出 WARNING。
        Encrypt API key with Fernet; store plaintext with WARNING if not configured.
        """
        fernet = _get_fernet()
        if fernet is None:
            logger.warning(
                "ORCH_TENANT_KEY_ENCRYPTION_KEY not set — "
                "storing tenant API key as plaintext (acceptable for dev only)"
            )
            return plaintext
        return fernet.encrypt(plaintext.encode()).decode()

    def _decrypt(self, stored_value: str) -> str:
        """
        使用 Fernet 解密 API Key；未配置加密时原样返回。
        Decrypt API key with Fernet; return as-is if encryption not configured.
        """
        fernet = _get_fernet()
        if fernet is None:
            return stored_value
        try:
            return fernet.decrypt(stored_value.encode()).decode()
        except Exception as exc:
            logger.warning(
                "Failed to decrypt tenant API key (key rotation or plaintext value?): %s", exc
            )
            return stored_value

    # ------------------------------------------------------------------
    # CRUD operations / 增删改查
    # ------------------------------------------------------------------

    async def upsert(
        self,
        tenant_id: Any,
        provider_id: str,
        api_key: str,
    ) -> TenantKeyRow:
        """
        插入或更新租户 API Key（已存在则更新）。写入前加密。
        Insert or update tenant API key (update if exists). Encrypts before storing.
        """
        await self._inject_tenant(tenant_id)
        encrypted_key = self._encrypt(api_key)

        stmt = select(TenantKeyRow).where(
            TenantKeyRow.tenant_id == tenant_id,
            TenantKeyRow.provider_id == provider_id,
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()

        if row is not None:
            row.api_key = encrypted_key
        else:
            row = TenantKeyRow(
                tenant_id=tenant_id,
                provider_id=provider_id,
                api_key=encrypted_key,
            )
            self._session.add(row)

        await self._session.flush()
        return row

    async def get(
        self,
        tenant_id: Any,
        provider_id: str,
    ) -> TenantKeyRow | None:
        """
        获取指定 provider 的 API Key。读取后解密。
        Get API key for the specified provider. Decrypts after reading.
        """
        await self._inject_tenant(tenant_id)
        stmt = select(TenantKeyRow).where(
            TenantKeyRow.tenant_id == tenant_id,
            TenantKeyRow.provider_id == provider_id,
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is not None:
            row.api_key = self._decrypt(row.api_key)
        return row

    async def list_all(self, tenant_id: Any) -> list[TenantKeyRow]:
        """
        列出租户所有已配置的 provider API Key（解密后返回）
        List all configured provider API keys for a tenant (decrypted).
        """
        await self._inject_tenant(tenant_id)
        stmt = select(TenantKeyRow).where(
            TenantKeyRow.tenant_id == tenant_id,
        )
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        for row in rows:
            row.api_key = self._decrypt(row.api_key)
        return rows

    async def delete(
        self,
        tenant_id: Any,
        provider_id: str,
    ) -> bool:
        """
        删除指定 provider 的 API Key（不存在时返回 False）
        Delete API key for the specified provider (returns False if not found).
        """
        await self._inject_tenant(tenant_id)
        stmt = delete(TenantKeyRow).where(
            TenantKeyRow.tenant_id == tenant_id,
            TenantKeyRow.provider_id == provider_id,
        )
        result = await self._session.execute(stmt)
        return (result.rowcount or 0) > 0
