from functools import lru_cache
from pydantic import Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="REFRAME_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    database_url: str = Field(
        default="sqlite:///./reframe.db",
        validation_alias=AliasChoices("DATABASE_URL", "REFRAME_DATABASE__URL", "DATABASE__URL"),
    )
    broker_url: str = Field(
        default="redis://redis:6379/0",
        validation_alias=AliasChoices("BROKER_URL", "REFRAME_BROKER__BROKER_URL", "BROKER__BROKER_URL"),
    )
    result_backend: str = Field(
        default="redis://redis:6379/0",
        validation_alias=AliasChoices("RESULT_BACKEND", "REFRAME_BROKER__RESULT_BACKEND", "BROKER__RESULT_BACKEND"),
    )
    media_root: str = Field(
        default="./media",
        validation_alias=AliasChoices("MEDIA_ROOT", "REFRAME_MEDIA_ROOT"),
    )
    api_title: str = Field(default="Reframe API")
    api_version: str = Field(default="0.1.0")
    log_format: str = Field(default="json", description="Logging format: json|plain")
    log_level: str = Field(default="INFO", description="Logging level, e.g. DEBUG|INFO|WARNING")
    rate_limit_requests: int = Field(default=60)
    rate_limit_window_seconds: int = Field(default=60)
    max_upload_bytes: int = Field(
        default=1_073_741_824,
        validation_alias=AliasChoices("MAX_UPLOAD_BYTES", "REFRAME_MAX_UPLOAD_BYTES"),
        description="Max upload size for /assets/upload (0 disables). Default: 1 GiB.",
    )
    cleanup_ttl_hours: int = Field(
        default=24,
        validation_alias=AliasChoices("CLEANUP_TTL_HOURS", "REFRAME_CLEANUP_TTL_HOURS"),
        description="Delete files under MEDIA_ROOT/tmp older than this (hours).",
    )
    cleanup_interval_seconds: int = Field(
        default=3600,
        validation_alias=AliasChoices("CLEANUP_INTERVAL_SECONDS", "REFRAME_CLEANUP_INTERVAL_SECONDS"),
        description="How often to run tmp cleanup (seconds).",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
