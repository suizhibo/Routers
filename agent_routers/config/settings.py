from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="forbid")

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/agent_routers"
    REDIS_URL: str = "redis://localhost:6379/0"
    JWKS_URL: str = "https://idp.example.com/.well-known/jwks.json"
    JWT_ISS: str = "https://idp.example.com"
    JWT_AUD: str = "agent-routers"
    AUDIT_HMAC_KEY: str = "change-me-in-production"
    QUOTA_DEFAULT_PER_MINUTE: int = 120
    DRAIN_TIMEOUT_SECONDS: int = 15


settings = Settings()
