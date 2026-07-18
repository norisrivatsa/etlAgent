from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Kafka Pipeline Architect Agent"
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_database: str = "kafka_pipeline_architect"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5-mini"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    kafka_bootstrap_servers: str = "localhost:9092"
    connect_url: str = "http://localhost:8083"
    ksqldb_url: str = "http://localhost:8088"
    deployment_root: Path = Field(default=Path("var/deployments"))
    command_timeout_seconds: float = 30.0
    http_timeout_seconds: float = 180.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
