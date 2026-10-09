from functools import lru_cache

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = Field(default="development")
    log_level: str = Field(default="INFO")
    log_json: bool = Field(default=False)

    database_url: str = Field(...)

    redis_url: str = Field(default="")
    redis_enabled: bool = Field(default=True)

    evolution_api_url: str = Field(...)
    evolution_api_key: str = Field(...)
    evolution_instance: str = Field(...)

    webhook_secret: str = Field(..., min_length=32)

    @field_validator("evolution_api_key", "webhook_secret", mode="before")
    @classmethod
    def _strip(cls, v: object) -> object:
        # Values pasted from a dashboard often carry a stray space or newline.
        return "".join(v.split()) if isinstance(v, str) else v

    @field_validator("database_url")
    @classmethod
    def _use_asyncpg(cls, v: str) -> str:
        # Providers hand out postgres:// or postgresql:// URLs; SQLAlchemy needs the driver named.
        scheme, _, rest = v.strip().partition("://")
        if scheme not in {"postgres", "postgresql", "postgresql+asyncpg"} or not rest:
            raise ValueError("must be a PostgreSQL connection URL")
        return f"postgresql+asyncpg://{rest}"

    @field_validator("evolution_api_url")
    @classmethod
    def _no_trailing_slash(cls, v: str) -> str:
        return v.strip().rstrip("/")

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as e:
        # Raised without the original traceback, which would echo values read from the environment.
        fields = "; ".join(f"{'.'.join(str(p) for p in err['loc']).upper()}: {err['msg']}" for err in e.errors())
        raise RuntimeError(f"Invalid or missing configuration: {fields}. See .env.example.") from None
