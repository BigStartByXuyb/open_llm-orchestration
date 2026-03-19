"""
请求/响应 schema 单元测试
Request/response schema unit tests.
"""

from __future__ import annotations

import pytest

from orchestration.gateway.schemas.task_request import (
    TaskCreateRequest,
    TaskCreateResponse,
    TaskStatusResponse,
    SessionResponse,
    PluginInfo,
    PluginListResponse,
    ErrorResponse,
)
from orchestration.shared.enums import TaskStatus


def test_task_create_request_requires_message() -> None:
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        TaskCreateRequest(message="")  # min_length=1


def test_task_create_request_defaults() -> None:
    req = TaskCreateRequest(message="hello")
    assert req.session_id == ""
    assert req.metadata == {}


def test_task_create_response() -> None:
    resp = TaskCreateResponse(
        task_id="t1",
        session_id="s1",
        status=TaskStatus.PENDING,
    )
    assert resp.status == TaskStatus.PENDING
    assert resp.message == "Task created"


def test_task_status_response() -> None:
    resp = TaskStatusResponse(
        task_id="t1",
        session_id="s1",
        status=TaskStatus.DONE,
        result="summary text",
    )
    assert resp.result == "summary text"
    assert resp.error is None


def test_session_response() -> None:
    resp = SessionResponse(
        session_id="s1",
        tenant_id="tenant-abc",
        message_count=5,
        char_count=1000,
    )
    assert resp.message_count == 5


def test_plugin_list_response() -> None:
    resp = PluginListResponse(
        plugins=[
            PluginInfo(plugin_id="p1", version="1.0.0", skills=["skill_a"]),
        ],
        total=1,
    )
    assert resp.total == 1
    assert resp.plugins[0].plugin_id == "p1"


def test_error_response() -> None:
    err = ErrorResponse(error="Something went wrong")
    assert err.code == "internal_error"
    assert err.detail is None
