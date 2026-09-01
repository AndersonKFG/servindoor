import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Configurações Gerais
    PROJECT_NAME: str = "Servindoor"
    DEBUG: bool = False
    
    # Banco de Dados (Padrão para container Docker local)
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@db:5432/festa_db"
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_RECYCLE: int = 1800

    # Segurança (JWT e Hashing)
    SECRET_KEY: str = "festa-servidor-super-secret-key-ultra-fast-2026"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 120

    # Servidor
    WORKERS_COUNT: int = 4

    # Amazon SES / SMTP Servindoor
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "ingresso@servindoor.com.br"
    SMTP_FROM_NAME: str = "Servindoor"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
