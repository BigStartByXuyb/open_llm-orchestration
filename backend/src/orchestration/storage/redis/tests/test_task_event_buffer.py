"""
Sprint 18: TaskStateStore 事件缓冲功能单元测试（使用 fakeredis）
Sprint 18: TaskStateStore event buffer unit tests (using fakeredis).
"""

from __future__ import annotations

import json

import pytest

try:
    import fakeredis.aioredis as fakeredis_async  # type: ignore[import]
    HAS_FAKEREDIS = True
except ImportError:
    HAS_FAKEREDIS = False

from orchestration.storage.redis.task_state import TaskStateStore

skip_if_no_fakeredis = pytest.mark.skipif(
    not HAS_FAKEREDIS,
    reason="fakeredis not installed",
)


def _make_store():
    """Create TaskStateStore backed by a fakeredis instance."""
    redis = fakeredis_async.FakeRedis()
    return TaskStateStore(redis)


@skip_if_no_fakeredis
class TestTaskEventBuffer:
    """Sprint 18: Event buffer for WS reconnect."""

    @pytest.mark.asyncio
    async def test_push_event_and_retrieve_all(self) -> None:
        """Pushed events can be retrieved with get_events_after(last_seq=0)."""
        store = _make_store()
        task_id = "task-buf-1"

        await store.push_event(task_id, json.dumps({"seq": 1, "event": "block_created"}), seq=1)
        await store.push_event(task_id, json.dumps({"seq": 2, "event": "block_done"}), seq=2)
        await store.push_event(task_id, json.dumps({"seq": 3, "event": "summary_done"}), seq=3)

        events = await store.get_events_after(task_id, last_seq=0)
        assert len(events) == 3

    @pytest.mark.asyncio
    async def test_get_events_after_filters_by_seq(self) -> None:
        """get_events_after returns only events with seq > last_seq."""
        store = _make_store()
        task_id = "task-buf-2"

        for seq in range(1, 6):
            await store.push_event(task_id, json.dumps({"seq": seq, "type": "evt"}), seq=seq)

        events = await store.get_events_after(task_id, last_seq=3)
        seqs = [json.loads(e)["seq"] for e in events]
        assert seqs == [4, 5]

    @pytest.mark.asyncio
    async def test_get_events_after_empty_returns_empty(self) -> None:
        """get_events_after on non-existent task returns empty list (not error)."""
        store = _make_store()
        result = await store.get_events_after("nonexistent-task", last_seq=0)
        assert result == []

    @pytest.mark.asyncio
    async def test_delete_events(self) -> None:
        """delete_events removes all buffered events for the task."""
        store = _make_store()
        task_id = "task-del-events"

        await store.push_event(task_id, json.dumps({"seq": 1}), seq=1)
        await store.delete_events(task_id)

        result = await store.get_events_after(task_id, last_seq=0)
        assert result == []

    @pytest.mark.asyncio
    async def test_buffer_capped_at_100_events(self) -> None:
        """Buffer is capped at _MAX_BUFFERED_EVENTS = 100."""
        store = _make_store()
        task_id = "task-cap-test"

        for seq in range(1, 120):
            await store.push_event(task_id, json.dumps({"seq": seq}), seq=seq)

        events = await store.get_events_after(task_id, last_seq=0)
        assert len(events) == 100
        # Should have the most recent 100 (seqs 19-118 → 19..118)
        first_seq = json.loads(events[0])["seq"]
        last_seq_val = json.loads(events[-1])["seq"]
        assert first_seq == 19
        assert last_seq_val == 119  # Not 118 (119 total pushed, last 100 = 19..119)

    @pytest.mark.asyncio
    async def test_no_events_with_last_seq_at_or_beyond_max(self) -> None:
        """get_events_after with last_seq >= latest seq returns empty list."""
        store = _make_store()
        task_id = "task-no-new"

        await store.push_event(task_id, json.dumps({"seq": 5}), seq=5)

        result = await store.get_events_after(task_id, last_seq=5)
        assert result == []

        result = await store.get_events_after(task_id, last_seq=100)
        assert result == []
