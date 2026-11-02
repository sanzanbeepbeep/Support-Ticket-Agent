"""Runtime configuration, read from environment variables or a local .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_parse_none_str="none")

    openai_api_key: str | None = None
    # Any OpenAI-compatible endpoint (Azure proxy, vLLM, Ollama...) can be used by setting a base URL.
    openai_base_url: str | None = None
    openai_model: str = "gpt-4.1"
    # Set OPENAI_TEMPERATURE=none for reasoning models that reject the parameter.
    openai_temperature: float | None = 0.0
    openai_max_retries: int = 3
    openai_timeout_seconds: float = 60.0

    max_tool_iterations: int = 6
    auto_respond_min_confidence: float = 0.6

    data_dir: Path = PROJECT_ROOT / "data"


@lru_cache
def get_settings() -> Settings:
    return Settings()
