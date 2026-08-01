"""Application settings via pydantic-settings.

All configuration is loaded from environment variables prefixed with MYH_,
with .env file support for local development.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide configuration.

    Loads from environment variables (MYH_* prefix) and .env file.
    """

    model_config = SettingsConfigDict(
        env_prefix="MYH_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── LLM Providers ──────────────────────────────────────────────────

    openai_api_key: str = Field(default="", description="OpenAI API key")
    openai_default_model: str = Field(default="gpt-4o", description="Default OpenAI model")

    anthropic_api_key: str = Field(default="", description="Anthropic API key")
    anthropic_default_model: str = Field(
        default="claude-3-opus-20240229", description="Default Anthropic model"
    )

    google_api_key: str = Field(default="", description="Google AI API key")
    google_default_model: str = Field(
        default="gemini-2.0-flash", description="Default Google Gemini model"
    )

    qwen_api_key: str = Field(default="", description="Qwen (通义千问) API key")
    qwen_default_model: str = Field(default="qwen-max", description="Default Qwen model")

    deepseek_api_key: str = Field(default="", description="DeepSeek API key")
    deepseek_default_model: str = Field(
        default="deepseek-chat", description="Default DeepSeek model"
    )

    ollama_base_url: str = Field(
        default="http://localhost:11434", description="Ollama base URL for local models"
    )
    ollama_default_model: str = Field(
        default="llama3.1", description="Default local model via Ollama"
    )

    default_llm_provider: str = Field(
        default="openai",
        description="Default LLM provider: openai|anthropic|google|qwen|deepseek|local",
    )

    # ── Data Storage ───────────────────────────────────────────────────

    data_dir: Path = Field(default=Path("./data"), description="Root data directory")
    embedding_dimension: int = Field(
        default=1536, description="Default embedding vector dimension"
    )
    vector_index_type: str = Field(
        default="IVFFlat", description="FAISS index type (IVFFlat, Flat, HNSW, etc.)"
    )

    # ── API Server ─────────────────────────────────────────────────────

    api_host: str = Field(default="0.0.0.0", description="API server host")
    api_port: int = Field(default=8000, description="API server port")
    api_debug: bool = Field(default=False, description="Enable debug mode")

    # ── Logging ────────────────────────────────────────────────────────

    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(
        default="json", description="Log format: json|console|keyvalue"
    )

    # ── Runtime ────────────────────────────────────────────────────────

    cognitive_loop_interval_ms: int = Field(
        default=100, description="Cognitive loop polling interval in milliseconds"
    )
    max_concurrent_tasks: int = Field(
        default=10, description="Maximum concurrent cognitive tasks"
    )
    default_task_timeout: float = Field(
        default=300.0, description="Default task timeout in seconds"
    )

    @property
    def memory_source_dir(self) -> Path:
        """Directory for memory source-of-truth (JSON) files."""
        return self.data_dir / "memory" / "source"

    @property
    def memory_derived_dir(self) -> Path:
        """Directory for memory derived (rebuildable) data."""
        return self.data_dir / "memory" / "derived"

    @property
    def memory_index_dir(self) -> Path:
        """Directory for memory vector and text indexes."""
        return self.data_dir / "memory" / "indexes"

    @property
    def skills_dir(self) -> Path:
        """Directory for skill definition files."""
        return self.data_dir / "skills"

    def ensure_directories(self) -> None:
        """Create all required data directories if they don't exist."""
        for d in [
            self.memory_source_dir,
            self.memory_derived_dir,
            self.memory_index_dir,
            self.skills_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    settings = Settings()
    settings.ensure_directories()
    return settings
