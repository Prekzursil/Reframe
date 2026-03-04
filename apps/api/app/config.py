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
    rate_limit_heavy_requests: int = Field(
        default=20,
        validation_alias=AliasChoices("RATE_LIMIT_HEAVY_REQUESTS", "REFRAME_RATE_LIMIT_HEAVY_REQUESTS"),
    )
    rate_limit_heavy_window_seconds: int = Field(
        default=60,
        validation_alias=AliasChoices("RATE_LIMIT_HEAVY_WINDOW_SECONDS", "REFRAME_RATE_LIMIT_HEAVY_WINDOW_SECONDS"),
    )
    rate_limit_upload_requests: int = Field(
        default=30,
        validation_alias=AliasChoices("RATE_LIMIT_UPLOAD_REQUESTS", "REFRAME_RATE_LIMIT_UPLOAD_REQUESTS"),
    )
    rate_limit_upload_window_seconds: int = Field(
        default=60,
        validation_alias=AliasChoices("RATE_LIMIT_UPLOAD_WINDOW_SECONDS", "REFRAME_RATE_LIMIT_UPLOAD_WINDOW_SECONDS"),
    )
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
    share_link_secret: str = Field(
        default="reframe-dev-share-secret",
        validation_alias=AliasChoices("SHARE_LINK_SECRET", "REFRAME_SHARE_LINK_SECRET"),
        description="HMAC secret used to sign public share links for local assets.",
    )
    hosted_mode: bool = Field(
        default=False,
        validation_alias=AliasChoices("HOSTED_MODE", "REFRAME_HOSTED_MODE"),
        description="Enable hosted multi-tenant auth and billing enforcement.",
    )
    enable_oauth: bool = Field(
        default=False,
        validation_alias=AliasChoices("ENABLE_OAUTH", "REFRAME_ENABLE_OAUTH"),
        description="Enable Google/GitHub OAuth routes.",
    )
    enable_billing: bool = Field(
        default=False,
        validation_alias=AliasChoices("ENABLE_BILLING", "REFRAME_ENABLE_BILLING"),
        description="Enable billing and quota enforcement routes.",
    )
    jwt_secret: str = Field(
        default="reframe-dev-jwt-secret",
        validation_alias=AliasChoices("JWT_SECRET", "REFRAME_JWT_SECRET"),
        description="Secret used to sign access tokens.",
    )
    jwt_refresh_secret: str = Field(
        default="reframe-dev-jwt-refresh-secret",
        validation_alias=AliasChoices("JWT_REFRESH_SECRET", "REFRAME_JWT_REFRESH_SECRET"),
        description="Secret used to sign refresh tokens.",
    )
    jwt_access_ttl_minutes: int = Field(
        default=15,
        validation_alias=AliasChoices("JWT_ACCESS_TTL_MINUTES", "REFRAME_JWT_ACCESS_TTL_MINUTES"),
        description="Access token lifetime in minutes.",
    )
    jwt_refresh_ttl_days: int = Field(
        default=30,
        validation_alias=AliasChoices("JWT_REFRESH_TTL_DAYS", "REFRAME_JWT_REFRESH_TTL_DAYS"),
        description="Refresh token lifetime in days.",
    )
    app_base_url: str = Field(
        default="http://localhost:5173",
        validation_alias=AliasChoices("APP_BASE_URL", "REFRAME_APP_BASE_URL"),
        description="Public frontend URL used for OAuth/billing redirects.",
    )
    desktop_web_dist: str = Field(
        default="",
        validation_alias=AliasChoices("DESKTOP_WEB_DIST", "REFRAME_DESKTOP_WEB_DIST"),
        description="Optional absolute path to built desktop web assets mounted at '/'.",
    )
    api_base_url: str = Field(
        default="http://localhost:8000",
        validation_alias=AliasChoices("API_BASE_URL", "REFRAME_API_BASE_URL"),
        description="Public API URL used in callback URLs.",
    )
    oauth_google_client_id: str = Field(
        default="",
        validation_alias=AliasChoices("OAUTH_GOOGLE_CLIENT_ID", "REFRAME_OAUTH_GOOGLE_CLIENT_ID"),
        description="Google OAuth client id.",
    )
    oauth_google_client_secret: str = Field(
        default="",
        validation_alias=AliasChoices("OAUTH_GOOGLE_CLIENT_SECRET", "REFRAME_OAUTH_GOOGLE_CLIENT_SECRET"),
        description="Google OAuth client secret.",
    )
    oauth_github_client_id: str = Field(
        default="",
        validation_alias=AliasChoices("OAUTH_GITHUB_CLIENT_ID", "REFRAME_OAUTH_GITHUB_CLIENT_ID"),
        description="GitHub OAuth client id.",
    )
    oauth_github_client_secret: str = Field(
        default="",
        validation_alias=AliasChoices("OAUTH_GITHUB_CLIENT_SECRET", "REFRAME_OAUTH_GITHUB_CLIENT_SECRET"),
        description="GitHub OAuth client secret.",
    )
    oauth_state_secret: str = Field(
        default="reframe-dev-oauth-state",
        validation_alias=AliasChoices("OAUTH_STATE_SECRET", "REFRAME_OAUTH_STATE_SECRET"),
        description="Secret used to sign OAuth state payloads.",
    )
    enable_sso_scim: bool = Field(
        default=False,
        validation_alias=AliasChoices("ENABLE_SSO_SCIM", "REFRAME_ENABLE_SSO_SCIM"),
        description="Enable enterprise SSO/SCIM routes for hosted organizations.",
    )
    okta_issuer_url: str = Field(
        default="",
        validation_alias=AliasChoices("OKTA_ISSUER_URL", "REFRAME_OKTA_ISSUER_URL"),
        description="Default Okta issuer URL for hosted SSO.",
    )
    okta_client_id: str = Field(
        default="",
        validation_alias=AliasChoices("OKTA_CLIENT_ID", "REFRAME_OKTA_CLIENT_ID"),
        description="Default Okta OAuth client ID.",
    )
    okta_client_secret: str = Field(
        default="",
        validation_alias=AliasChoices("OKTA_CLIENT_SECRET", "REFRAME_OKTA_CLIENT_SECRET"),
        description="Default Okta OAuth client secret.",
    )
    okta_audience: str = Field(
        default="",
        validation_alias=AliasChoices("OKTA_AUDIENCE", "REFRAME_OKTA_AUDIENCE"),
        description="Optional Okta audience for API authorization.",
    )
    scim_token_prefix: str = Field(
        default="rscim_",
        validation_alias=AliasChoices("SCIM_TOKEN_PREFIX", "REFRAME_SCIM_TOKEN_PREFIX"),
        description="Prefix used when issuing SCIM bearer tokens.",
    )
    publish_state_secret: str = Field(
        default="reframe-dev-publish-state-secret",
        validation_alias=AliasChoices("PUBLISH_STATE_SECRET", "REFRAME_PUBLISH_STATE_SECRET"),
        description="Secret used to sign publish provider connection state.",
    )
    publish_youtube_client_id: str = Field(
        default="",
        validation_alias=AliasChoices("PUBLISH_YOUTUBE_CLIENT_ID", "REFRAME_PUBLISH_YOUTUBE_CLIENT_ID"),
        description="OAuth client id for YouTube publishing integration.",
    )
    publish_youtube_client_secret: str = Field(
        default="",
        validation_alias=AliasChoices("PUBLISH_YOUTUBE_CLIENT_SECRET", "REFRAME_PUBLISH_YOUTUBE_CLIENT_SECRET"),
        description="OAuth client secret for YouTube publishing integration.",
    )
    publish_tiktok_client_id: str = Field(
        default="",
        validation_alias=AliasChoices("PUBLISH_TIKTOK_CLIENT_ID", "REFRAME_PUBLISH_TIKTOK_CLIENT_ID"),
        description="OAuth client id for TikTok publishing integration.",
    )
    publish_tiktok_client_secret: str = Field(
        default="",
        validation_alias=AliasChoices("PUBLISH_TIKTOK_CLIENT_SECRET", "REFRAME_PUBLISH_TIKTOK_CLIENT_SECRET"),
        description="OAuth client secret for TikTok publishing integration.",
    )
    publish_instagram_client_id: str = Field(
        default="",
        validation_alias=AliasChoices("PUBLISH_INSTAGRAM_CLIENT_ID", "REFRAME_PUBLISH_INSTAGRAM_CLIENT_ID"),
        description="OAuth client id for Instagram publishing integration.",
    )
    publish_instagram_client_secret: str = Field(
        default="",
        validation_alias=AliasChoices("PUBLISH_INSTAGRAM_CLIENT_SECRET", "REFRAME_PUBLISH_INSTAGRAM_CLIENT_SECRET"),
        description="OAuth client secret for Instagram publishing integration.",
    )
    publish_facebook_client_id: str = Field(
        default="",
        validation_alias=AliasChoices("PUBLISH_FACEBOOK_CLIENT_ID", "REFRAME_PUBLISH_FACEBOOK_CLIENT_ID"),
        description="OAuth client id for Facebook publishing integration.",
    )
    publish_facebook_client_secret: str = Field(
        default="",
        validation_alias=AliasChoices("PUBLISH_FACEBOOK_CLIENT_SECRET", "REFRAME_PUBLISH_FACEBOOK_CLIENT_SECRET"),
        description="OAuth client secret for Facebook publishing integration.",
    )
    stripe_secret_key: str = Field(
        default="",
        validation_alias=AliasChoices("STRIPE_SECRET_KEY", "REFRAME_STRIPE_SECRET_KEY"),
        description="Stripe secret key (test mode in this phase).",
    )
    stripe_webhook_secret: str = Field(
        default="",
        validation_alias=AliasChoices("STRIPE_WEBHOOK_SECRET", "REFRAME_STRIPE_WEBHOOK_SECRET"),
        description="Stripe webhook secret for signature verification.",
    )
    stripe_price_pro: str = Field(
        default="",
        validation_alias=AliasChoices("STRIPE_PRICE_PRO", "REFRAME_STRIPE_PRICE_PRO"),
        description="Stripe price id for pro plan.",
    )
    stripe_price_enterprise: str = Field(
        default="",
        validation_alias=AliasChoices("STRIPE_PRICE_ENTERPRISE", "REFRAME_STRIPE_PRICE_ENTERPRISE"),
        description="Stripe price id for enterprise plan.",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
