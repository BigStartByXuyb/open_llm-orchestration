"""
Anthropic provider 专属配置
Anthropic provider-specific configuration.

Layer 4: Only imports from shared/.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AnthropicConfig(BaseSettings):
    """Anthropic API 配置 / Anthropic API configuration."""

    model_config = SettingsConfigDict(
        env_prefix="ANTHROPIC_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    API_KEY: str = Field(default="", description="Anthropic API key (ANTHROPIC_API_KEY)")
    BASE_URL: str = Field(
        default="https://api.anthropic.com",
        description="Anthropic API base URL",
    )
    API_VERSION: str = Field(
        default="2023-06-01",
        description="Anthropic API version header (anthropic-version)",
    )
    TIMEOUT: float = Field(default=120.0, description="Request timeout in seconds")
    MAX_RETRIES: int = Field(default=3, description="Max retry attempts for 5xx errors")
