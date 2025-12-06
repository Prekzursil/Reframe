from functools import lru_cache
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseModel):
    url: str = Field(default="sqlite:///./reframe.db")


class BrokerSettings(BaseModel):
    broker_url: str = Field(default="redis://redis:6379/0")
    result_backend: str = Field(default="redis://redis:6379/0")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", env_prefix="REFRAME_")

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    broker: BrokerSettings = Field(default_factory=BrokerSettings)
    media_root: str = Field(default="./media")
    api_title: str = Field(default="Reframe API")
    api_version: str = Field(default="0.1.0")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
