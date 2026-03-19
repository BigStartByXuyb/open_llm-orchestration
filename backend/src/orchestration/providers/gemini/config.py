"""Gemini provider 专属配置 / Gemini provider-specific configuration."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GeminiConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GEMINI_", env_file=".env", case_sensitive=False, extra="ignore")
    API_KEY: str = Field(default="", description="Google Gemini API key")
    BASE_URL: str = Field(default="https://generativelanguage.googleapis.com", description="Gemini API base URL")
    TIMEOUT: float = Field(default=60.0, description="Request timeout in seconds")
    MAX_RETRIES: int = Field(default=3, description="Max retry attempts")
