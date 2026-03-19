"""
集成测试 Fixture（testcontainers - 需要 Docker）
Integration test fixtures (testcontainers - requires Docker).

所有集成测试标记为 @pytest.mark.integration，Docker 不可用时自动跳过。
All integration tests marked with @pytest.mark.integration, auto-skipped when Docker unavailable.
"""

from __future__ import annotations

import pytest


def is_docker_available() -> bool:
    """检查 Docker 是否可用 / Check if Docker is available."""
    import os
    import socket

    if os.name == "nt":
        # Windows: check named pipe
        return os.path.exists("\\\\.\\pipe\\docker_engine")
    else:
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect("/var/run/docker.sock")
            s.close()
            return True
        except Exception:
            return False


# 集成测试标记：Docker 不可用时跳过 / Integration mark: skip when Docker unavailable
skip_if_no_docker = pytest.mark.skipif(
    not is_docker_available(),
    reason="Docker is not available; skipping integration tests",
)
integration = pytest.mark.integration


@pytest.fixture(scope="session")
def postgres_container():
    """PostgreSQL testcontainer（session scope，所有集成测试共享）。"""
    try:
        from testcontainers.postgres import PostgresContainer  # type: ignore[import]
    except ImportError:
        pytest.skip("testcontainers[postgres] not installed")

    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg


@pytest.fixture(scope="session")
def redis_container():
    """Redis testcontainer（session scope，所有集成测试共享）。"""
    try:
        from testcontainers.redis import RedisContainer  # type: ignore[import]
    except ImportError:
        pytest.skip("testcontainers[redis] not installed")

    with RedisContainer("redis:7-alpine") as rd:
        yield rd
