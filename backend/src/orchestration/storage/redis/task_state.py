"""
Redis 任务状态存储（实时状态缓存，补充 PostgreSQL 持久化）
Redis task state store (real-time status cache, complement to PostgreSQL persistence).

Layer 4: Only imports from shared/.

设计 / Design:
  - Key: "task:{task_id}" → Redis Hash
  - Fields: status, error, updated_at, trace_id
  - TTL: 24 小时（任务完成后自动清理）
    TTL: 24 hours (auto-cleanup after task completion)
  - 不替代 DB，仅作为快速状态查询缓存
    Does NOT replace DB; used as fast status query cache only
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis


_KEY_PREFIX = "task:"
_EVENTS_KEY_PREFIX = "task_events:"
_DEFAULT_TTL_SECONDS = 86_400  # 24 hours / 24 小时
_MAX_BUFFERED_EVENTS = 100  # Sprint 18: max events kept per task for WS reconnect


def _task_key(task_id: str) -> str:
    return f"{_KEY_PREFIX}{task_id}"


def _events_key(task_id: str) -> str:
    """Redis list key for buffered WS events per task (Sprint 18)."""
    return f"{_EVENTS_KEY_PREFIX}{task_id}"


class TaskStateStore:
    """
    Redis 任务状态缓存
    Redis task state cache.
    """

    def __init__(self, redis: Redis) -> None:  # type: ignore[type-arg]
        self._redis = redis

    async def set_status(
        self,
        task_id: str,
        status: str,
        *,
        error: str = "",
        trace_id: str = "",
        extra: dict[str, Any] | None = None,
    ) -> None:
        """
        设置任务状态（创建或更新）
        Set task status (create or update).
        """
        key = _task_key(task_id)
        data: dict[str, str] = {
            "status": status,
            "error": error,
            "trace_id": trace_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if extra:
            data["extra"] = json.dumps(extra)

        async with self._redis.pipeline(transaction=True) as pipe:
            await pipe.hset(key, mapping=data)  # type: ignore[arg-type]
            await pipe.expire(key, _DEFAULT_TTL_SECONDS)
            await pipe.execute()

    async def get_status(self, task_id: str) -> dict[str, Any] | None:
        """
        获取任务状态；不存在时返回 None
        Get task status; returns None if not found.
        """
        key = _task_key(task_id)
        data = await self._redis.hgetall(key)
        if not data:
            return None
        # Redis 返回 bytes，需解码 / Redis returns bytes, decode needed
        decoded: dict[str, Any] = {
            k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v
            for k, v in data.items()
        }
        if "extra" in decoded:
            try:
                decoded["extra"] = json.loads(decoded["extra"])
            except (json.JSONDecodeError, TypeError):
                pass
        return decoded

    async def delete(self, task_id: str) -> None:
        """删除任务状态 / Delete task state."""
        await self._redis.delete(_task_key(task_id))

    async def exists(self, task_id: str) -> bool:
        """检查任务状态是否存在 / Check if task state exists."""
        return bool(await self._redis.exists(_task_key(task_id)))

    # ------------------------------------------------------------------
    # Sprint 18: Event buffer for WS reconnect / Sprint 18：WS 重连事件缓冲
    # ------------------------------------------------------------------

    async def push_event(self, task_id: str, event_json: str, seq: int) -> None:
        """
        将 WS 事件 JSON 追加到任务事件缓冲列表（最多保留 _MAX_BUFFERED_EVENTS 条）。
        Append a WS event JSON to the task event buffer list (capped at _MAX_BUFFERED_EVENTS).

        payload: JSON string of the event including its 'seq' field.
        """
        key = _events_key(task_id)
        async with self._redis.pipeline(transaction=True) as pipe:
            await pipe.rpush(key, event_json)
            await pipe.ltrim(key, -_MAX_BUFFERED_EVENTS, -1)
            await pipe.expire(key, _DEFAULT_TTL_SECONDS)
            await pipe.execute()

    async def get_events_after(self, task_id: str, last_seq: int) -> list[str]:
        """
        返回 seq > last_seq 的所有已缓冲事件 JSON 列表，按 seq 升序。
        Return all buffered event JSONs with seq > last_seq, ordered by seq ascending.

        Used by WS reconnect to replay missed events (Sprint 18).
        """
        key = _events_key(task_id)
        raw_events = await self._redis.lrange(key, 0, -1)
        result: list[str] = []
        for raw in raw_events:
            text = raw.decode() if isinstance(raw, bytes) else raw
            try:
                data = json.loads(text)
                if data.get("seq", 0) > last_seq:
                    result.append(text)
            except (json.JSONDecodeError, TypeError):
                pass
        return result

    async def delete_events(self, task_id: str) -> None:
        """删除任务事件缓冲（任务完成后清理）/ Delete event buffer (cleanup after task done)."""
        await self._redis.delete(_events_key(task_id))
