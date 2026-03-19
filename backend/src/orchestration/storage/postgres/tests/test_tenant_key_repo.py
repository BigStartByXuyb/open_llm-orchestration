"""
TenantKeyRepository 单元测试（★ Sprint 15）
Unit tests for TenantKeyRepository (mocked AsyncSession).
"""

from __future__ import annotations

import unittest.mock
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from orchestration.storage.postgres.models import TenantKeyRow
from orchestration.storage.postgres.repos.tenant_key_repo import TenantKeyRepository


TENANT_ID = uuid.uuid4()


# -----------------------------------------------------------------------
# Test helpers
# -----------------------------------------------------------------------


def _make_session(
    existing_row: TenantKeyRow | None = None,
    all_rows: list[TenantKeyRow] | None = None,
    rowcount: int = 0,
) -> AsyncMock:
    session = AsyncMock()

    query_result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = all_rows or []
    query_result.scalars.return_value = scalars_mock
    query_result.scalar_one_or_none.return_value = existing_row
    query_result.rowcount = rowcount
    session.execute.return_value = query_result
    session.flush = AsyncMock()
    session.add = MagicMock()
    return session


def _make_row(
    provider_id: str = "anthropic",
    api_key: str = "sk-test-key",
) -> TenantKeyRow:
    row = TenantKeyRow()
    row.id = uuid.uuid4()
    row.tenant_id = TENANT_ID
    row.provider_id = provider_id
    row.api_key = api_key
    return row


# -----------------------------------------------------------------------
# TestUpsert
# -----------------------------------------------------------------------


class TestUpsert:
    @pytest.mark.asyncio
    async def test_insert_new_key(self) -> None:
        session = _make_session(existing_row=None)
        repo = TenantKeyRepository(session)

        row = await repo.upsert(TENANT_ID, "openai", "sk-new-key")

        session.add.assert_called_once()
        session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_existing_key(self) -> None:
        existing = _make_row(provider_id="anthropic", api_key="old-key")
        session = _make_session(existing_row=existing)
        repo = TenantKeyRepository(session)

        await repo.upsert(TENANT_ID, "anthropic", "new-key")

        session.add.assert_not_called()
        assert existing.api_key == "new-key"


# -----------------------------------------------------------------------
# TestGet
# -----------------------------------------------------------------------


class TestGet:
    @pytest.mark.asyncio
    async def test_get_existing_returns_row(self) -> None:
        existing = _make_row(provider_id="openai", api_key="sk-abc")
        session = _make_session(existing_row=existing)
        repo = TenantKeyRepository(session)

        result = await repo.get(TENANT_ID, "openai")
        assert result is existing

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self) -> None:
        session = _make_session(existing_row=None)
        repo = TenantKeyRepository(session)

        result = await repo.get(TENANT_ID, "deepseek")
        assert result is None


# -----------------------------------------------------------------------
# TestListAll
# -----------------------------------------------------------------------


class TestListAll:
    @pytest.mark.asyncio
    async def test_list_returns_all_rows(self) -> None:
        rows = [
            _make_row("anthropic", "sk-1"),
            _make_row("openai", "sk-2"),
        ]
        session = _make_session(all_rows=rows)
        repo = TenantKeyRepository(session)

        result = await repo.list_all(TENANT_ID)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_empty_returns_empty(self) -> None:
        session = _make_session(all_rows=[])
        repo = TenantKeyRepository(session)

        result = await repo.list_all(TENANT_ID)
        assert result == []


# -----------------------------------------------------------------------
# TestDelete
# -----------------------------------------------------------------------


class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_existing_returns_true(self) -> None:
        delete_result = MagicMock()
        delete_result.rowcount = 1
        session = AsyncMock()
        session.execute.return_value = delete_result

        repo = TenantKeyRepository(session)
        deleted = await repo.delete(TENANT_ID, "anthropic")
        assert deleted is True

    @pytest.mark.asyncio
    async def test_delete_missing_returns_false(self) -> None:
        delete_result = MagicMock()
        delete_result.rowcount = 0
        session = AsyncMock()
        session.execute.return_value = delete_result

        repo = TenantKeyRepository(session)
        deleted = await repo.delete(TENANT_ID, "nonexistent_provider")
        assert deleted is False


# -----------------------------------------------------------------------
# TestEncryption (N-08)
# -----------------------------------------------------------------------


class TestEncryption:
    """N-08: Verify Fernet encryption of API keys in tenant_key_repo."""

    @pytest.mark.asyncio
    async def test_with_encryption_key_stored_value_differs_from_plaintext(self) -> None:
        """
        When TENANT_KEY_ENCRYPTION_KEY is set, the value stored in DB (api_key on row)
        must not equal the original plaintext API key.
        """
        from cryptography.fernet import Fernet
        from orchestration.shared.config import get_settings

        test_key = Fernet.generate_key().decode()
        plaintext_api_key = "sk-super-secret-key"

        # Patch settings to use our test encryption key
        with unittest.mock.patch.object(
            get_settings(), "TENANT_KEY_ENCRYPTION_KEY", test_key
        ):
            stored_keys: list[str] = []

            # Build a session that captures what api_key is stored
            session = AsyncMock()
            query_result = MagicMock()
            query_result.scalar_one_or_none.return_value = None
            session.execute.return_value = query_result
            session.flush = AsyncMock()

            def capture_add(row: object) -> None:
                stored_keys.append(row.api_key)  # type: ignore[attr-defined]

            session.add = MagicMock(side_effect=capture_add)

            repo = TenantKeyRepository(session)
            # Temporarily override _get_fernet to use our test key
            import orchestration.storage.postgres.repos.tenant_key_repo as repo_module
            original_get_fernet = repo_module._get_fernet

            def patched_get_fernet():
                return Fernet(test_key.encode())

            repo_module._get_fernet = patched_get_fernet
            try:
                await repo.upsert(TENANT_ID, "openai", plaintext_api_key)
            finally:
                repo_module._get_fernet = original_get_fernet

            assert len(stored_keys) == 1
            assert stored_keys[0] != plaintext_api_key, (
                "Encrypted value must differ from plaintext"
            )
            # Verify it can be decrypted back
            fernet = Fernet(test_key.encode())
            decrypted = fernet.decrypt(stored_keys[0].encode()).decode()
            assert decrypted == plaintext_api_key

    @pytest.mark.asyncio
    async def test_without_encryption_key_plaintext_stored_and_returned(self) -> None:
        """
        When TENANT_KEY_ENCRYPTION_KEY is empty, api_key is stored as plaintext
        and get() returns the same plaintext value.
        """
        import orchestration.storage.postgres.repos.tenant_key_repo as repo_module
        original_get_fernet = repo_module._get_fernet
        repo_module._get_fernet = lambda: None  # force plaintext mode

        try:
            plaintext_api_key = "sk-plaintext-key"
            existing_row = _make_row(api_key=plaintext_api_key)
            session = _make_session(existing_row=existing_row)

            repo = TenantKeyRepository(session)
            result = await repo.get(TENANT_ID, "anthropic")

            assert result is not None
            assert result.api_key == plaintext_api_key
        finally:
            repo_module._get_fernet = original_get_fernet
