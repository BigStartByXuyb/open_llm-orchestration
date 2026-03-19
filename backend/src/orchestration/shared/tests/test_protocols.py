"""
shared/protocols.py 单元测试
Unit tests for shared/protocols.py — Protocol compliance and runtime checks.
"""

from typing import Any, AsyncIterator

import pytest

from orchestration.shared.enums import ProviderID
from orchestration.shared.protocols import (
    InstructionTransformer,
    PluginProtocol,
    PluginRegistryProtocol,
    ProviderAdapter,
    SkillProtocol,
    TransformerRegistryProtocol,
)
from orchestration.shared.types import (
    CanonicalMessage,
    CanonicalTool,
    ProviderResult,
    RunContext,
    StreamChunk,
)


# ---------------------------------------------------------------------------
# Minimal concrete implementations for protocol compliance testing
# 最小化具体实现，用于 Protocol 合规性测试
# ---------------------------------------------------------------------------


class ConcreteTransformer:
    """Minimal InstructionTransformer implementation / 最小化 InstructionTransformer 实现"""

    provider_id: ProviderID = ProviderID.ANTHROPIC
    api_version: str = "v3"

    def transform(self, messages: list[CanonicalMessage]) -> dict[str, Any]:
        return {"messages": []}

    def transform_tools(self, tools: list[CanonicalTool]) -> list[dict[str, Any]]:
        return []

    def parse_response(self, raw: dict[str, Any]) -> ProviderResult:
        return ProviderResult(
            subtask_id="",
            provider_id=self.provider_id,
            content=raw.get("content", ""),
        )


class ConcreteAdapter:
    """Minimal ProviderAdapter implementation / 最小化 ProviderAdapter 实现"""

    provider_id: ProviderID = ProviderID.ANTHROPIC

    async def call(self, payload: dict[str, Any], context: RunContext) -> dict[str, Any]:
        return {}

    async def stream(
        self, payload: dict[str, Any], context: RunContext
    ) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(delta="hello")


class ConcreteSkill:
    """Minimal SkillProtocol implementation / 最小化 SkillProtocol 实现"""

    skill_id: str = "web_search"
    description: str = "Search the web"
    input_schema: dict[str, Any] = {"type": "object"}
    output_schema: dict[str, Any] = {"type": "object"}

    async def execute(self, inputs: dict[str, Any], context: RunContext) -> dict[str, Any]:
        return {"results": []}


class ConcretePlugin:
    """Minimal PluginProtocol implementation / 最小化 PluginProtocol 实现"""

    plugin_id: str = "test_plugin"
    version: str = "1.0.0"
    skills: list[SkillProtocol] = []

    def on_load(self) -> None:
        pass

    def on_unload(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Protocol compliance tests / Protocol 合规性测试
# ---------------------------------------------------------------------------


class TestInstructionTransformerProtocol:
    def test_runtime_checkable(self) -> None:
        impl = ConcreteTransformer()
        assert isinstance(impl, InstructionTransformer)

    def test_has_required_attributes(self) -> None:
        impl = ConcreteTransformer()
        assert hasattr(impl, "provider_id")
        assert hasattr(impl, "api_version")
        assert hasattr(impl, "transform")
        assert hasattr(impl, "transform_tools")
        assert hasattr(impl, "parse_response")

    def test_provider_id_is_provider_id(self) -> None:
        impl = ConcreteTransformer()
        assert isinstance(impl.provider_id, ProviderID)

    def test_transform_returns_dict(self) -> None:
        impl = ConcreteTransformer()
        result = impl.transform([])
        assert isinstance(result, dict)

    def test_transform_tools_returns_list(self) -> None:
        impl = ConcreteTransformer()
        result = impl.transform_tools([])
        assert isinstance(result, list)


class TestProviderAdapterProtocol:
    def test_runtime_checkable(self) -> None:
        impl = ConcreteAdapter()
        assert isinstance(impl, ProviderAdapter)

    def test_has_required_methods(self) -> None:
        impl = ConcreteAdapter()
        assert callable(impl.call)
        assert callable(impl.stream)

    @pytest.mark.asyncio
    async def test_stream_is_async_iterator(self) -> None:
        impl = ConcreteAdapter()
        ctx = RunContext(tenant_id="t", session_id="s", task_id="tk")
        chunks = []
        async for chunk in impl.stream({}, ctx):
            chunks.append(chunk)
        assert len(chunks) >= 0  # Just verify it's iterable


class TestSkillProtocol:
    def test_runtime_checkable(self) -> None:
        impl = ConcreteSkill()
        assert isinstance(impl, SkillProtocol)

    def test_required_attributes(self) -> None:
        impl = ConcreteSkill()
        assert impl.skill_id == "web_search"
        assert isinstance(impl.input_schema, dict)
        assert isinstance(impl.output_schema, dict)

    @pytest.mark.asyncio
    async def test_execute_returns_dict(self) -> None:
        impl = ConcreteSkill()
        ctx = RunContext(tenant_id="t", session_id="s", task_id="tk")
        result = await impl.execute({}, ctx)
        assert isinstance(result, dict)


class TestPluginProtocol:
    def test_runtime_checkable(self) -> None:
        impl = ConcretePlugin()
        assert isinstance(impl, PluginProtocol)

    def test_lifecycle_methods_callable(self) -> None:
        impl = ConcretePlugin()
        impl.on_load()   # Should not raise
        impl.on_unload() # Should not raise

    def test_skills_attribute(self) -> None:
        impl = ConcretePlugin()
        assert isinstance(impl.skills, list)


class TestMissingAttributeNotProtocol:
    """对象缺少必要属性时，不满足 Protocol / Objects missing required attributes don't satisfy Protocol."""

    def test_class_without_provider_id_not_transformer(self) -> None:
        class BadTransformer:
            api_version = "v1"
            def transform(self, messages: Any) -> dict[str, Any]: return {}
            def transform_tools(self, tools: Any) -> list[dict[str, Any]]: return []
            def parse_response(self, raw: Any) -> Any: return None

        # runtime_checkable only checks for method/attribute presence at runtime
        # but provider_id is a class-level attribute, not a method
        bad = BadTransformer()
        # It lacks provider_id attribute, so should NOT be instance
        assert not isinstance(bad, InstructionTransformer)
