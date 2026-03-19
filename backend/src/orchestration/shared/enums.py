"""
枚举定义 — 系统所有枚举值的唯一来源
Enum definitions — single source of truth for all enum values in the system.

Layer 0: No internal imports allowed.
"""

from enum import StrEnum, auto


class Role(StrEnum):
    """消息角色 / Message role in a conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ProviderID(StrEnum):
    """
    LLM 提供商 ID / LLM provider identifier.

    SKILL is a pseudo-provider for plugin/skill invocations that bypass
    the transformer/adapter pipeline entirely.
    SKILL 是插件调用的伪 provider，完全绕过 transformer/adapter 管道。
    """

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    GEMINI = "gemini"
    JIMENG = "jimeng"    # 极梦图像生成 / Jimeng image generation
    KLING = "kling"      # 可灵视频生成 / Kling video generation
    SKILL = "skill"      # 插件调用伪 provider / Plugin invocation pseudo-provider


class Capability(StrEnum):
    """
    子任务所需能力类型 / Capability type required by a subtask.
    Used by CapabilityRouter to select the appropriate provider.
    由 CapabilityRouter 用于选择合适的 provider。
    """

    TEXT = "text"
    CODE = "code"
    SEARCH = "search"
    IMAGE_GEN = "image_gen"      # 图像生成 / Image generation
    VIDEO_GEN = "video_gen"      # 视频生成 / Video generation
    ANALYSIS = "analysis"


class TaskStatus(StrEnum):
    """
    任务状态机 / Task state machine.
    Transitions: PENDING → RUNNING → DONE | FAILED | CANCELLED
    """

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ContentPartType(StrEnum):
    """消息内容块类型 / Content part types within a CanonicalMessage."""

    TEXT = "text"
    IMAGE = "image"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
