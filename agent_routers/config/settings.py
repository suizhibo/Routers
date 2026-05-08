from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="forbid", env_file=".env", env_file_encoding="utf-8")

    # Dev mode: run without external dependencies (PG, Redis, JWKS)
    DEV_MODE: bool = False

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/agent_routers"
    REDIS_URL: str = "redis://localhost:6379/0"
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    AUDIT_HMAC_KEY: str = "change-me-in-production"
    AUDIT_MAX_BODY_BYTES: int = 65536
    QUOTA_DEFAULT_PER_MINUTE: int = 120
    DRAIN_TIMEOUT_SECONDS: int = 15
    DEFAULT_AGENT_ID: str = ""


settings = Settings()
