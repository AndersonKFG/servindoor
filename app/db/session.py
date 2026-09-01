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
    """Inicializa automaticamente todas as tabelas do sistema e executa migracoes estruturais"""
    from app.models.all_models import Usuario, Lote, Ingresso, Secretaria, ReservaIngresso, LogAcesso, Eixo, Premio, Ganhador, EstadoSorteio  # noqa
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

        migracoes = [
            "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS data_nascimento VARCHAR;",
            "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS setor VARCHAR;",
            "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS vinculo VARCHAR;",
            "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS telefone VARCHAR;",
            "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS email VARCHAR;",
            "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS ultimo_acesso TIMESTAMP;",
            "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS roles VARCHAR;",
            "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP;",
            "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS ativo BOOLEAN DEFAULT TRUE;",
            "ALTER TABLE ingressos ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP;",
            "ALTER TABLE reservas_ingressos ADD COLUMN IF NOT EXISTS device_id VARCHAR;",
            "ALTER TABLE secretarias ADD COLUMN IF NOT EXISTS sigla VARCHAR;",
            "ALTER TABLE secretarias ADD COLUMN IF NOT EXISTS eixo_id INTEGER REFERENCES eixos(id) ON DELETE SET NULL;",
            "ALTER TABLE premios ADD COLUMN IF NOT EXISTS foto_url VARCHAR;",
            "ALTER TABLE premios ADD COLUMN IF NOT EXISTS categoria VARCHAR DEFAULT 'categoria_1';",
            "ALTER TABLE premios ADD COLUMN IF NOT EXISTS eixo_id INTEGER REFERENCES eixos(id) ON DELETE SET NULL;",
            "ALTER TABLE premios ADD COLUMN IF NOT EXISTS quantidade_sorteada INTEGER DEFAULT 0;",
            "ALTER TABLE premios ADD COLUMN IF NOT EXISTS ativo BOOLEAN DEFAULT TRUE;",
            "ALTER TABLE premios ADD COLUMN IF NOT EXISTS ordem INTEGER DEFAULT 0;",
            "ALTER TABLE premios ADD COLUMN IF NOT EXISTS descricao VARCHAR;",
            "ALTER TABLE premios ADD COLUMN IF NOT EXISTS quantidade INTEGER DEFAULT 1;",
            "ALTER TABLE premios ALTER COLUMN tipo DROP NOT NULL;",
            "ALTER TABLE premios ALTER COLUMN sorteado DROP NOT NULL;",
            "ALTER TABLE premios ALTER COLUMN sorteado SET DEFAULT FALSE;",
            "ALTER TABLE ganhadores ADD COLUMN IF NOT EXISTS categoria VARCHAR DEFAULT 'categoria_1';",
            "ALTER TABLE ganhadores ADD COLUMN IF NOT EXISTS eixo_id INTEGER REFERENCES eixos(id) ON DELETE SET NULL;",
            "ALTER TABLE ganhadores ADD COLUMN IF NOT EXISTS entregue BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE ganhadores ADD COLUMN IF NOT EXISTS data_entrega TIMESTAMP;",
            "ALTER TABLE ganhadores ADD COLUMN IF NOT EXISTS foto_entrega_url VARCHAR;",
            "ALTER TABLE ganhadores ADD COLUMN IF NOT EXISTS responsavel_entrega_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL;",
            "ALTER TABLE ganhadores ADD COLUMN IF NOT EXISTS anulado BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE ganhadores ADD COLUMN IF NOT EXISTS motivo_anulacao VARCHAR;",
            "ALTER TABLE ganhadores ADD COLUMN IF NOT EXISTS data_sorteio TIMESTAMP DEFAULT NOW();",
            "ALTER TABLE ganhadores ALTER COLUMN data_ganho DROP NOT NULL;",
            "ALTER TABLE ganhadores ALTER COLUMN data_ganho SET DEFAULT NOW();",
        ]
        for sql in migracoes:
            try:
                await conn.execute(text(sql))
            except Exception as ex:
                print(f'Nota na migracao ({sql[:40]}...): {ex}')
