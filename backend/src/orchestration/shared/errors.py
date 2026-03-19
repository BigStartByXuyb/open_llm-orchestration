"""
异常层级定义 — 系统所有异常的唯一来源
Exception hierarchy — single source of truth for all exceptions in the system.

Layer 0: No internal imports allowed.

Error boundary rules / 错误边界规则:
- Transformer only raises TransformError (format issues)
  Transformer 只抛 TransformError（格式问题）
- Adapter translates HTTP errors into ProviderError subclasses
  Adapter 负责将 HTTP 错误翻译为 ProviderError 子类
- Executor catches both and decides retry/fail policy
  Executor 捕获两者并决定重试/失败策略
"""


class OrchestrationError(Exception):
    """
    所有平台异常的基类 / Base class for all platform exceptions.
    Always include a human-readable message. 始终包含人类可读消息。
    """

    def __init__(self, message: str, *, code: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.code = code  # 机器可读错误码，用于客户端处理 / Machine-readable code for client handling

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(message={self.message!r}, code={self.code!r})"


# ---------------------------------------------------------------------------
# Transformer errors / Transformer 错误
# ---------------------------------------------------------------------------


class TransformError(OrchestrationError):
    """
    Transformer 格式转换失败 / Transformer format conversion failure.

    Raised when a transformer cannot convert a CanonicalMessage to a
    provider-specific payload, or cannot parse a provider response.
    当 transformer 无法将 CanonicalMessage 转换为 provider 专有格式，
    或无法解析 provider 响应时抛出。
    """


# ---------------------------------------------------------------------------
# Provider / Adapter errors / Provider/Adapter 错误
# ---------------------------------------------------------------------------


class ProviderError(OrchestrationError):
    """
    Provider Adapter HTTP/网络错误基类 / Base class for adapter HTTP/network errors.
    Adapters translate raw HTTP errors into these subclasses.
    Adapter 将原始 HTTP 错误翻译为这些子类后抛出。
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "",
        status_code: int = 0,
        provider_id: str = "",
    ) -> None:
        super().__init__(message, code=code)
        self.status_code = status_code
        self.provider_id = provider_id


class RateLimitError(ProviderError):
    """
    HTTP 429 速率限制 / HTTP 429 rate limit exceeded.
    Caller should implement exponential backoff.
    调用方应实现指数退避。
    """

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        *,
        retry_after: float = 0.0,
        **kwargs: object,
    ) -> None:
        super().__init__(message, code="rate_limit", status_code=429, **kwargs)  # type: ignore[arg-type]
        self.retry_after = retry_after  # 建议等待秒数 / Suggested wait time in seconds


class AuthError(ProviderError):
    """
    HTTP 401/403 认证/授权失败 / HTTP 401/403 authentication/authorization failure.
    Do NOT retry — requires credential rotation.
    不应重试 — 需要轮换凭证。
    """

    def __init__(self, message: str = "Authentication failed", **kwargs: object) -> None:
        super().__init__(message, code="auth_error", **kwargs)  # type: ignore[arg-type]


class ProviderUnavailable(ProviderError):
    """
    HTTP 5xx provider 不可用 / HTTP 5xx provider unavailable.
    Eligible for retry with backoff. 可以退避重试。
    """

    def __init__(self, message: str = "Provider unavailable", **kwargs: object) -> None:
        super().__init__(message, code="provider_unavailable", **kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Orchestration-level errors / 编排层错误
# ---------------------------------------------------------------------------


class ContextOverflowError(OrchestrationError):
    """
    token/char 超限（已压缩仍无法处理）
    Token/char limit exceeded even after compression attempts.

    Raised by decomposer or aggregator when context cannot be reduced
    further within configured thresholds.
    当上下文无法在配置阈值内进一步压缩时，由 decomposer 或 aggregator 抛出。
    """

    def __init__(
        self,
        message: str = "Context overflow: cannot reduce further",
        *,
        char_count: int = 0,
        threshold: int = 0,
    ) -> None:
        super().__init__(message, code="context_overflow")
        self.char_count = char_count
        self.threshold = threshold


class TenantIsolationError(OrchestrationError):
    """
    多租户 RLS 注入失败 / Multi-tenant RLS injection failure.

    Raised when tenant_id is missing or invalid, preventing DB access.
    当 tenant_id 缺失或无效，阻止 DB 访问时抛出。
    This is a security-critical error — never silently swallow.
    这是安全关键错误 — 永远不要静默吞掉。
    """

    def __init__(self, message: str = "Tenant isolation failure", **kwargs: object) -> None:
        super().__init__(message, code="tenant_isolation", **kwargs)  # type: ignore[arg-type]


class PluginError(OrchestrationError):
    """
    Skill/Plugin 执行失败 / Skill/Plugin execution failure.
    """

    def __init__(
        self,
        message: str = "Plugin execution failed",
        *,
        skill_id: str = "",
        **kwargs: object,
    ) -> None:
        super().__init__(message, code="plugin_error", **kwargs)  # type: ignore[arg-type]
        self.skill_id = skill_id


class ConfigurationError(OrchestrationError):
    """
    配置错误 — 启动时必要配置缺失或无效 / Configuration error — required config missing or invalid at startup.

    Raised when a required component (e.g., provider adapter) is not configured
    but is needed for operation. Indicates an operator error, not a user error.
    当所需组件（如 provider adapter）未配置但被需要时抛出，表示运维错误而非用户错误。
    """

    def __init__(self, message: str = "Configuration error", **kwargs: object) -> None:
        super().__init__(message, code="configuration_error", **kwargs)  # type: ignore[arg-type]
