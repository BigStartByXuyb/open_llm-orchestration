"""
Redis 滑动窗口限流存储
Redis sliding window rate limit store.

Layer 4: Only imports from shared/.

算法 / Algorithm:
  使用 Redis Sorted Set 实现滑动窗口：
  Using Redis Sorted Set for sliding window:
    - Key: "rl:{tenant_id}"
    - Score: Unix 时间戳（毫秒）/ Unix timestamp (milliseconds)
    - Member: 唯一请求 ID（UUID）/ Unique request ID (UUID)
  每次检查时删除窗口外的旧记录，统计窗口内请求数。
  On each check, remove entries outside the window, count remaining.
"""

from __future__ import annotations

import time
import uuid


from redis.asyncio import Redis


_KEY_PREFIX = "rl:"
_DEFAULT_WINDOW_MS = 60_000  # 1 minute / 1 分钟
_DEFAULT_TTL_SECONDS = 120   # 2x window as key TTL / 键 TTL 为窗口的 2 倍


def _rl_key(tenant_id: str) -> str:
    return f"{_KEY_PREFIX}{tenant_id}"


class RateLimitStore:
    """
    基于 Redis Sorted Set 的滑动窗口限流存储
    Sliding window rate limit store using Redis Sorted Set.
    """

    def __init__(self, redis: Redis, *, requests_per_minute: int = 60) -> None:  # type: ignore[type-arg]
        self._redis = redis
        self._max_requests = requests_per_minute
        self._window_ms = _DEFAULT_WINDOW_MS

    async def check_and_record(self, tenant_id: str) -> bool:
        """
        检查是否在限流阈值内，若是则记录本次请求并返回 True（允许）。
        Check if within rate limit, record the request if allowed, return True (allowed).

        若超限返回 False（拒绝）。/ Returns False (rejected) if over limit.

        使用 Lua 脚本保证原子性。/ Uses Lua script for atomicity.
        """
        key = _rl_key(tenant_id)
        now_ms = int(time.time() * 1000)
        window_start_ms = now_ms - self._window_ms
        request_id = str(uuid.uuid4())

        # Lua 脚本：原子地删除过期成员、统计数量、条件性添加
        # Lua script: atomically remove expired, count, conditionally add
        lua_script = """
local key = KEYS[1]
local window_start = tonumber(ARGV[1])
local now = tonumber(ARGV[2])
local max_requests = tonumber(ARGV[3])
local member = ARGV[4]
local ttl = tonumber(ARGV[5])

-- 删除窗口外的旧记录 / Remove entries outside window
redis.call('ZREMRANGEBYSCORE', key, '-inf', window_start)

-- 统计当前窗口内请求数 / Count requests in current window
local count = redis.call('ZCARD', key)

if count < max_requests then
    -- 允许：记录本次请求 / Allowed: record this request
    redis.call('ZADD', key, now, member)
    redis.call('EXPIRE', key, ttl)
    return 1
else
    -- 拒绝：超限 / Rejected: over limit
    return 0
end
"""
        result = await self._redis.eval(
            lua_script,
            1,
            key,
            str(window_start_ms),
            str(now_ms),
            str(self._max_requests),
            request_id,
            str(_DEFAULT_TTL_SECONDS),
        )
        return bool(result)

    async def get_current_count(self, tenant_id: str) -> int:
        """
        获取当前窗口内的请求数（不记录请求）
        Get current request count in window (without recording a request).
        """
        key = _rl_key(tenant_id)
        now_ms = int(time.time() * 1000)
        window_start_ms = now_ms - self._window_ms
        await self._redis.zremrangebyscore(key, "-inf", str(window_start_ms))
        return await self._redis.zcard(key)

    async def reset(self, tenant_id: str) -> None:
        """重置限流计数（测试/管理用）/ Reset rate limit (for testing/admin)."""
        await self._redis.delete(_rl_key(tenant_id))
