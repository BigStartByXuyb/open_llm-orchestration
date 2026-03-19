"""极梦 provider 专属配置 / Jimeng provider-specific configuration."""

from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class JimengConfig(BaseSettings):
    """
    极梦 provider 配置，支持双模式认证
    Jimeng provider config with dual-mode authentication support.

    AUTH_MODE="bearer"          — 即梦 AI 开放平台 API Key（默认）
    AUTH_MODE="volcano_signing" — 火山引擎账号 HMAC-SHA256 签名
    """

    model_config = SettingsConfigDict(env_prefix="JIMENG_", env_file=".env", case_sensitive=False, extra="ignore")

    API_KEY: str = Field(default="", description="Jimeng (ByteDance) API key（bearer 模式使用）")
    BASE_URL: str = Field(default="https://visual.volcengineapi.com", description="Jimeng API base URL")
    TIMEOUT: float = Field(default=60.0, description="Request timeout in seconds")
    MAX_RETRIES: int = Field(default=2, description="Max retry attempts")

    # --- 双模式认证字段 / Dual-mode auth fields ---
    AUTH_MODE: Literal["bearer", "volcano_signing"] = Field(
        default="bearer",
        description="认证模式：bearer=平台 API Key，volcano_signing=火山引擎 HMAC-SHA256 签名",
    )
    ACCESS_KEY: str = Field(default="", description="火山引擎 Access Key（volcano_signing 模式使用）")
    SECRET_KEY: str = Field(default="", description="火山引擎 Secret Key（volcano_signing 模式使用）")

    @model_validator(mode="after")
    def _validate_volcano_signing_fields(self) -> "JimengConfig":
        """volcano_signing 模式下 ACCESS_KEY 和 SECRET_KEY 不能为空。"""
        if self.AUTH_MODE == "volcano_signing":
            missing = [f for f in ("ACCESS_KEY", "SECRET_KEY") if not getattr(self, f)]
            if missing:
                raise ValueError(
                    f"volcano_signing mode requires {', '.join(missing)} to be set"
                )
        return self
