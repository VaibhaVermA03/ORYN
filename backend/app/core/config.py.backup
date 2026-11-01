"""Application configuration, loaded from environment variables.

All server-side secrets live here and are never exposed to the frontend.
`Settings.validate_runtime()` is called at startup and fails with an
actionable message when a required production value is missing.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDER_MARKERS = ("changeme", "change-me", "replace-me", "your-", "placeholder")


class ConfigError(RuntimeError):
    """Raised at startup when configuration is incomplete or unsafe."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # --- Application -----------------------------------------------------
    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = "ORYN"
    app_secret: str = Field(default="", description="HMAC secret for JWT signing and CSRF tokens")
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"

    # --- Database --------------------------------------------------------
    database_url: str = "postgresql+psycopg://oryn:oryn@localhost:5432/oryn"
    db_pool_size: int = 10
    db_max_overflow: int = 10

    # --- Sessions / cookies ---------------------------------------------
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 14
    frontend_origins: str = "http://localhost:5173"
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cookie_domain: str | None = None

    # --- OpenAI ----------------------------------------------------------
    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    openai_timeout_seconds: float = 60.0
    openai_max_retries: int = 2
    openai_temperature: float | None = 0.1  # set empty to omit (needed by some reasoning models)

    # --- Pinecone --------------------------------------------------------
    pinecone_api_key: str = ""
    pinecone_index_name: str = "oryn"
    pinecone_cloud: str = "aws"
    pinecone_region: str = "us-east-1"
    pinecone_namespace_prefix: str = "ws-"
    pinecone_timeout_seconds: float = 20.0

    # --- Cohere ----------------------------------------------------------
    cohere_api_key: str = ""
    cohere_rerank_model: str = "rerank-v3.5"
    cohere_timeout_seconds: float = 30.0

    # --- Google OAuth ----------------------------------------------------
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/v1/auth/google/callback"
    frontend_post_login_url: str = "http://localhost:5173/app"
    frontend_login_url: str = "http://localhost:5173/login"

    # --- Uploads / storage ----------------------------------------------
    max_upload_bytes: int = 25 * 1024 * 1024
    max_files_per_request: int = 10
    storage_backend: Literal["local"] = "local"
    storage_dir: str = "./storage"
    temp_dir: str = "./tmp"

    # --- Ingestion / chunking -------------------------------------------
    # Chunk sizes are measured in CHARACTERS (not tokens), so chunking is deterministic and
    # needs no tokenizer download. 4000 chars is roughly 1000 English tokens; 700 is roughly 175.
    chunk_size_chars: int = 4000
    chunk_overlap_chars: int = 700
    embedding_batch_size: int = 64
    ingestion_version: int = 1
    ingestion_max_attempts: int = 3
    ingestion_worker_poll_seconds: float = 2.0
    ingestion_stale_lock_seconds: int = 600
    # inline: run the worker thread inside the API process; separate: run
    # `python -m app.workers.ingestion_worker` as its own service; off: do not run one.
    ingestion_worker_mode: Literal["inline", "separate", "off"] = "inline"
    max_pdf_pages: int = 2000
    max_docx_uncompressed_bytes: int = 200 * 1024 * 1024
    pinecone_auto_create_index: bool = True

    # --- Retrieval -------------------------------------------------------
    dense_top_k: int = 30
    lexical_top_k: int = 30
    rrf_k: int = 60
    rerank_candidates: int = 30
    context_chunks: int = 5
    min_rerank_score: float = 0.05

    # --- Chat ------------------------------------------------------------
    max_message_chars: int = 4000
    chat_history_messages: int = 6
    chat_max_output_tokens: int = 1024
    chat_total_timeout_seconds: float = 120.0
    source_excerpt_chars: int = 600

    # --- Evaluation ------------------------------------------------------
    eval_max_samples: int = 50
    openai_judge_model: str = ""  # defaults to OPENAI_CHAT_MODEL when empty

    # --- Rate limiting (requests per window) ----------------------------
    rate_limit_auth_per_minute: int = 10
    rate_limit_upload_per_minute: int = 20
    rate_limit_chat_per_minute: int = 30

    # --- Admin bootstrap -------------------------------------------------
    bootstrap_admin_email: str = ""

    @field_validator("cookie_domain", "openai_temperature", mode="before")
    @classmethod
    def _empty_is_none(cls, v: object) -> object:
        """`KEY=` in a .env file means "unset", not an empty string."""
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("frontend_origins")
    @classmethod
    def _strip_origins(cls, v: str) -> str:
        return ",".join(o.strip().rstrip("/") for o in v.split(",") if o.strip())

    @property
    def allowed_origins(self) -> list[str]:
        return [o for o in self.frontend_origins.split(",") if o]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def namespace_for(self, workspace_id: str) -> str:
        return f"{self.pinecone_namespace_prefix}{workspace_id}"

    def validate_runtime(self) -> None:
        """Fail fast on missing/unsafe configuration."""
        problems: list[str] = []

        if len(self.app_secret) < 32:
            problems.append("APP_SECRET must be set to a random string of at least 32 characters")
        if "*" in self.allowed_origins:
            problems.append("FRONTEND_ORIGINS must list explicit origins; wildcard is not allowed")
        if self.cookie_samesite == "none" and not self.cookie_secure:
            problems.append("COOKIE_SAMESITE=none requires COOKIE_SECURE=true")

        if self.is_production:
            if not self.cookie_secure:
                problems.append("COOKIE_SECURE must be true in production")
            if any(m in self.app_secret.lower() for m in _PLACEHOLDER_MARKERS):
                problems.append("APP_SECRET still looks like a placeholder value")
            for name, value in (
                ("OPENAI_API_KEY", self.openai_api_key),
                ("PINECONE_API_KEY", self.pinecone_api_key),
                ("COHERE_API_KEY", self.cohere_api_key),
            ):
                if not value:
                    problems.append(f"{name} is required in production")
            if self.database_url.startswith("sqlite"):
                problems.append("DATABASE_URL must point to PostgreSQL in production")

        if self.chunk_overlap_chars >= self.chunk_size_chars:
            problems.append("CHUNK_OVERLAP_CHARS must be smaller than CHUNK_SIZE_CHARS")

        if problems:
            joined = "\n  - ".join(problems)
            raise ConfigError(f"Invalid ORYN configuration:\n  - {joined}")


@lru_cache
def get_settings() -> Settings:
    return Settings()
