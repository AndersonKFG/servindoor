from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from sqlmodel import SQLModel
from app.core.config import settings

# Configuracao de URL e argumentos de conexao assincrona
db_url = settings.DATABASE_URL
connect_args = {}

# Se for asyncpg (PostgreSQL assincrono)
if "asyncpg" in db_url:
    if "?sslmode=require" in db_url:
        db_url = db_url.replace("?sslmode=require", "")
        connect_args["ssl"] = False
    connect_args["statement_cache_size"] = 1024
    connect_args["command_timeout"] = 30

engine = create_async_engine(
    db_url,
    echo=settings.DB_ECHO,
    future=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=settings.DB_POOL_RECYCLE,
    pool_pre_ping=True,
    connect_args=connect_args
)
async_session = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Injeta a sessao de banco assincrona para cada requisicao com reaproveitamento de pool"""
    async with async_session() as session:
        yield session

async def init_db():
    """Inicializa automaticamente todas as tabelas oficiais do sistema"""
    from app.models.all_models import (
        Usuario, Lote, Ingresso, Secretaria, ReservaIngresso, LogAcesso,
        Eixo, Premio, Ganhador, EstadoSorteio, GatekeeperTentativa
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
