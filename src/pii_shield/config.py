from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM providers
    groq_api_key: str
    gemini_api_key: str
    groq_model: str = "openai/gpt-oss-120b"
    gemini_model: str = "gemini-flash-lite-latest"

    # NLP / PII detection
    spacy_model: str = "en_core_web_lg"
    pii_confidence_threshold: float = 0.4

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # App
    environment: str = "development"
    log_level: str = "INFO"
    
    agent_max_tool_rounds: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()