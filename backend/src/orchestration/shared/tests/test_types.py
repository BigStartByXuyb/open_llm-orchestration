"""
shared/types.py 单元测试
Unit tests for shared/types.py — serialization, char_count, immutability.
"""

import pytest

from orchestration.shared.enums import Capability, ProviderID, Role, TaskStatus
from orchestration.shared.types import (
    CanonicalMessage,
    CanonicalTool,
    ImagePart,
    ProviderResult,
    RunContext,
    StreamChunk,
    SubTask,
    TaskPlan,
    TextPart,
    ToolCallPart,
    ToolResultPart,
)


# ---------------------------------------------------------------------------
# ContentPart tests / 内容块测试
# ---------------------------------------------------------------------------


class TestTextPart:
    def test_basic(self) -> None:
        part = TextPart(text="Hello, world!")
        assert part.text == "Hello, world!"

    def test_immutable(self) -> None:
        part = TextPart(text="immutable")
        with pytest.raises(Exception):  # frozen dataclass raises FrozenInstanceError
            part.text = "mutated"  # type: ignore[misc]


class TestImagePart:
    def test_url_image(self) -> None:
        part = ImagePart(url="https://example.com/img.jpg")
        assert part.url == "https://example.com/img.jpg"
        assert part.data == ""

    def test_base64_image(self) -> None:
        part = ImagePart(data="aGVsbG8=", media_type="image/png")
        assert part.data == "aGVsbG8="
        assert part.media_type == "image/png"


class TestToolCallPart:
    def test_basic(self) -> None:
        part = ToolCallPart(
            tool_call_id="call_1",
            tool_name="web_search",
            arguments={"query": "LLM orchestration"},
        )
        assert part.tool_call_id == "call_1"
        assert part.arguments["query"] == "LLM orchestration"


class TestToolResultPart:
    def test_success(self) -> None:
        part = ToolResultPart(tool_call_id="call_1", content="results here")
        assert not part.is_error

    def test_error(self) -> None:
        part = ToolResultPart(tool_call_id="call_1", content="failed", is_error=True)
        assert part.is_error


# ---------------------------------------------------------------------------
# CanonicalMessage tests / 核心消息测试
# ---------------------------------------------------------------------------


class TestCanonicalMessage:
    def test_basic_creation(self) -> None:
        msg = CanonicalMessage(
            role=Role.USER,
            content=[TextPart(text="Hello")],
        )
        assert msg.role == Role.USER
        assert len(msg.content) == 1
        assert msg.schema_version == 1

    def test_default_metadata_is_empty_dict(self) -> None:
        msg = CanonicalMessage(role=Role.SYSTEM, content=[TextPart(text="sys")])
        assert msg.metadata == {}

    def test_metadata_not_shared_between_instances(self) -> None:
        # Each instance should have its own metadata dict (field_factory)
        # Since frozen=True and field(default_factory=dict), each gets its own
        msg1 = CanonicalMessage(role=Role.USER, content=[TextPart(text="a")])
        msg2 = CanonicalMessage(role=Role.USER, content=[TextPart(text="b")])
        assert msg1.metadata is not msg2.metadata

    def test_char_count_text(self) -> None:
        msg = CanonicalMessage(
            role=Role.USER,
            content=[TextPart(text="Hello")],  # 5 chars
        )
        assert msg.char_count() == 5

    def test_char_count_multiple_parts(self) -> None:
        msg = CanonicalMessage(
            role=Role.USER,
            content=[
                TextPart(text="Hello"),        # 5
                TextPart(text=" World"),       # 6
            ],
        )
        assert msg.char_count() == 11

    def test_char_count_image_part_not_counted(self) -> None:
        # ImagePart doesn't contribute to char count (binary data)
        msg = CanonicalMessage(
            role=Role.USER,
            content=[TextPart(text="AB"), ImagePart(url="http://x.com/img.jpg")],
        )
        assert msg.char_count() == 2

    def test_char_count_tool_call(self) -> None:
        part = ToolCallPart(
            tool_call_id="c1",
            tool_name="search",  # 6 chars
            arguments={"q": "hi"},  # str({"q": "hi"}) = "{'q': 'hi'}" = 11 chars
        )
        msg = CanonicalMessage(role=Role.ASSISTANT, content=[part])
        assert msg.char_count() == len("search") + len(str({"q": "hi"}))

    def test_char_count_tool_result(self) -> None:
        part = ToolResultPart(tool_call_id="c1", content="result data")  # 11 chars
        msg = CanonicalMessage(role=Role.TOOL, content=[part])
        assert msg.char_count() == 11

    def test_char_count_empty_content(self) -> None:
        msg = CanonicalMessage(role=Role.USER, content=[])
        assert msg.char_count() == 0

    def test_schema_version_default(self) -> None:
        msg = CanonicalMessage(role=Role.USER, content=[])
        assert msg.schema_version == 1

    def test_immutable(self) -> None:
        msg = CanonicalMessage(role=Role.USER, content=[TextPart(text="hello")])
        with pytest.raises(Exception):
            msg.role = Role.ASSISTANT  # type: ignore[misc]


# ---------------------------------------------------------------------------
# RunContext tests / 运行上下文测试
# ---------------------------------------------------------------------------


class TestRunContext:
    def test_basic_creation(self) -> None:
        ctx = RunContext(
            tenant_id="tenant-1",
            session_id="session-1",
            task_id="task-1",
        )
        assert ctx.tenant_id == "tenant-1"
        assert ctx.trace_id == ""
        assert ctx.user_id == ""

    def test_with_trace_id(self) -> None:
        ctx = RunContext(
            tenant_id="t1",
            session_id="s1",
            task_id="tk1",
            trace_id="trace-abc",
        )
        assert ctx.trace_id == "trace-abc"

    def test_mutable(self) -> None:
        # RunContext is NOT frozen — it can be updated during a run
        ctx = RunContext(tenant_id="t1", session_id="s1", task_id="tk1")
        ctx.trace_id = "new-trace"
        assert ctx.trace_id == "new-trace"


# ---------------------------------------------------------------------------
# SubTask and TaskPlan tests / 子任务和任务计划测试
# ---------------------------------------------------------------------------


class TestSubTask:
    def test_defaults(self) -> None:
        subtask = SubTask(
            subtask_id="st-1",
            description="Search for X",
            capability=Capability.SEARCH,
            context_slice=[],
        )
        assert subtask.provider_id == ProviderID.ANTHROPIC
        assert subtask.transformer_version == "v1"
        assert subtask.depends_on == []
        assert subtask.status == TaskStatus.PENDING

    def test_depends_on_not_shared(self) -> None:
        st1 = SubTask(subtask_id="a", description="a", capability=Capability.TEXT, context_slice=[])
        st2 = SubTask(subtask_id="b", description="b", capability=Capability.TEXT, context_slice=[])
        assert st1.depends_on is not st2.depends_on


class TestTaskPlan:
    def test_basic(self) -> None:
        plan = TaskPlan(
            plan_id="plan-1",
            subtasks=[
                SubTask(
                    subtask_id="st-1",
                    description="do X",
                    capability=Capability.TEXT,
                    context_slice=[],
                )
            ],
        )
        assert len(plan.subtasks) == 1
        assert plan.summary == ""


# ---------------------------------------------------------------------------
# ProviderResult tests / Provider 结果测试
# ---------------------------------------------------------------------------


class TestProviderResult:
    def test_char_count(self) -> None:
        result = ProviderResult(
            subtask_id="st-1",
            provider_id=ProviderID.ANTHROPIC,
            content="Hello World",  # 11 chars
        )
        assert result.char_count() == 11

    def test_defaults(self) -> None:
        result = ProviderResult(
            subtask_id="st-1",
            provider_id=ProviderID.OPENAI,
            content="test",
        )
        assert result.tokens_used == 0
        assert result.latency_ms == 0.0
        assert result.raw_response == {}
        assert result.transformer_version == "v1"


# ---------------------------------------------------------------------------
# CanonicalTool tests / 工具定义测试
# ---------------------------------------------------------------------------


class TestCanonicalTool:
    def test_basic(self) -> None:
        tool = CanonicalTool(
            name="web_search",
            description="Search the web",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        )
        assert tool.name == "web_search"
        assert tool.tool_id == ""
