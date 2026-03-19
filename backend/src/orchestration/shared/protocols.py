"""
跨模块 Protocol 定义 — 系统所有接口契约的唯一来源
Cross-module Protocol definitions — single source of truth for all interface contracts.

Layer 0: Only imports from shared/. No concrete implementations here.
第 0 层：仅从 shared/ 导入，此处无任何具体实现。

Design principle / 设计原则:
  - Transformer knows nothing about networking.
    Transformer 对网络层一无所知。
  - Adapter knows nothing about CanonicalMessage.
    Adapter 对 CanonicalMessage 一无所知。
  - Orchestration knows only these Protocols, not concrete classes.
    Orchestration 只知道这些 Protocol，不知道具体类。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, AsyncIterator, Protocol, runtime_checkable

from orchestration.shared.enums import ProviderID
from orchestration.shared.types import (
    CanonicalMessage,
    CanonicalTool,
    ProviderResult,
    RunContext,
    StreamChunk,
)

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Transformer Protocol / 指令转换 Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class InstructionTransformer(Protocol):
    """
    指令转换协议 — 将统一内部格式转换为 provider 专有 API 格式
    Instruction transformer protocol — converts unified internal format to
    provider-specific API format.

    Error boundary / 错误边界:
      - Only raises TransformError (format issues).
        只抛 TransformError（格式问题）。
      - `raw` passed to parse_response is already an HTTP-success response;
        HTTP errors are handled by the Adapter before calling this method.
        传给 parse_response 的 `raw` 已是 HTTP 成功响应；
        HTTP 错误由 Adapter 在调用此方法前处理。
    """

    provider_id: ProviderID
    api_version: str  # e.g., "v3" — used by TransformerRegistry for versioned lookup / 版本标记，用于注册表版本化查找

    def transform(self, messages: list[CanonicalMessage]) -> dict[str, Any]:
        """
        将 CanonicalMessage 列表转换为 provider 专有请求格式
        Convert a list of CanonicalMessages to provider-specific request payload.
        Raises TransformError on failure. 失败时抛 TransformError。
        """
        ...

    def transform_tools(self, tools: list[CanonicalTool]) -> list[dict[str, Any]]:
        """
        将工具定义列表转换为 provider 专有格式
        Convert tool definitions to provider-specific format.
        Returns empty list if provider doesn't support tools.
        如果 provider 不支持工具调用，返回空列表。
        """
        ...

    def parse_response(self, raw: dict[str, Any]) -> ProviderResult:
        """
        将 provider 原始响应解析为标准 ProviderResult
        Parse provider raw response into standardized ProviderResult.
        Raises TransformError on failure. 失败时抛 TransformError。
        `raw` is guaranteed to be an HTTP-success response.
        `raw` 保证是 HTTP 成功响应。
        """
        ...


# ---------------------------------------------------------------------------
# Provider Adapter Protocol / Provider 适配器 Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ProviderAdapter(Protocol):
    """
    Provider 适配器协议 — 处理 HTTP 调用和流式响应
    Provider adapter protocol — handles HTTP calls and streaming responses.

    Error boundary / 错误边界:
      - HTTP 4xx/5xx are translated into ProviderError subclasses.
        HTTP 4xx/5xx 统一翻译为 ProviderError 子类后抛出。
      - Never handles TransformError — that's the executor's responsibility.
        不处理 TransformError — 那是 executor 的责任。
      - `payload` is already provider-specific (output of transformer.transform).
        `payload` 已是 provider 专有格式（transformer.transform 的输出）。
    """

    provider_id: ProviderID

    async def call(self, payload: dict[str, Any], context: RunContext) -> dict[str, Any]:
        """
        发起同步调用，等待完整响应 / Make a synchronous call, wait for complete response.
        Raises ProviderError subclasses for HTTP/network errors.
        HTTP/网络错误时抛 ProviderError 子类。
        """
        ...

    async def stream(
        self,
        payload: dict[str, Any],
        context: RunContext,
    ) -> AsyncIterator[StreamChunk]:
        """
        发起流式调用，逐块产出 / Make a streaming call, yield chunks incrementally.
        Raises ProviderError subclasses for HTTP/network errors.
        HTTP/网络错误时抛 ProviderError 子类。
        """
        ...
        yield StreamChunk(delta="")  # make Protocol typing happy / 满足 Protocol 类型检查


# ---------------------------------------------------------------------------
# Plugin / Skill Protocols / 插件/Skill Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class SkillProtocol(Protocol):
    """
    单个 Skill 的执行协议 / Execution protocol for a single skill.

    Skills bypass the transformer/adapter pipeline entirely.
    Skill 完全绕过 transformer/adapter 管道。
    """

    skill_id: str
    description: str
    input_schema: dict[str, Any]    # JSON Schema for input validation / 输入验证的 JSON Schema
    output_schema: dict[str, Any]   # JSON Schema for output / 输出的 JSON Schema

    async def execute(self, inputs: dict[str, Any], context: RunContext) -> dict[str, Any]:
        """
        执行 Skill / Execute the skill.
        Raises PluginError on failure. 失败时抛 PluginError。
        """
        ...


@runtime_checkable
class PluginProtocol(Protocol):
    """
    插件生命周期协议 — 管理一组 Skill
    Plugin lifecycle protocol — manages a group of skills.

    Loaded/unloaded dynamically by PluginLoader.
    由 PluginLoader 动态加载/卸载。
    """

    plugin_id: str
    version: str
    skills: list[SkillProtocol]

    def on_load(self) -> None:
        """插件加载时调用 / Called when plugin is loaded."""
        ...

    def on_unload(self) -> None:
        """插件卸载时调用 / Called when plugin is unloaded."""
        ...


# ---------------------------------------------------------------------------
# Registry Protocols / 注册表 Protocol
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Document Retriever Protocol / 文档检索 Protocol（RAG）
# ---------------------------------------------------------------------------


class DocumentRetrieverProtocol(Protocol):
    """
    文档检索协议 — 按文本关键词检索相关文档（供 RAG 使用）
    Document retrieval protocol — retrieve relevant documents by text keyword (for RAG).

    实现者 / Implementors:
      - EmbeddingRepository.retrieve_relevant()（storage/vector/vector_store.py）
      - RAGRetriever（storage/vector/vector_store.py，工厂模式，按需创建 session）
    """

    async def retrieve_relevant(
        self,
        tenant_id: Any,
        query: str,
        top_k: int = 5,
    ) -> list[tuple[str, str]]:
        """
        按文本关键词检索相关文档，返回 (doc_id, content) 元组列表（按相关性排列）
        Retrieve relevant documents by keyword, returning (doc_id, content) tuples ordered by
        relevance.
        """
        ...


class TransformerRegistryProtocol(Protocol):
    """
    Transformer 注册表协议 / Transformer registry protocol.
    Used by orchestration layer to look up transformers without knowing
    concrete classes. 编排层用于查找 transformer，无需知道具体类。
    """

    def register(self, transformer: InstructionTransformer) -> None:
        """注册 Transformer / Register a transformer."""
        ...

    def get(self, provider_id: ProviderID, version: str) -> InstructionTransformer:
        """
        查找指定 provider + 版本的 Transformer
        Look up transformer for given provider + version.
        Raises KeyError if not found. 未找到时抛 KeyError。
        """
        ...

    def list_versions(self, provider_id: ProviderID) -> list[str]:
        """列出指定 provider 的所有已注册版本 / List all registered versions for a provider."""
        ...


class PluginRegistryProtocol(Protocol):
    """
    插件注册表协议 / Plugin registry protocol.
    """

    def register_plugin(self, plugin: PluginProtocol) -> None:
        """注册插件 / Register a plugin."""
        ...

    def get_skill(self, skill_id: str) -> SkillProtocol:
        """
        按 skill_id 查找 Skill / Look up skill by skill_id.
        Raises KeyError if not found. 未找到时抛 KeyError。
        """
        ...

    def list_skills(self) -> list[str]:
        """列出所有已注册 Skill 的 ID / List all registered skill IDs."""
        ...
