"""
Environment setting configurations for Videre backend.
Environment variables are injected from Kubernetes ConfigMaps and Secrets, prefixed with "VIDERE_".
"""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VIDERE_", extra="forbid")
    
    postgres_host: str = "postgres.videre.svc.cluster.local"
    postgres_port: int = 5432
    postgres_database: str = "videre"
    postgres_user: str = "videre_app"
    postgres_password: SecretStr = SecretStr("")
    redis_host: str = "redis.videre.svc.cluster.local"
    redis_port: int = 6379
    kafka_bootstrap_servers: str = "kafka.videre.svc.cluster.local:9092"
    cache_refresh_interval_seconds: float = Field(default=5.0, gt=0.0)
    prometheus_base_url: str = "http://prometheus.videre.svc.cluster.local:9090"
    loki_base_url: str = "http://loki.videre.svc.cluster.local:3100"
    ai_source_timeout_seconds: float = Field(default=3.0, gt=0.0)
    ai_metric_window_minutes: int = Field(default=15, gt=0)
    ai_log_window_minutes: int = Field(default=15, gt=0)
    ai_log_line_limit: int = Field(default=50, gt=0)
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_timeout_seconds: float = Field(default=20.0, gt=0.0)
    gemini_maximum_attempts: int = Field(default=3, ge=1)
    gemini_maximum_prompt_characters: int = Field(default=24_000, gt=0)
    ai_global_daily_limit: int = Field(default=400, gt=0)
    ai_global_minute_limit: int = Field(default=10, gt=0)
    ai_client_daily_limit: int = Field(default=20, gt=0)
    ai_client_minute_limit: int = Field(default=3, gt=0)
    ai_cache_ttl_seconds: int = Field(default=420, gt=0)
    cors_allowed_origins: str = "http://localhost:5173"

    @property
    def cors_allowed_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @property
    def postgres_dsn(self) -> URL:
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_database,
        )
    
    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/0"
