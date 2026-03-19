"""可灵 provider 专属配置 / Kling provider-specific configuration."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class KlingConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KLING_", env_file=".env", case_sensitive=False, extra="ignore")
    API_KEY: str = Field(default="", description="Kling AI API key")
    BASE_URL: str = Field(default="https://api.klingai.com", description="Kling API base URL")
    TIMEOUT: float = Field(default=30.0, description="Per-request timeout (polling uses short timeouts)")
    POLL_INTERVAL: float = Field(default=5.0, description="Seconds between task status polls")
    POLL_MAX_ATTEMPTS: int = Field(default=60, description="Max poll attempts before giving up (5s * 60 = 5min)")
