from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine
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


async def migrar_fuso_reservas(conn: AsyncConnection) -> None:
    """Converte o horário local legado para instantes com fuso, uma única vez."""
    if conn.dialect.name != "postgresql":
        return

    # UTCDateTime (SQLModel) espera timestamptz. Nas colunas antigas, o
    # PostgreSQL gravava o horário de São Paulo sem o offset; a leitura pelo
    # ORM o rotulava como UTC, antecipando a expiração em três horas.
    await conn.execute(text("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'reservas_ingressos'
                  AND column_name = 'criada_em'
                  AND data_type = 'timestamp without time zone'
            ) THEN
                ALTER TABLE reservas_ingressos
                ALTER COLUMN criada_em TYPE TIMESTAMPTZ
                USING criada_em AT TIME ZONE 'America/Sao_Paulo';
            END IF;
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'reservas_ingressos'
                  AND column_name = 'expira_em'
                  AND data_type = 'timestamp without time zone'
            ) THEN
                ALTER TABLE reservas_ingressos
                ALTER COLUMN expira_em TYPE TIMESTAMPTZ
                USING expira_em AT TIME ZONE 'America/Sao_Paulo';
            END IF;
        END $$;
    """))


async def init_db():
    """Inicializa automaticamente todas as tabelas oficiais do sistema"""
    from app.models.all_models import (
        Usuario, Lote, Ingresso, Secretaria, ReservaIngresso, LogAcesso,
        Eixo, Premio, Ganhador, EstadoSorteio, GatekeeperTentativa, SolicitacaoCancelamento, BackupLote, TokenExclusaoLote, SolicitacaoValidacao, RateLimitTentativa, FaqItem, SponsorLogo
    )
    async with engine.begin() as conn:
        if "postgresql" in str(engine.url):
            await conn.execute(text("SELECT pg_advisory_xact_lock(7429184);"))
        await conn.run_sync(SQLModel.metadata.create_all)
        # Executa sob o mesmo lock de inicialização e antes de expirar reservas.
        await migrar_fuso_reservas(conn)
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS email_queue (
                id BIGSERIAL PRIMARY KEY,
                recipient VARCHAR NOT NULL,
                subject VARCHAR NOT NULL,
                html_body TEXT NOT NULL,
                sender_type VARCHAR NOT NULL DEFAULT 'ticket',
                qr_image BYTEA,
                ticket_image BYTEA,
                status VARCHAR NOT NULL DEFAULT 'queued',
                attempts INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                sent_at TIMESTAMPTZ,
                last_error TEXT
            )
        """))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_email_queue_pending ON email_queue (status, next_attempt_at, id)"))
        await conn.execute(text("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS secretarias_validador VARCHAR;"))
        await conn.execute(text("ALTER TABLE logs_acesso ADD COLUMN IF NOT EXISTS operador_id INTEGER;"))
        await conn.execute(text("ALTER TABLE logs_acesso ADD COLUMN IF NOT EXISTS ingresso_id INTEGER;"))
        await conn.execute(text("ALTER TABLE logs_acesso ADD COLUMN IF NOT EXISTS device_id VARCHAR;"))
        await conn.execute(text("ALTER TABLE logs_acesso ADD COLUMN IF NOT EXISTS ip_origem VARCHAR;"))
        await conn.execute(text("ALTER TABLE logs_acesso ADD COLUMN IF NOT EXISTS metodo_validacao VARCHAR;"))
        await conn.execute(text("ALTER TABLE ingressos ADD COLUMN IF NOT EXISTS cancelado_por_id INTEGER;"))
        await conn.execute(text("ALTER TABLE ingressos ADD COLUMN IF NOT EXISTS motivo_cancelamento VARCHAR;"))
        await conn.execute(text("ALTER TABLE solicitacoes_cancelamento ADD COLUMN IF NOT EXISTS motivo VARCHAR;"))
        await conn.execute(text("ALTER TABLE solicitacoes_cancelamento ADD COLUMN IF NOT EXISTS codigo_envios INTEGER NOT NULL DEFAULT 1;"))
        await conn.execute(text("ALTER TABLE solicitacoes_cancelamento ADD COLUMN IF NOT EXISTS codigo_ultimo_envio_em TIMESTAMPTZ;"))
        await conn.execute(text("UPDATE solicitacoes_cancelamento SET codigo_ultimo_envio_em = criado_em WHERE codigo_ultimo_envio_em IS NULL;"))
        await conn.execute(text("ALTER TABLE solicitacoes_validacao ADD COLUMN IF NOT EXISTS token VARCHAR;"))
        await conn.execute(text("ALTER TABLE solicitacoes_validacao ADD COLUMN IF NOT EXISTS reserva_id INTEGER REFERENCES reservas_ingressos(id);"))
        await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_solicitacao_reserva ON solicitacoes_validacao (reserva_id) WHERE reserva_id IS NOT NULL;"))
        from app.services.resgate_jobs import RESGATE_JOBS_DDL, RESGATE_JOBS_INDEX_DDL
        await conn.execute(text(RESGATE_JOBS_DDL))
        await conn.execute(text(RESGATE_JOBS_INDEX_DDL))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_reservas_ativas ON reservas_ingressos (lote_id, utilizada, expira_em);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_solicitacoes_usuario_lote ON solicitacoes_validacao (usuario_id, lote_id);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_ingressos_usuario_ativo ON ingressos (usuario_id) WHERE deleted_at IS NULL;"))

        # Garantias de Integridade Relacional e Unicidade Crítica
        await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_solicitacoes_token ON solicitacoes_validacao (token) WHERE token IS NOT NULL;"))
        await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_ingressos_usuario_ativo ON ingressos (usuario_id) WHERE deleted_at IS NULL;"))
        await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_solic_usuario_ativa ON solicitacoes_validacao (usuario_id) WHERE status IN ('pendente_analise', 'aprovado');"))

        # Saneamento seguro de premiações duplicadas históricas antes de aplicar a nova restrição global única
        await conn.execute(text("""
            UPDATE ganhadores
            SET anulado = TRUE, motivo_anulacao = 'Saneamento automático: regra de prêmio único por participante'
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM ganhadores
                WHERE anulado = FALSE
                GROUP BY usuario_id
            ) AND anulado = FALSE;
        """))
        # Restrição Global Nova Regra de Negócio: Cada participante só pode ganhar no máximo uma premiação válida
        await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_ganhador_usuario_ativo ON ganhadores (usuario_id) WHERE anulado = FALSE;"))

        # Migracoes e Indices de Exclusividade de Reserva por Participante e Dispositivo
        await conn.execute(text("ALTER TABLE reservas_ingressos ADD COLUMN IF NOT EXISTS cpf VARCHAR;"))
        await conn.execute(text("ALTER TABLE reservas_ingressos ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'ativa';"))
        await conn.execute(text("ALTER TABLE reservas_ingressos ADD COLUMN IF NOT EXISTS browser_token_hash VARCHAR;"))
        await conn.execute(text("ALTER TABLE reservas_ingressos ADD COLUMN IF NOT EXISTS device_fingerprint VARCHAR;"))

        # Saneamento de dados historicos de reservas existentes
        await conn.execute(text('''
            UPDATE reservas_ingressos
            SET status = 'concluida'
            WHERE (utilizada = TRUE) AND status = 'ativa';
        '''))
        await conn.execute(text('''
            UPDATE reservas_ingressos
            SET status = 'cancelada'
            WHERE expira_em <= '2000-01-02 00:00:00' AND status = 'ativa';
        '''))
        await conn.execute(text('''
            UPDATE reservas_ingressos
            SET status = 'expirada'
            WHERE expira_em < CURRENT_TIMESTAMP AND status = 'ativa';
        '''))

        # Indices estaticos para integridade no PostgreSQL e SQLite
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_reservas_status_expira ON reservas_ingressos (status, expira_em);"))
        await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_reserva_cpf_ativa ON reservas_ingressos (cpf) WHERE status = 'ativa';"))
        await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_reserva_browser_ativa ON reservas_ingressos (browser_token_hash) WHERE status = 'ativa';"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_rate_limit_ip_acao_ts ON rate_limit_tentativas (ip, acao, criado_em);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_reserva_capacidade_ativa ON reservas_ingressos (lote_id, expira_em) WHERE status = 'ativa';"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_reserva_fingerprint_ativa ON reservas_ingressos (device_fingerprint, expira_em DESC) WHERE status = 'ativa';"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_reserva_device_ativa ON reservas_ingressos (device_id, expira_em DESC) WHERE status = 'ativa';"))
