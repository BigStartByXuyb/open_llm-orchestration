"""
WebSocket 事件模型单元测试
WebSocket event model unit tests.
"""

from __future__ import annotations

import json

import pytest

from orchestration.gateway.schemas.ws_event import (
    BlockCreatedEvent,
    BlockDoneEvent,
    SummaryStartEvent,
    SummaryDeltaEvent,
    SummaryDoneEvent,
    ErrorEvent,
)


def test_block_created_serializes_correctly() -> None:
    ev = BlockCreatedEvent(seq=1, block_id="b1", title="Task 1", worker_type="text")
    data = json.loads(ev.model_dump_json())
    assert data["type"] == "block_created"
    assert data["seq"] == 1
    assert data["block_id"] == "b1"
    assert data["worker_type"] == "text"


def test_block_done_serializes_correctly() -> None:
    ev = BlockDoneEvent(
        seq=2,
        block_id="b1",
        content="Hello world",
        provider_used="anthropic",
        transformer_version="v3",
        tokens_used=42,
        latency_ms=123.4,
        trace_id="trace-abc",
    )
    data = json.loads(ev.model_dump_json())
    assert data["type"] == "block_done"
    assert data["tokens_used"] == 42
    assert data["trace_id"] == "trace-abc"


def test_summary_lifecycle_events() -> None:
    start = SummaryStartEvent(seq=3)
    delta = SummaryDeltaEvent(seq=4, delta="Hello ")
    done = SummaryDoneEvent(seq=5, full_text="Hello world")

    assert json.loads(start.model_dump_json())["type"] == "summary_start"
    assert json.loads(delta.model_dump_json())["delta"] == "Hello "
    assert json.loads(done.model_dump_json())["full_text"] == "Hello world"


def test_error_event() -> None:
    ev = ErrorEvent(seq=10, message="Something went wrong", code="internal_error", block_id="b2")
    data = json.loads(ev.model_dump_json())
    assert data["type"] == "error"
    assert data["block_id"] == "b2"


def test_all_events_have_seq_field() -> None:
    """Every event type must carry a seq field for reconnect support."""
    events = [
        BlockCreatedEvent(seq=1, block_id="b", title="T", worker_type="text"),
        BlockDoneEvent(seq=2, block_id="b", content="x", provider_used="p",
                       transformer_version="v1", tokens_used=0, latency_ms=0.0),
        SummaryStartEvent(seq=3),
        SummaryDeltaEvent(seq=4, delta="d"),
        SummaryDoneEvent(seq=5, full_text="full"),
        ErrorEvent(seq=6, message="err"),
    ]
    for ev in events:
        data = json.loads(ev.model_dump_json())
        assert "seq" in data, f"Missing seq in {ev}"
        assert "type" in data, f"Missing type in {ev}"
