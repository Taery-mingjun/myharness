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
        default="claude-sonnet-4-20250514", description="Default Anthropic model"
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

    # Generic OpenAI-compatible provider (Agnes, Together, vLLM, etc.)
    openai_compatible_api_key: str = Field(default="", description="API key for OpenAI-compatible backend")
    openai_compatible_base_url: str = Field(default="", description="Base URL for OpenAI-compatible backend")
    openai_compatible_default_model: str = Field(default="gpt-4o", description="Default model for OpenAI-compatible backend")
    openai_compatible_provider_name: str = Field(default="openai_compatible", description="Logical provider name for OpenAI-compatible backend")

    default_llm_provider: str = Field(
        default="openai",
        description="Default LLM provider: openai|anthropic|google|qwen|deepseek|local|openai_compatible",
    )

    # Embedding backend — may differ from the cognitive provider. Anthropic
    # and DeepSeek expose no embeddings API, so vector memory needs a
    # separate backend (e.g. 'openai' or 'local'). See P8 (replaceable compute).
    embedding_provider: str = Field(
        default="openai",
        description="Provider used for embeddings (vector memory). "
        "May differ from default_llm_provider, since Anthropic and DeepSeek "
        "expose no embeddings API. Set to 'none' to disable vector memory "
        "and rely on full-text search only.",
    )
    embedding_model: str = Field(
        default="text-embedding-3-small",
        description="Embedding model used by the embedding provider.",
    )

    # ── Data Storage ───────────────────────────────────────────────────

    data_dir: Path = Field(default=Path("./data"), description="Root data directory")
    memory_fsync_appends: bool = Field(
        default=True,
        description=(
            "Flush each memory append to the device before acknowledging it. "
            "On by default because the rest of the system treats a returned "
            "append as durable. Disable only on throughput-bound deployments "
            "that accept losing the most recent entries on power loss."
        ),
    )
    embedding_dimension: int = Field(
        default=1536, description="Default embedding vector dimension"
    )
    vector_index_type: str = Field(
        default="IVFFlat", description="FAISS index type (IVFFlat, Flat, HNSW, etc.)"
    )

    # ── Self-healing & Reflex Layer ────────────────────────────────────

    healing_failure_threshold: int = Field(
        default=5, ge=1, description="Consecutive failures that generate a rollback candidate"
    )
    healing_window_size: int = Field(
        default=100, ge=10, description="Metric window used for failure-rate evaluation"
    )
    reflex_success_threshold: int = Field(
        default=5, ge=1, description="Consecutive successes required to promote a skill to the Reflex Index"
    )

    # ── API Server ─────────────────────────────────────────────────────

    api_host: str = Field(default="127.0.0.1", description="API server bind host")
    api_port: int = Field(default=8000, description="API server port")
    api_debug: bool = Field(default=False, description="Enable debug mode")

    # API authentication — fail-closed if api_key is not configured
    api_key: str = Field(
        default="",
        description="Static API key required for all mutating endpoints. "
        "If empty, ALL write requests are rejected (fail-closed).",
    )
    api_key_header: str = Field(
        default="X-API-Key",
        description="HTTP header name from which the API key is read.",
    )

    # CORS — explicit allowlist (no wildcard)
    api_cors_origins: list[str] = Field(
        default_factory=lambda: ["http://127.0.0.1:8000", "http://localhost:8000"],
        description="Explicit list of allowed CORS origins (no wildcard).",
    )
    api_cors_methods: list[str] = Field(
        default_factory=lambda: ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        description="Allowed HTTP methods for CORS.",
    )
    api_cors_headers: list[str] = Field(
        default_factory=lambda: ["Authorization", "Content-Type", "X-API-Key"],
        description="Allowed headers for CORS.",
    )

    # ── Execution Authorisation ────────────────────────────────────────

    system_actor: str = Field(
        default="system",
        description="Actor attributed to plan steps that carry no explicit actor.",
    )
    enforce_execution_boundary: bool = Field(
        default=True,
        description="Block plan steps that fall outside their skill's declared "
        "action boundary. Set False only to audit a policy against live "
        "traffic — denials are then logged but still executed.",
    )
    permission_default_policy: str = Field(
        default="deny",
        description="RBAC decision when no grant matches: 'deny' (fail-closed) "
        "or 'allow'. The system_actor is granted full access at container "
        "build time, so the default single-agent deployment works unchanged.",
    )

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
