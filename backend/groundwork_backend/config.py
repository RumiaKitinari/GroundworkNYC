import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = ""
    redis_url: str = ""
    cors_origins: tuple = ()
    production: bool = False
    tile_ttl: int = 86400

    @classmethod
    def from_env(cls):
        settings = cls(
            database_url=os.getenv("DATABASE_URL", ""),
            redis_url=os.getenv("REDIS_URL", ""),
            cors_origins=tuple(x.strip() for x in os.getenv("CORS_ORIGINS", "").split(",") if x.strip()),
            production=os.getenv("APP_ENV") == "production",
        )
        if "*" in settings.cors_origins:
            raise ValueError("Set explicit CORS origins; wildcard origins are not supported.")
        if settings.production and len(os.getenv("GROUNDWORK_SECRET_KEY", "")) < 32:
            raise ValueError("Production requires a stable GROUNDWORK_SECRET_KEY of at least 32 characters.")
        if settings.production and not settings.database_url:
            raise ValueError("Production requires DATABASE_URL.")
        return settings
