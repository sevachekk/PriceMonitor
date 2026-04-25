from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DB_URL: str
    
    DB_NAME: str
    DB_USER: str
    DB_PASSWORD: str
    DB_HOST: str
    DB_PORT: int
    
    COOKIE_SECRET_KEY: str
    ADMIN_AUTH_SECRET: str = "change-this-admin-secret"
    ADMIN_BOOTSTRAP_USERNAME: str = "superadmin"
    ADMIN_BOOTSTRAP_PASSWORD: str = "superadmin123"
    ADMIN_BOOTSTRAP_FULL_NAME: str = "Bootstrap Super Admin"
    ADMIN_ACCESS_TOKEN_TTL_MINUTES: int = 480
    INTERNAL_TASK_SECRET: str = "internal-task-secret"
    BACKUP_DIR: str = "backups"
    STARTUP_RECOVERY_PENDING_ALERT_LIMIT: int = 500
    API_RATE_LIMIT_WINDOW_SECONDS: int = 60
    API_RATE_LIMIT_REQUESTS: int = 240
    API_AUTH_RATE_LIMIT_WINDOW_SECONDS: int = 60
    API_AUTH_RATE_LIMIT_REQUESTS: int = 20
    CORS_ALLOW_ORIGINS: str = "http://localhost:8080,http://127.0.0.1:8080"
    DB_ECHO: bool = False
    
    EMAIL: str
    EMAIL_PASSWORD: str
    
    class Config:
        env_file = (".env", "../.env", "src/.env")
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings():
    return Settings()
