"""
系统全局配置 — pydantic-settings 驱动，支持环境变量覆盖
Global system configuration — pydantic-settings driven, supports env var overrides.

Layer 0: No internal imports allowed.

Usage / 使用方式:
  from orchestration.shared.config import settings
  threshold = settings.CONTEXT_TRUNCATION_THRESHOLD

All threshold values are in characters unless noted otherwise.
所有阈值均以字符数为单位，除非另有说明。
"""

from __future__ import annotations

from functools import lru_cache

import logging
import warnings

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    平台配置类 / Platform configuration class.

    Environment variables take precedence over defaults.
    环境变量优先于默认值。
    Prefix: ORCH_ (e.g., ORCH_COORDINATOR_MODEL=claude-sonnet-4-6)
    """

    model_config = SettingsConfigDict(
        env_prefix="ORCH_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -----------------------------------------------------------------------
    # Coordinator / 协调者配置
    # -----------------------------------------------------------------------

    COORDINATOR_MODEL: str = Field(
        default="claude-sonnet-4-6",
        description=(
            "主 LLM 模型 ID，可配置，不硬编码 / "
            "Coordinator LLM model ID, configurable, never hardcoded."
        ),
    )

    MAX_SUBTASKS_PER_PLAN: int = Field(
        default=5,
        description=(
            "每次分解的最大子任务数，超出时抛 TransformError(code='plan_too_large') / "
            "Hard limit on subtasks per decomposition plan. "
            "Exceeding this raises TransformError(code='plan_too_large')."
        ),
    )

    COORDINATOR_DECOMPOSE_PROMPT: str = Field(
        default="",
        description=(
            "自定义分解系统 prompt（空 = 使用代码内置默认）/ "
            "Custom decomposition system prompt (empty = use built-in default). "
            "Env var: ORCH_COORDINATOR_DECOMPOSE_PROMPT"
        ),
    )

    # -----------------------------------------------------------------------
    # Context truncation / 上下文截断配置
    # -----------------------------------------------------------------------

    CONTEXT_TRUNCATION_THRESHOLD: int = Field(
        default=400_000,
        description=(
            "session 历史截断阈值（字符数）/ "
            "Session history truncation threshold (char count). "
            ">80% → sliding window; >95% → summary compression."
        ),
    )

    MAX_SUBTASK_CONTEXT_CHARS: int = Field(
        default=40_000,
        description=(
            "子 Agent 上下文上限（字符数）/ "
            "Max chars allocated to sub-agent context. "
            "Coordinator truncates context_slice if exceeded."
        ),
    )

    # -----------------------------------------------------------------------
    # Aggregator overflow / 聚合阶段溢出配置
    # -----------------------------------------------------------------------

    MAX_RESULT_CHARS_PER_BLOCK: int = Field(
        default=8_000,
        description=(
            "单块 ProviderResult 截断阈值（字符数）≈ 2000 tokens / "
            "Per-block ProviderResult truncation threshold (chars) ≈ 2000 tokens."
        ),
    )

    MAX_SUMMARY_INPUT_CHARS: int = Field(
        default=120_000,
        description=(
            "汇总阶段总输入上限（字符数）≈ 30k tokens / "
            "Max total input chars for summary stage ≈ 30k tokens."
        ),
    )

    # -----------------------------------------------------------------------
    # Provider concurrency / Provider 并发配置
    # -----------------------------------------------------------------------

    PROVIDER_CONCURRENCY_LIMITS: dict[str, int] = Field(
        default={
            "anthropic": 5,
            "openai": 10,
            "deepseek": 8,
            "gemini": 5,
            "jimeng": 3,
            "kling": 2,
        },
        description=(
            "每 provider 的最大并发请求数，由 ParallelExecutor 的 Semaphore 控制 / "
            "Max concurrent requests per provider, controlled by ParallelExecutor Semaphores."
        ),
    )

    # -----------------------------------------------------------------------
    # Resilience — retry / circuit breaker / timeout  韧性配置
    # -----------------------------------------------------------------------

    PROVIDER_MAX_RETRIES: int = Field(
        default=3,
        description=(
            "Provider 调用失败时的最大重试次数（指数退避）/ "
            "Max retry attempts on provider failure (exponential backoff)."
        ),
    )

    PROVIDER_RETRY_BASE_DELAY: float = Field(
        default=1.0,
        description=(
            "指数退避基础延迟（秒），实际延迟 = base * 2^attempt + jitter / "
            "Base delay in seconds for exponential backoff; actual = base * 2^attempt + jitter."
        ),
    )

    PROVIDER_TIMEOUT_SECONDS: float = Field(
        default=60.0,
        description=(
            "每个 provider LLM 调用的超时时间（秒）/ "
            "Timeout in seconds for each provider LLM call."
        ),
    )

    CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = Field(
        default=5,
        description=(
            "熔断器：连续失败次数达到阈值后进入 open 状态 / "
            "Circuit breaker: enter open state after this many consecutive failures."
        ),
    )

    CIRCUIT_BREAKER_RESET_TIMEOUT: float = Field(
        default=30.0,
        description=(
            "熔断器：open 状态持续时间（秒），之后进入 half-open 探测 / "
            "Circuit breaker: seconds to stay open before trying half-open probe."
        ),
    )

    # -----------------------------------------------------------------------
    # Database / 数据库配置
    # -----------------------------------------------------------------------

    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/llm_orchestration",
        description="PostgreSQL 异步连接 URL / PostgreSQL async connection URL.",
    )

    DATABASE_POOL_SIZE: int = Field(
        default=10,
        description="连接池大小 / Connection pool size.",
    )

    DATABASE_MAX_OVERFLOW: int = Field(
        default=20,
        description="连接池最大溢出 / Max pool overflow.",
    )

    # -----------------------------------------------------------------------
    # Redis / Redis 配置
    # -----------------------------------------------------------------------

    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis 连接 URL / Redis connection URL.",
    )

    # -----------------------------------------------------------------------
    # Auth / 认证配置
    # -----------------------------------------------------------------------

    JWT_SECRET_KEY: str = Field(
        default="CHANGE_ME_IN_PRODUCTION",
        description=(
            "JWT 签名密钥 / JWT signing secret. "
            "MUST be overridden in production! 生产环境必须覆盖！"
        ),
    )

    JWT_ALGORITHM: str = Field(
        default="HS256",
        description="JWT 签名算法 / JWT signing algorithm.",
    )

    JWT_EXPIRE_MINUTES: int = Field(
        default=60,
        description="JWT 过期时间（分钟）/ JWT expiry in minutes.",
    )

    # -----------------------------------------------------------------------
    # Environment / 运行环境
    # -----------------------------------------------------------------------

    ENV: str = Field(
        default="development",
        description=(
            "运行环境：development / testing / production / "
            "Runtime environment: development / testing / production. "
            "Controls security checks (e.g. default JWT secret is blocked in production)."
        ),
    )

    # -----------------------------------------------------------------------
    # Rate limiting / 限流配置
    # -----------------------------------------------------------------------

    RATE_LIMIT_REQUESTS_PER_MINUTE: int = Field(
        default=60,
        description="每租户每分钟请求数上限（滑动窗口）/ Max requests per tenant per minute (sliding window).",
    )

    # -----------------------------------------------------------------------
    # Feature flags / 功能开关
    # -----------------------------------------------------------------------

    ENABLE_REVIEW_GATE: bool = Field(
        default=False,
        description=(
            "启用主 Agent 审查门（ReviewGate）/ "
            "Enable coordinator review gate before presenting results. "
            "Requires orchestration/review.py implementation."
        ),
    )

    # -----------------------------------------------------------------------
    # CORS / 跨域配置
    # -----------------------------------------------------------------------

    CORS_ALLOWED_ORIGINS: list[str] = Field(
        default=["*"],
        description=(
            "CORS 允许的来源列表 / CORS allowed origins. "
            "Override in production (e.g. ['https://app.example.com']). "
            "Default '*' is only safe for local development."
        ),
    )

    # -----------------------------------------------------------------------
    # Coordinator provider / 协调者 provider 配置
    # -----------------------------------------------------------------------

    COORDINATOR_PROVIDER: str = Field(
        default="anthropic",
        description=(
            "协调者 LLM 使用的 provider ID / Provider ID for coordinator LLM. "
            "Valid values: anthropic, openai, deepseek, gemini, jimeng, kling. "
            "The corresponding API key must also be configured."
        ),
    )

    # -----------------------------------------------------------------------
    # Tenant key encryption / 租户密钥加密配置
    # -----------------------------------------------------------------------

    TENANT_KEY_ENCRYPTION_KEY: str = Field(
        default="",
        description=(
            "Fernet 对称加密密钥，用于加密租户 API Key / "
            "Fernet key for tenant API key encryption. "
            "Generate with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\". "
            "Empty = disabled (dev only, stores plaintext with WARNING)."
        ),
    )

    # -----------------------------------------------------------------------
    # Observability / 可观测性配置
    # -----------------------------------------------------------------------

    OTEL_EXPORTER_OTLP_ENDPOINT: str = Field(
        default="",
        description=(
            "OpenTelemetry OTLP exporter 地址（Sprint 8 启用）/ "
            "OTel OTLP exporter endpoint (activated in Sprint 8). "
            "Empty string disables export."
        ),
    )

    # -----------------------------------------------------------------------
    # Provider API keys / Provider API 密钥
    # -----------------------------------------------------------------------

    ANTHROPIC_API_KEY: str = Field(default="", description="Anthropic API key.")
    OPENAI_API_KEY: str = Field(default="", description="OpenAI API key.")
    DEEPSEEK_API_KEY: str = Field(default="", description="DeepSeek API key.")
    GEMINI_API_KEY: str = Field(default="", description="Google Gemini API key.")
    JIMENG_API_KEY: str = Field(default="", description="极梦 (Jimeng) API key.")
    KLING_API_KEY: str = Field(default="", description="可灵 (Kling) API key.")

    # -----------------------------------------------------------------------
    # MCP / MCP 服务器配置
    # -----------------------------------------------------------------------

    MCP_SERVER_CONFIGS: list[dict] = Field(
        default=[],
        description=(
            "MCP server 连接配置列表（JSON 数组）/ "
            "MCP server connection config list (JSON array). "
            "Each item: {server_id, transport, command/args/env or url}. "
            "Parsed by wiring/container.py into MCPServerConfig objects."
        ),
    )

    # -----------------------------------------------------------------------
    # Docker 沙箱代码执行 / Docker sandbox code execution
    # -----------------------------------------------------------------------

    DOCKER_EXEC_MCP_IMAGE: str = Field(
        default="",
        description=(
            "Docker 沙箱代码执行 MCP server 镜像名（留空则禁用）/ "
            "Docker image for sandbox code execution MCP server (empty = disabled). "
            "When set, container.py auto-registers a Docker MCP server with id 'docker_exec'. "
            "Example: 'mcp-code-runner:latest'. "
            "Container is started with: docker run --rm -i --memory=256m --cpus=0.5 <image>."
        ),
    )

    DOCKER_EXEC_MEMORY_LIMIT: str = Field(
        default="256m",
        description="Docker 沙箱内存限制 / Docker sandbox memory limit (e.g. '256m', '512m').",
    )

    DOCKER_EXEC_CPU_LIMIT: str = Field(
        default="0.5",
        description="Docker 沙箱 CPU 配额 / Docker sandbox CPU quota (e.g. '0.5' = 50%).",
    )

    # -----------------------------------------------------------------------
    # Webhook / Webhook 配置
    # -----------------------------------------------------------------------

    WEBHOOK_SECRET: str = Field(
        default="",
        description=(
            "Webhook 端点签名密钥（留空则跳过验证）/ "
            "Webhook endpoint signing secret (empty = skip verification). "
            "If set, callers must include X-Webhook-Secret header with this value."
        ),
    )

    # -----------------------------------------------------------------------
    # RAG / 检索增强生成配置
    # -----------------------------------------------------------------------

    RAG_TOP_K: int = Field(
        default=5,
        description=(
            "RAG 检索时返回的最大文档数 / "
            "Max number of documents to retrieve for RAG context enrichment. "
            "Set to 0 to disable RAG retrieval entirely."
        ),
    )

    # -----------------------------------------------------------------------
    # Session history / 会话历史分页配置
    # -----------------------------------------------------------------------

    MAX_HISTORY_ROUNDS: int = Field(
        default=50,
        description=(
            "加载会话历史时的最大轮次数（每轮 = 1 条用户消息 + 1 条 assistant 回复）。"
            "超出的历史保留在 DB，仅加载滑动窗口以避免 OOM。\n"
            "Max conversation history rounds to load (1 round = user + assistant). "
            "Older history stays in DB; only the sliding window is loaded to prevent OOM."
        ),
    )

    # -----------------------------------------------------------------------
    # Security validators / 安全校验器
    # -----------------------------------------------------------------------

    _DEFAULT_JWT_SECRET = "CHANGE_ME_IN_PRODUCTION"

    @model_validator(mode="after")
    def _validate_jwt_secret(self) -> "Settings":
        """
        生产环境使用默认 JWT 密钥时阻止启动；开发环境仅打印 WARNING。
        Block startup if production uses the default JWT secret; warn in development.

        安全防线 / Security guard:
          - production: 抛出 ValueError，阻止进程启动
            ValueError raised, blocking process start
          - development/testing: 打印 WARNING，允许继续
            WARNING printed, allows continuing
        """
        if self.JWT_SECRET_KEY == self._DEFAULT_JWT_SECRET:
            env = self.ENV.lower()
            if env not in ("testing", "development", "dev", "test"):
                raise ValueError(
                    "SECURITY ERROR: JWT_SECRET_KEY is set to the default value "
                    f"'{self._DEFAULT_JWT_SECRET}'. "
                    "This is NOT safe for production. "
                    "Set ORCH_JWT_SECRET_KEY to a strong random secret before starting. "
                    "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
                )
            # Development / testing: emit a warning but allow startup
            # 开发/测试环境：发出警告但允许启动
            warnings.warn(
                "JWT_SECRET_KEY is using the insecure default value. "
                "This is acceptable only for local development. "
                "Set ORCH_JWT_SECRET_KEY in production.",
                UserWarning,
                stacklevel=2,
            )
            logging.getLogger(__name__).warning(
                "SECURITY WARNING: JWT_SECRET_KEY is using the default value — "
                "do NOT use this configuration in production!"
            )
        return self

    # -----------------------------------------------------------------------
    # Computed helpers / 计算属性
    # -----------------------------------------------------------------------

    @property
    def sliding_window_threshold(self) -> int:
        """
        滑动窗口截断阈值（80% of CONTEXT_TRUNCATION_THRESHOLD）
        Sliding window truncation threshold (80% of main threshold).
        """
        return int(self.CONTEXT_TRUNCATION_THRESHOLD * 0.8)

    @property
    def summary_compression_threshold(self) -> int:
        """
        摘要压缩截断阈值（95% of CONTEXT_TRUNCATION_THRESHOLD）
        Summary compression threshold (95% of main threshold).
        """
        return int(self.CONTEXT_TRUNCATION_THRESHOLD * 0.95)

    def get_provider_concurrency(self, provider_id: str) -> int:
        """
        获取指定 provider 的并发上限，未配置时返回 5
        Get concurrency limit for provider, defaults to 5 if not configured.
        """
        return self.PROVIDER_CONCURRENCY_LIMITS.get(provider_id, 5)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    获取全局 Settings 单例（缓存，测试时可用 cache_clear 重置）
    Get global Settings singleton (cached; use cache_clear in tests to reset).
    """
    return Settings()


# Module-level alias for convenience / 便捷访问的模块级别别名
settings: Settings = get_settings()
