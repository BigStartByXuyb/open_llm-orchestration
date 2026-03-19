"""
Redis 存储集成测试（testcontainers，需要 Docker）
Redis storage integration tests (testcontainers, requires Docker).
"""

from __future__ import annotations

import asyncio

import pytest
from redis.asyncio import Redis

from orchestration.storage.redis.task_state import TaskStateStore
from orchestration.storage.redis.rate_limit_store import RateLimitStore
from tests.integration.conftest import integration, skip_if_no_docker

pytestmark = [integration, skip_if_no_docker]


@pytest.fixture(scope="module")
def redis_client(redis_container):
    """连接到 testcontainer Redis 实例。"""
    url = redis_container.get_connection_url()
    return Redis.from_url(url)


# ---------------------------------------------------------------------------
# TaskStateStore tests
# ---------------------------------------------------------------------------

class TestTaskStateStore:
    @pytest.mark.asyncio
    async def test_set_and_get(self, redis_client: Redis) -> None:
        store = TaskStateStore(redis_client)
        await store.set_status("task-1", "running", trace_id="trace-abc")

        data = await store.get_status("task-1")
        assert data is not None
        assert data["status"] == "running"
        assert data["trace_id"] == "trace-abc"

    @pytest.mark.asyncio
    async def test_nonexistent_returns_none(self, redis_client: Redis) -> None:
        store = TaskStateStore(redis_client)
        result = await store.get_status("no-such-task")
        assert result is None

    @pytest.mark.asyncio
    async def test_exists(self, redis_client: Redis) -> None:
        store = TaskStateStore(redis_client)
        await store.set_status("task-exists", "done")
        assert await store.exists("task-exists") is True
        assert await store.exists("task-missing") is False

    @pytest.mark.asyncio
    async def test_delete(self, redis_client: Redis) -> None:
        store = TaskStateStore(redis_client)
        await store.set_status("task-del", "pending")
        await store.delete("task-del")
        assert await store.exists("task-del") is False

    @pytest.mark.asyncio
    async def test_extra_field(self, redis_client: Redis) -> None:
        store = TaskStateStore(redis_client)
        await store.set_status("task-extra", "done", extra={"subtasks": 3})
        data = await store.get_status("task-extra")
        assert data is not None
        assert data["extra"]["subtasks"] == 3


# ---------------------------------------------------------------------------
# RateLimitStore tests
# ---------------------------------------------------------------------------

class TestRateLimitStore:
    @pytest.mark.asyncio
    async def test_within_limit_returns_true(self, redis_client: Redis) -> None:
        store = RateLimitStore(redis_client, requests_per_minute=5)
        tenant_id = "rl-tenant-1"
        await store.reset(tenant_id)

        for _ in range(5):
            allowed = await store.check_and_record(tenant_id)
            assert allowed is True

    @pytest.mark.asyncio
    async def test_over_limit_returns_false(self, redis_client: Redis) -> None:
        store = RateLimitStore(redis_client, requests_per_minute=3)
        tenant_id = "rl-tenant-2"
        await store.reset(tenant_id)

        for _ in range(3):
            await store.check_and_record(tenant_id)

        denied = await store.check_and_record(tenant_id)
        assert denied is False

    @pytest.mark.asyncio
    async def test_reset_clears_count(self, redis_client: Redis) -> None:
        store = RateLimitStore(redis_client, requests_per_minute=2)
        tenant_id = "rl-tenant-3"
        await store.reset(tenant_id)

        await store.check_and_record(tenant_id)
        await store.check_and_record(tenant_id)
        await store.reset(tenant_id)

        allowed = await store.check_and_record(tenant_id)
        assert allowed is True
