"""
AppContainer — 依赖注入容器（唯一知道所有具体类的地方）
AppContainer — Dependency injection container (the only place that knows all concrete classes).

Layer 5: May import from all layers.
第 5 层：可以从所有层导入。

职责 / Responsibilities:
  - 构建所有具体实例（Transformer、Adapter、Engine 等）
    Build all concrete instances (Transformer, Adapter, Engine, etc.)
  - 注入依赖（构造函数注入）
    Inject dependencies (constructor injection)
  - 管理 MCP 连接的生命周期
    Manage MCP connection lifecycle
  - 提供 FastAPI 依赖注入所需的单例
    Provide singletons for FastAPI dependency injection

N-09: AppContainer 内部结构通过两个私有 dataclass 分组，降低 God Object 复杂度：
  _InfraComponents     — DB session factory + Redis client
  _PluginCoordinator   — Plugin loader + plugin registry
  外部接口（属性和工厂方法）保持不变。
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, AsyncSession

from orchestration.shared.config import Settings, get_settings
from orchestration.shared.enums import ProviderID
from orchestration.shared.errors import ConfigurationError

# Layer 3: Transformers
from orchestration.transformer.registry import TransformerRegistry
from orchestration.transformer.providers.anthropic_v3.transformer import AnthropicV3Transformer
from orchestration.transformer.providers.openai_v1.transformer import OpenAIV1Transformer
from orchestration.transformer.providers.deepseek_v1.transformer import DeepSeekV1Transformer
from orchestration.transformer.providers.gemini_v1.transformer import GeminiV1Transformer
from orchestration.transformer.providers.jimeng_v1.transformer import JimengV1Transformer
from orchestration.transformer.providers.kling_v1.transformer import KlingV1Transformer

# Layer 4: Provider Adapters
from orchestration.providers.anthropic.adapter import AnthropicAdapter
from orchestration.providers.openai.adapter import OpenAIAdapter
from orchestration.providers.deepseek.adapter import DeepSeekAdapter
from orchestration.providers.gemini.adapter import GeminiAdapter
from orchestration.providers.jimeng.adapter import JimengAdapter
from orchestration.providers.kling.adapter import KlingAdapter

# Layer 4: Storage
from orchestration.storage.postgres.engine import (
    create_engine_from_settings,
    create_session_factory,
    create_tables,
    apply_rls_policies,
)
from orchestration.storage.postgres.repos.session_repo import SessionRepository
from orchestration.storage.postgres.repos.task_repo import TaskRepository
from orchestration.storage.postgres.repos.tenant_repo import TenantRepository
from orchestration.storage.redis.task_state import TaskStateStore
from orchestration.storage.redis.rate_limit_store import RateLimitStore

# Layer 4: Plugins
from orchestration.plugins.registry import PluginRegistry
from orchestration.plugins.loader import PluginLoader
from orchestration.plugins.builtin.code_exec.skill import CodeExecSkill
from orchestration.plugins.builtin.code_exec.iterative_skill import CodeIterativeSkill

# Layer 4: Storage — billing + vector + tenant keys
from orchestration.storage.billing.billing_repo import BillingRepository
from orchestration.storage.vector.vector_store import EmbeddingRepository, RAGRetriever
from orchestration.storage.postgres.repos.tenant_key_repo import TenantKeyRepository

# Layer 4: MCP
from orchestration.mcp.client import MCPClient
from orchestration.mcp.skill_adapter import MCPSkill
from orchestration.mcp.plugin_adapter import MCPPlugin
from orchestration.mcp.registry import MCPRegistry

# Layer 4: Scheduler
from orchestration.scheduler.setup import SchedulerManager
from orchestration.scheduler.jobs.billing_rollup import billing_rollup_job

# Layer 2: Orchestration
from orchestration.orchestration.decomposer import TaskDecomposer
from orchestration.orchestration.router import CapabilityRouter
from orchestration.orchestration.executor import ParallelExecutor
from orchestration.orchestration.aggregator import ResultAggregator
from orchestration.orchestration.engine import OrchestrationEngine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Transformer version map — maps ProviderID to its registered api_version
# Provider → transformer 版本映射
# ---------------------------------------------------------------------------

_PROVIDER_TRANSFORMER_VERSION: dict[ProviderID, str] = {
    ProviderID.ANTHROPIC: "v3",
    ProviderID.OPENAI: "v1",
    ProviderID.DEEPSEEK: "v1",
    ProviderID.GEMINI: "v1",
    ProviderID.JIMENG: "v1",
    ProviderID.KLING: "v1",
}


# ---------------------------------------------------------------------------
# Private infrastructure groupings (N-09 bounded refactoring)
# 私有基础设施分组（N-09 有界重构）
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _InfraComponents:
    """
    DB + Redis 基础设施组件
    Database session factory and Redis client.
    """
    db_engine: AsyncEngine | None = None
    db_session_factory: async_sessionmaker[AsyncSession] | None = None
    redis: Redis | None = None  # type: ignore[type-arg]


@dataclasses.dataclass
class _PluginCoordinator:
    """
    插件加载器 + 插件注册表
    Plugin loader and plugin registry.
    """
    loader: PluginLoader | None = None
    registry: PluginRegistry | None = None


# ---------------------------------------------------------------------------
# Private plugin wrapper — used only within wiring/ (Layer 5)
# 私有插件包装器 — 仅在 wiring/ 内使用（第 5 层）
# ---------------------------------------------------------------------------


class _IterativePlugin:
    """
    将 CodeIterativeSkill 包装为 PluginProtocol 的最小容器
    Minimal PluginProtocol wrapper for CodeIterativeSkill.

    Created here (Layer 5) because it holds a reference to injected adapter/transformer.
    在此处（第 5 层）创建，因为它持有注入的 adapter/transformer 引用。
    """

    plugin_id = "builtin_code_exec_iterative"
    version = "1.0.0"

    def __init__(self, skill: CodeIterativeSkill) -> None:
        self.skills = [skill]

    def on_load(self) -> None:
        pass

    def on_unload(self) -> None:
        pass


class AppContainer:
    """
    应用依赖注入容器 — 构建并持有所有单例实例
    Application DI container — builds and holds all singleton instances.

    Usage / 使用方式:
        container = AppContainer(settings)
        await container.startup()  # 建立连接 / Establish connections
        # ... serve requests ...
        await container.shutdown()  # 清理资源 / Clean up resources
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

        # ----------------------------------------------------------------
        # Infrastructure (N-09: grouped in _InfraComponents)
        # 基础设施（N-09：分组在 _InfraComponents 中）
        # ----------------------------------------------------------------
        self._infra = _InfraComponents()

        # ----------------------------------------------------------------
        # Plugin coordinator (N-09: grouped in _PluginCoordinator)
        # 插件协调器（N-09：分组在 _PluginCoordinator 中）
        # ----------------------------------------------------------------
        self._plugins_coord = _PluginCoordinator()

        # ----------------------------------------------------------------
        # Other registries and state (set during startup)
        # 其他注册表和状态（在 startup 中设置）
        # ----------------------------------------------------------------
        self._transformer_registry: TransformerRegistry | None = None
        self._adapters: dict[ProviderID, Any] | None = None
        self._mcp_clients: list[MCPClient] = []
        self._engine: OrchestrationEngine | None = None
        self._scheduler: SchedulerManager | None = None

    # ------------------------------------------------------------------
    # Startup / Shutdown
    # ------------------------------------------------------------------

    async def startup(self) -> None:
        """
        启动序列：初始化所有组件
        Startup sequence: initialize all components.
        """
        logger.info("AppContainer startup begin")

        # Step 1: Database
        self._infra.db_engine = create_engine_from_settings(self._settings)
        self._infra.db_session_factory = create_session_factory(self._infra.db_engine)
        logger.info("Database engine created")

        # Step 2: Redis
        self._infra.redis = Redis.from_url(  # type: ignore[assignment]
            self._settings.REDIS_URL, decode_responses=True
        )
        logger.info("Redis client created: %s", self._settings.REDIS_URL)

        # Step 3: Transformer registry
        self._transformer_registry = self._build_transformer_registry()
        logger.info("TransformerRegistry built: %d entries", len(self._transformer_registry))

        # Step 4: Provider adapters
        self._adapters = self._build_adapters()
        logger.info("Provider adapters built: %s", list(self._adapters.keys()))

        # Step 5: Plugin registry + built-in plugins
        self._plugins_coord.registry = PluginRegistry()
        self._plugins_coord.loader = PluginLoader(self._plugins_coord.registry)
        self._load_builtin_plugins()

        # Step 6: MCP plugins (async — connect then register)
        await self._connect_mcp_plugins()

        # Step 7: Orchestration engine
        self._engine = self._build_engine()
        logger.info("OrchestrationEngine ready")

        # Step 8: Scheduler — MemoryJobStore (jobs use injected runtime deps, not picklable)
        # 调度器 — 使用内存 JobStore（job 依赖运行时注入的 session_factory，无法 pickle）
        self._scheduler = SchedulerManager()
        self._register_scheduled_jobs()
        await self._scheduler.start()
        logger.info("SchedulerManager started")

        logger.info("AppContainer startup complete")

    async def shutdown(self) -> None:
        """
        关闭序列：释放所有资源
        Shutdown sequence: release all resources.
        """
        logger.info("AppContainer shutdown begin")

        # Shutdown scheduler
        if self._scheduler:
            await self._scheduler.shutdown(wait=False)
            self._scheduler = None

        # Close MCP connections
        for client in self._mcp_clients:
            try:
                await client.close()
            except Exception as exc:
                logger.warning("Error closing MCPClient '%s': %s", client.server_id, exc)
        self._mcp_clients.clear()

        # Unload all plugins
        if self._plugins_coord.loader:
            self._plugins_coord.loader.unload_all()

        # Close Redis
        if self._infra.redis:
            await self._infra.redis.aclose()
            self._infra.redis = None

        # Dispose DB engine
        if self._infra.db_engine:
            await self._infra.db_engine.dispose()
            self._infra.db_engine = None

        logger.info("AppContainer shutdown complete")

    # ------------------------------------------------------------------
    # Property accessors (for FastAPI deps)
    # 属性访问器（供 FastAPI deps 使用）
    # ------------------------------------------------------------------

    @property
    def engine(self) -> OrchestrationEngine:
        if self._engine is None:
            raise RuntimeError("AppContainer not started — call await startup() first")
        return self._engine

    @property
    def db_session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._infra.db_session_factory is None:
            raise RuntimeError("AppContainer not started")
        return self._infra.db_session_factory

    @property
    def redis(self) -> Redis:  # type: ignore[type-arg]
        if self._infra.redis is None:
            raise RuntimeError("AppContainer not started")
        return self._infra.redis

    @property
    def plugin_registry(self) -> PluginRegistry:
        if self._plugins_coord.registry is None:
            raise RuntimeError("AppContainer not started")
        return self._plugins_coord.registry

    @property
    def plugin_loader(self) -> PluginLoader:
        if self._plugins_coord.loader is None:
            raise RuntimeError("AppContainer not started")
        return self._plugins_coord.loader

    @property
    def settings(self) -> Settings:
        return self._settings

    # ------------------------------------------------------------------
    # Repo factories (new repo per request — session injected by caller)
    # 仓库工厂（每次请求新建 repo — session 由调用方注入）
    # ------------------------------------------------------------------

    def make_session_repo(self, session: AsyncSession) -> SessionRepository:
        return SessionRepository(session)

    def make_task_repo(self, session: AsyncSession) -> TaskRepository:
        return TaskRepository(session)

    def make_tenant_repo(self, session: AsyncSession) -> TenantRepository:
        return TenantRepository(session)

    def make_task_state_store(self) -> TaskStateStore:
        return TaskStateStore(self.redis)

    def make_rate_limit_store(self) -> RateLimitStore:
        return RateLimitStore(
            self.redis,
            requests_per_minute=self._settings.RATE_LIMIT_REQUESTS_PER_MINUTE,
        )

    def make_billing_repo(self, session: AsyncSession) -> BillingRepository:
        """
        计费记录仓库工厂（每次请求新建实例）
        Billing repository factory (new instance per request).
        """
        return BillingRepository(session)

    def make_embedding_repo(self, session: AsyncSession) -> EmbeddingRepository:
        """
        文档向量嵌入仓库工厂（每次请求新建实例）★ Sprint 13
        Document embedding repository factory (new instance per request).
        """
        return EmbeddingRepository(session)

    def make_rag_retriever(self) -> RAGRetriever:
        """
        RAG 检索器工厂（持有 session_factory，按需创建 session）★ Sprint 15
        RAG retriever factory (holds session_factory, creates session on demand).
        """
        return RAGRetriever(self.db_session_factory)

    def make_tenant_key_repo(self, session: AsyncSession) -> TenantKeyRepository:
        """
        租户 API Key 仓库工厂（每次请求新建实例）★ Sprint 15
        Tenant API key repository factory (new instance per request).
        """
        return TenantKeyRepository(session)

    def build_tenant_adapters(
        self, tenant_key_map: dict[str, str]
    ) -> dict[ProviderID, Any]:
        """
        根据租户 API Key 映射构建 adapter 覆盖字典
        Build adapter override dict from tenant API key map.

        tenant_key_map: {provider_id_str: api_key}
        Returns: {ProviderID: adapter_instance} — each instance uses the tenant's API key.
        每个实例使用租户自己的 API Key，不影响全局 adapter。
        """
        _factory_map: dict[str, Any] = {
            ProviderID.ANTHROPIC.value: AnthropicAdapter,
            ProviderID.OPENAI.value: OpenAIAdapter,
            ProviderID.DEEPSEEK.value: DeepSeekAdapter,
            ProviderID.GEMINI.value: GeminiAdapter,
            ProviderID.JIMENG.value: JimengAdapter,
            ProviderID.KLING.value: KlingAdapter,
        }
        overrides: dict[ProviderID, Any] = {}
        for provider_str, api_key in tenant_key_map.items():
            adapter_cls = _factory_map.get(provider_str)
            if adapter_cls is not None:
                try:
                    pid = ProviderID(provider_str)
                    overrides[pid] = adapter_cls(api_key=api_key)
                except (ValueError, Exception) as exc:
                    logger.warning(
                        "Failed to build tenant adapter for provider %r: %s",
                        provider_str, exc,
                    )
        return overrides

    @property
    def scheduler(self) -> SchedulerManager:
        if self._scheduler is None:
            raise RuntimeError("AppContainer not started")
        return self._scheduler

    # ------------------------------------------------------------------
    # Private builders
    # 私有构建方法
    # ------------------------------------------------------------------

    def _build_transformer_registry(self) -> TransformerRegistry:
        registry = TransformerRegistry()
        registry.register(AnthropicV3Transformer())
        registry.register(OpenAIV1Transformer())
        registry.register(DeepSeekV1Transformer())
        registry.register(GeminiV1Transformer())
        registry.register(JimengV1Transformer())
        registry.register(KlingV1Transformer())
        return registry

    def _build_adapters(self) -> dict[ProviderID, Any]:
        s = self._settings
        adapters: dict[ProviderID, Any] = {
            ProviderID.ANTHROPIC: AnthropicAdapter(api_key=s.ANTHROPIC_API_KEY),
            ProviderID.OPENAI: OpenAIAdapter(api_key=s.OPENAI_API_KEY),
            ProviderID.DEEPSEEK: DeepSeekAdapter(api_key=s.DEEPSEEK_API_KEY),
            ProviderID.GEMINI: GeminiAdapter(api_key=s.GEMINI_API_KEY),
            ProviderID.JIMENG: JimengAdapter(api_key=s.JIMENG_API_KEY),
            ProviderID.KLING: KlingAdapter(api_key=s.KLING_API_KEY),
        }
        return adapters

    def _load_builtin_plugins(self) -> None:
        """
        通过 plugin.toml manifest 自动发现并加载内置插件，
        然后补充加载需要依赖注入的插件（CodeIterativeSkill、PromptPlugin）。
        Auto-discover built-in plugins via plugin.toml manifests,
        then separately load DI-requiring plugins (CodeIterativeSkill, PromptPlugin).

        N-02: PromptPlugin 走手动注册路径（prompt_skills/plugin.toml 已删除 — N-05）。
        N-02: PromptPlugin is loaded manually (prompt_skills/plugin.toml removed — N-05).
        """
        assert self._plugins_coord.loader is not None
        # Auto-discover: scans builtin/ subdirs for plugin.toml manifests
        # 自动发现：扫描 builtin/ 子目录中的 plugin.toml
        self._plugins_coord.loader.load_builtin_plugins()
        # DI-injected plugin: stays explicit because it requires adapter + transformer
        # 需要 DI 的插件：保留显式加载，因为需要 adapter + transformer 注入
        self._load_iterative_skill()
        # N-02: Manually register PromptPlugin (not TOML-discoverable — skills/ is not builtin/)
        # N-02：手动注册 PromptPlugin（skills/ 目录不走 TOML 自动发现）
        from orchestration.plugins.prompt_plugin import PromptPlugin  # noqa: PLC0415
        prompt_plugin = PromptPlugin()  # scans default plugins/skills/ directory
        self._plugins_coord.loader.load_plugin_instance(prompt_plugin)
        logger.info("Built-in plugins loaded (auto-discovered + injected)")

    def _load_iterative_skill(self) -> None:
        """
        注册 CodeIterativeSkill — 注入协调者 LLM 作为修复引擎
        Register CodeIterativeSkill — inject coordinator LLM as the fixer engine.

        Uses COORDINATOR_PROVIDER setting (N-10) to select the fixer adapter.
        """
        assert self._plugins_coord.loader is not None
        assert self._adapters is not None
        assert self._transformer_registry is not None

        coordinator_provider_id = self._get_coordinator_provider_id()
        coordinator_adapter = self._adapters[coordinator_provider_id]
        transformer_version = _PROVIDER_TRANSFORMER_VERSION.get(coordinator_provider_id, "v1")
        coordinator_transformer = self._transformer_registry.get(
            coordinator_provider_id, transformer_version
        )
        exec_skill = CodeExecSkill()
        iterative_skill = CodeIterativeSkill(
            exec_skill=exec_skill,
            fixer_adapter=coordinator_adapter,
            fixer_transformer=coordinator_transformer,
            coordinator_model=self._settings.COORDINATOR_MODEL,
        )
        # Wrap in a minimal plugin container for PluginLoader compatibility
        # 包装为最小 Plugin 容器供 PluginLoader 使用
        plugin = _IterativePlugin(iterative_skill)
        self._plugins_coord.loader.load_plugin_instance(plugin)

    def _get_coordinator_provider_id(self) -> ProviderID:
        """
        N-10: 从 COORDINATOR_PROVIDER 设置解析 ProviderID，验证 adapter 已配置。
        N-10: Resolve ProviderID from COORDINATOR_PROVIDER setting, validate adapter exists.
        """
        assert self._adapters is not None
        try:
            provider_id = ProviderID(self._settings.COORDINATOR_PROVIDER)
        except ValueError:
            raise ConfigurationError(
                f"COORDINATOR_PROVIDER '{self._settings.COORDINATOR_PROVIDER}' is not a valid "
                f"ProviderID. Valid values: {[p.value for p in ProviderID]}",
            )
        if provider_id not in self._adapters:
            raise ConfigurationError(
                f"Coordinator provider '{provider_id.value}' not configured or API key missing. "
                f"Set ORCH_{provider_id.value.upper()}_API_KEY.",
            )
        return provider_id

    async def _connect_mcp_plugins(self) -> None:
        assert self._plugins_coord.loader is not None
        # Merge explicit MCP_SERVER_CONFIGS with auto-generated Docker exec config
        # 合并显式 MCP 配置和自动生成的 Docker exec 配置
        mcp_configs = list(self._settings.MCP_SERVER_CONFIGS)
        docker_config = self._build_docker_exec_config()
        if docker_config:
            mcp_configs.append(docker_config)

        mcp_registry = MCPRegistry.from_config_dicts(mcp_configs)

        for config in mcp_registry.all_configs():
            client = MCPClient(config)
            try:
                await client.connect()
                tools = await client.list_tools()
                skills = [MCPSkill(client=client, tool=tool) for tool in tools]
                mcp_plugin = MCPPlugin(
                    server_id=config.server_id,
                    client=client,
                    skills=skills,
                )
                self._plugins_coord.loader.load_plugin_instance(mcp_plugin)
                self._mcp_clients.append(client)
                logger.info(
                    "MCP server '%s' connected with %d tools",
                    config.server_id, len(tools)
                )
            except Exception as exc:
                logger.error(
                    "Failed to connect MCP server '%s': %s — skipping",
                    config.server_id, exc
                )
                # Non-fatal: continue without this MCP server
                # 非致命：继续运行，跳过此 MCP server

    def _register_scheduled_jobs(self) -> None:
        """
        注册所有定时 job（在 SchedulerManager.start() 前调用）
        Register all scheduled jobs (called before SchedulerManager.start()).
        """
        assert self._scheduler is not None
        assert self._infra.db_session_factory is not None

        import functools  # noqa: PLC0415

        factory = self._infra.db_session_factory
        self._scheduler.add_cron_job(
            functools.partial(billing_rollup_job, session_factory=factory),
            job_id="billing_daily_rollup",
            hour=3,
            minute=0,
        )

    def _build_docker_exec_config(self) -> dict | None:
        """
        若 DOCKER_EXEC_MCP_IMAGE 已配置，自动生成 Docker exec MCP server 配置
        If DOCKER_EXEC_MCP_IMAGE is set, auto-generate a Docker exec MCP server config.

        生成的配置等价于在 ORCH_MCP_SERVER_CONFIGS 中手动添加：
        Equivalent to manually adding in ORCH_MCP_SERVER_CONFIGS:
          {"server_id": "docker_exec", "transport": "stdio",
           "command": "docker", "args": ["run", "--rm", "-i",
           "--memory=...", "--cpus=...", "<image>"]}
        """
        image = self._settings.DOCKER_EXEC_MCP_IMAGE.strip()
        if not image:
            return None
        return {
            "server_id": "docker_exec",
            "transport": "stdio",
            "command": "docker",
            "args": [
                "run", "--rm", "-i",
                f"--memory={self._settings.DOCKER_EXEC_MEMORY_LIMIT}",
                f"--cpus={self._settings.DOCKER_EXEC_CPU_LIMIT}",
                "--network=none",   # 沙箱禁止网络访问 / Sandbox: no network
                image,
            ],
        }

    def _build_engine(self) -> OrchestrationEngine:
        assert self._transformer_registry is not None
        assert self._adapters is not None
        assert self._plugins_coord.registry is not None

        s = self._settings

        # N-10: Use COORDINATOR_PROVIDER setting (default: anthropic)
        # N-10：使用 COORDINATOR_PROVIDER 配置（默认：anthropic）
        coordinator_provider_id = self._get_coordinator_provider_id()
        coordinator_adapter = self._adapters[coordinator_provider_id]
        transformer_version = _PROVIDER_TRANSFORMER_VERSION.get(coordinator_provider_id, "v1")
        coordinator_transformer = self._transformer_registry.get(
            coordinator_provider_id, transformer_version
        )

        # Fallback adapter: OpenAI as backup when primary coordinator fails
        # 备用 adapter：主协调者失败时自动降级到 OpenAI
        # (Only use OpenAI as fallback if it's not already the primary coordinator)
        fallback_provider = ProviderID.OPENAI if coordinator_provider_id != ProviderID.OPENAI else ProviderID.ANTHROPIC
        fallback_adapter = self._adapters.get(fallback_provider)
        fallback_version = _PROVIDER_TRANSFORMER_VERSION.get(fallback_provider, "v1")
        fallback_transformer = (
            self._transformer_registry.get(fallback_provider, fallback_version)
            if fallback_adapter is not None
            else None
        )

        decomposer = TaskDecomposer(
            coordinator_adapter=coordinator_adapter,
            coordinator_transformer=coordinator_transformer,
            settings=s,
            fallback_adapter=fallback_adapter,
            fallback_transformer=fallback_transformer,
        )
        router = CapabilityRouter()
        executor = ParallelExecutor(
            transformer_registry=self._transformer_registry,
            adapters=self._adapters,
            plugin_registry=self._plugins_coord.registry,
            settings=s,
        )
        aggregator = ResultAggregator(
            coordinator_adapter=coordinator_adapter,
            coordinator_transformer=coordinator_transformer,
            settings=s,
        )

        return OrchestrationEngine(
            decomposer=decomposer,
            router=router,
            executor=executor,
            aggregator=aggregator,
            settings=s,
        )
