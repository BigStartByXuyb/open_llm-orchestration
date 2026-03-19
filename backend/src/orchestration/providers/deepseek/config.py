"""DeepSeek provider 专属配置 / DeepSeek provider-specific configuration."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DeepSeekConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DEEPSEEK_", env_file=".env", case_sensitive=False, extra="ignore")
    API_KEY: str = Field(default="", description="DeepSeek API key")
    BASE_URL: str = Field(default="https://api.deepseek.com", description="DeepSeek API base URL")
    TIMEOUT: float = Field(default=120.0, description="Request timeout (DeepSeek-R1 can be slow)")
    MAX_RETRIES: int = Field(default=3, description="Max retry attempts")
