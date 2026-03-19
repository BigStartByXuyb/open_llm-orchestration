"""OpenAI provider 专属配置 / OpenAI provider-specific configuration."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OpenAIConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPENAI_", env_file=".env", case_sensitive=False, extra="ignore")
    API_KEY: str = Field(default="", description="OpenAI API key")
    BASE_URL: str = Field(default="https://api.openai.com", description="OpenAI API base URL")
    TIMEOUT: float = Field(default=60.0, description="Request timeout in seconds")
    MAX_RETRIES: int = Field(default=3, description="Max retry attempts")
