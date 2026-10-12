import os
from urllib.parse import quote
try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:
    class BaseSettings:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
    SettingsConfigDict = lambda **kw: None

class Settings(BaseSettings):
    # Configurações Gerais
    PROJECT_NAME: str = "Serv indoor"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"
    
    # Banco de Dados (Padrão para container Docker local)
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@db:5432/festa_db"
    # Quando POSTGRES_HOST estiver definido, monta a URL com as credenciais separadas.
    POSTGRES_HOST: str | None = None
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str | None = None
    POSTGRES_DB: str = "festa_db"
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 15
    DB_MAX_OVERFLOW: int = 5
    DB_POOL_RECYCLE: int = 1800

    # Segurança (JWT e Hashing)
    SECRET_KEY: str = "festa-servidor-super-secret-key-ultra-fast-2026"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 120

    # Gatekeeper / Controle de Acesso Antecipado por PIN
    GATEKEEPER_ENABLED: bool = True
    SITE_ACCESS_PIN: str = "123456"  # Suporta números, letras (maiúsculas/minúsculas) e símbolos (ex: S3rv#2026)
    SITE_ACCESS_EXPIRE_DAYS: int = 7
    SITE_ACCESS_COOKIE_NAME: str = "servindoor_gate_token"
    GATEKEEPER_MAX_TENTATIVAS: int = 3  # Máximo de tentativas falhas por dispositivo a cada 24 horas

    # Servidor
    WORKERS_COUNT: int = 4

    # Amazon SES / SMTP Servindoor
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "ingresso@servindoor.com.br"
    SMTP_FROM_NAME: str = "Serv indoor"
    SMTP_FROM_SECURITY: str = "seguranca@servindoor.com.br"
    SMTP_FROM_COMMUNICATIONS: str = "comunicados@servindoor.com.br"
    SMTP_FROM_TEAM: str = "equipe@servindoor.com.br"
    EMAIL_SEND_RATE_PER_SECOND: int = 12
    EMAIL_DAILY_LIMIT: int = 50000

    # Integração com API da Escola de Governo de Caruaru
    API_KEY_EGPC: str = ""
    ESCOLA_GOVERNO_API_URL: str = "https://escoladegoverno.caruaru.pe.gov.br/api/v1/servidor/verificar"

    # Validação Externa de Servidores
    VALIDACAO_EXTERNA_URL: str = ""
    VALIDACAO_EXTERNA_TOKEN: str = ""
    VALIDACAO_EXTERNA_MOCK: bool = False
    VALIDACAO_EXTERNA_MOCK_NEGATIVOS: str = "99999999999,11111111111,12345678901"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.POSTGRES_HOST:
            usuario = quote(self.POSTGRES_USER, safe="")
            senha = quote(self.POSTGRES_PASSWORD or "", safe="")
            banco = quote(self.POSTGRES_DB, safe="")
            self.DATABASE_URL = (
                f"postgresql+asyncpg://{usuario}:{senha}"
                f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{banco}"
            )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
