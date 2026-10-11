import json
from sqlalchemy import BigInteger, Column, Text
from datetime import datetime
from enum import Enum
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship


class UserRole(str, Enum):
    admin_geral = "admin_geral"
    admin = "admin"
    servidor = "servidor"
    portaria = "portaria"
    entregador = "entregador"
    validador = "validador"


class MovimentoTipo(str, Enum):
    entrada = "entrada"
    saida = "saida"


class PremioCategoria(str, Enum):
    categoria_1 = "categoria_1"  # Geral / Todos os presentes
    categoria_2 = "categoria_2"  # Eixo Setorial / Grupo de Secretarias


class Eixo(SQLModel, table=True):
    __tablename__ = "eixos"

    id: Optional[int] = Field(default=None, primary_key=True)
    nome: str = Field(index=True)
    descricao: Optional[str] = Field(default=None, nullable=True)

    # Relacionamentos
    secretarias: List["Secretaria"] = Relationship(back_populates="eixo")
    premios: List["Premio"] = Relationship(back_populates="eixo")
    ganhadores: List["Ganhador"] = Relationship(back_populates="eixo")


class Secretaria(SQLModel, table=True):
    __tablename__ = "secretarias"

    id: Optional[int] = Field(default=None, primary_key=True)
    nome: str = Field(index=True)
    sigla: Optional[str] = Field(default=None, nullable=True)
    eixo_id: Optional[int] = Field(default=None, foreign_key="eixos.id", nullable=True)

    # Relacionamentos
    eixo: Optional[Eixo] = Relationship(back_populates="secretarias")
    usuarios: List["Usuario"] = Relationship(back_populates="secretaria")
    lotes: List["Lote"] = Relationship(back_populates="secretaria")


class Usuario(SQLModel, table=True):
    __tablename__ = "usuarios"

    id: Optional[int] = Field(default=None, primary_key=True)
    cpf: str = Field(unique=True, index=True)
    nome: str
    senha_hash: Optional[str] = Field(default=None, nullable=True)
    role: UserRole = Field(default=UserRole.servidor)
    roles: Optional[str] = Field(default=None, nullable=True)
    secretaria_id: Optional[int] = Field(default=None, foreign_key="secretarias.id", nullable=True)
    foto_rosto_url: Optional[str] = Field(default=None, nullable=True)
    validado: bool = Field(default=False)
    data_nascimento: Optional[str] = Field(default=None, nullable=True)
    setor: Optional[str] = Field(default=None, nullable=True)
    vinculo: Optional[str] = Field(default=None, nullable=True)
    telefone: Optional[str] = Field(default=None, nullable=True)
    email: Optional[str] = Field(default=None, nullable=True)
    ultimo_acesso: Optional[datetime] = Field(default=None, nullable=True)
    deleted_at: Optional[datetime] = Field(default=None, nullable=True)
    ativo: bool = Field(default=True)
    session_id: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    session_device_info: Optional[str] = Field(default=None, nullable=True)
    bloqueado_resgate: bool = Field(default=False)
    secretarias_validador: Optional[str] = Field(default=None, nullable=True)
    deve_trocar_senha: bool = Field(default=False)

    # Relacionamentos
    secretaria: Optional[Secretaria] = Relationship(back_populates="usuarios")
    ingressos: List["Ingresso"] = Relationship(back_populates="usuario", sa_relationship_kwargs={"foreign_keys": "[Ingresso.usuario_id]"})
    logs_acesso: List["LogAcesso"] = Relationship(back_populates="usuario", sa_relationship_kwargs={"foreign_keys": "[LogAcesso.usuario_id]"})
    ganhadores: List["Ganhador"] = Relationship(back_populates="usuario", sa_relationship_kwargs={"foreign_keys": "[Ganhador.usuario_id]"})
    solicitacoes_validacao: List["SolicitacaoValidacao"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[SolicitacaoValidacao.usuario_id]"}
    )
    solicitacoes_cancelamento: List["SolicitacaoCancelamento"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[SolicitacaoCancelamento.usuario_id]"}
    )

    def get_active_sessions(self) -> List[dict]:
        if not self.session_id:
            return []
        try:
            data = json.loads(self.session_id)
            if isinstance(data, list):
                return data
        except Exception:
            return [{
                "sid": self.session_id,
                "device": self.session_device_info or "Dispositivo",
                "ts": datetime.now().isoformat()
            }]
        return []

    def set_active_sessions(self, sessions: List[dict]) -> None:
        self.session_id = json.dumps(sessions)
        if sessions:
            self.session_device_info = sessions[-1].get("device", "Dispositivo")
        else:
            self.session_device_info = None

    def add_active_session(self, sid: str, device: str, max_sessions: int = 3) -> None:
        sessions = self.get_active_sessions()
        sessions = [s for s in sessions if s.get("sid") != sid]
        while len(sessions) >= max_sessions:
            sessions.pop(0)
        sessions.append({
            "sid": sid,
            "device": device,
            "ts": datetime.now().isoformat()
        })
        self.set_active_sessions(sessions)

    def remove_active_session(self, sid: Optional[str] = None) -> None:
        if not sid:
            self.session_id = None
            self.session_device_info = None
            return
        sessions = [s for s in self.get_active_sessions() if s.get("sid") != sid]
        self.set_active_sessions(sessions)

    def is_session_valid(self, token_sid: Optional[str]) -> bool:
        if not token_sid:
            return True
        sessions = self.get_active_sessions()
        if not sessions:
            return True
        return any(s.get("sid") == token_sid for s in sessions)

    def get_roles_list(self) -> List[str]:
        if self.roles and self.roles.strip():
            return [r.strip() for r in self.roles.split(",") if r.strip()]
        if self.role:
            r_str = self.role.value if hasattr(self.role, "value") else str(self.role)
            return [r_str]
        return ["servidor"]

    def get_secretarias_validador_ids(self) -> List[int]:
        if not self.secretarias_validador:
            return []
        ids = []
        for s in self.secretarias_validador.split(","):
            s_clean = s.strip()
            if s_clean.isdigit():
                ids.append(int(s_clean))
        return ids

    def has_role(self, *target_roles: str) -> bool:
        user_roles = self.get_roles_list()
        if "admin_geral" in user_roles:
            return True
        return any(tr in user_roles for tr in target_roles)

    @property
    def foto_url(self) -> Optional[str]:
        """Propriedade para compatibilidade com rotas e templates que usam foto_url"""
        return self.foto_rosto_url


class Lote(SQLModel, table=True):
    __tablename__ = "lotes"

    id: Optional[int] = Field(default=None, primary_key=True)
    nome: str
    quantidade_total: int = Field(default=0)
    quantidade_resgatada: int = Field(default=0)
    data_abertura: Optional[datetime] = Field(default=None, nullable=True)
    data_fechamento: Optional[datetime] = Field(default=None, nullable=True)
    ativo: bool = Field(default=True)
    secretaria_id: Optional[int] = Field(default=None, foreign_key="secretarias.id", nullable=True)
    deleted_at: Optional[datetime] = Field(default=None, nullable=True)

    # Relacionamentos
    secretaria: Optional[Secretaria] = Relationship(back_populates="lotes")
    ingressos: List["Ingresso"] = Relationship(back_populates="lote")
    reservas: List["ReservaIngresso"] = Relationship(back_populates="lote")


class Ingresso(SQLModel, table=True):
    __tablename__ = "ingressos"

    id: Optional[int] = Field(default=None, primary_key=True)
    usuario_id: int = Field(foreign_key="usuarios.id", index=True)
    lote_id: int = Field(foreign_key="lotes.id", index=True)
    qr_code_token: str = Field(unique=True, index=True)
    data_resgate: datetime = Field(default_factory=datetime.now)
    deleted_at: Optional[datetime] = Field(default=None, nullable=True)
    cancelado_por_id: Optional[int] = Field(default=None, foreign_key="usuarios.id", nullable=True)
    motivo_cancelamento: Optional[str] = Field(default=None, nullable=True)

    # Relacionamentos
    usuario: Optional[Usuario] = Relationship(back_populates="ingressos", sa_relationship_kwargs={"foreign_keys": "[Ingresso.usuario_id]"})
    lote: Optional[Lote] = Relationship(back_populates="ingressos")
    cancelado_por: Optional[Usuario] = Relationship(sa_relationship_kwargs={"foreign_keys": "[Ingresso.cancelado_por_id]"})


class ReservaIngresso(SQLModel, table=True):
    __tablename__ = "reservas_ingressos"

    id: Optional[int] = Field(default=None, primary_key=True)
    token: str = Field(unique=True, index=True)
    lote_id: int = Field(foreign_key="lotes.id", index=True)
    criada_em: datetime = Field(default_factory=datetime.now)
    expira_em: datetime = Field(index=True)
    utilizada: bool = Field(default=False, index=True)
    ip_origem: Optional[str] = Field(default=None, nullable=True)
    device_id: Optional[str] = Field(default=None, nullable=True, index=True)
    cpf: Optional[str] = Field(default=None, nullable=True, index=True)
    status: str = Field(default="ativa", index=True)
    browser_token_hash: Optional[str] = Field(default=None, nullable=True, index=True)
    device_fingerprint: Optional[str] = Field(default=None, nullable=True)

    # Relacionamentos
    lote: Optional[Lote] = Relationship(back_populates="reservas")


class LogAcesso(SQLModel, table=True):
    __tablename__ = "logs_acesso"

    id: Optional[int] = Field(default=None, primary_key=True)
    usuario_id: int = Field(foreign_key="usuarios.id", index=True)
    operador_id: Optional[int] = Field(default=None, foreign_key="usuarios.id", nullable=True, index=True)
    ingresso_id: Optional[int] = Field(default=None, foreign_key="ingressos.id", nullable=True, index=True)
    tipo: MovimentoTipo = Field(default=MovimentoTipo.entrada, index=True)
    data_hora: datetime = Field(default_factory=datetime.now, index=True)
    device_id: Optional[str] = Field(default=None, nullable=True)
    ip_origem: Optional[str] = Field(default=None, nullable=True)
    metodo_validacao: Optional[str] = Field(default="qr_code", nullable=True)

    # Relacionamentos
    usuario: Optional[Usuario] = Relationship(back_populates="logs_acesso", sa_relationship_kwargs={"foreign_keys": "[LogAcesso.usuario_id]"})
    operador: Optional["Usuario"] = Relationship(sa_relationship_kwargs={"foreign_keys": "[LogAcesso.operador_id]"})
    ingresso: Optional["Ingresso"] = Relationship()


class Premio(SQLModel, table=True):
    __tablename__ = "premios"

    id: Optional[int] = Field(default=None, primary_key=True)
    nome: str = Field(index=True)
    descricao: Optional[str] = Field(default=None, nullable=True)
    foto_url: Optional[str] = Field(default=None, nullable=True)
    categoria: str = Field(default="categoria_1")
    eixo_id: Optional[int] = Field(default=None, foreign_key="eixos.id", nullable=True)
    quantidade: int = Field(default=1)
    quantidade_sorteada: int = Field(default=0)
    ativo: bool = Field(default=True)
    ordem: int = Field(default=0)

    # Relacionamentos
    eixo: Optional[Eixo] = Relationship(back_populates="premios")
    ganhadores: List["Ganhador"] = Relationship(back_populates="premio")


class Ganhador(SQLModel, table=True):
    __tablename__ = "ganhadores"

    id: Optional[int] = Field(default=None, primary_key=True)
    premio_id: int = Field(foreign_key="premios.id", index=True)
    usuario_id: int = Field(foreign_key="usuarios.id", index=True)
    categoria: str = Field(default="categoria_1", index=True)
    eixo_id: Optional[int] = Field(default=None, foreign_key="eixos.id", nullable=True)
    data_sorteio: datetime = Field(default_factory=datetime.now, index=True)
    entregue: bool = Field(default=False, index=True)
    data_entrega: Optional[datetime] = Field(default=None, nullable=True)
    foto_entrega_url: Optional[str] = Field(default=None, nullable=True)
    responsavel_entrega_id: Optional[int] = Field(default=None, foreign_key="usuarios.id", nullable=True)
    anulado: bool = Field(default=False, index=True)
    motivo_anulacao: Optional[str] = Field(default=None, nullable=True)

    # Relacionamentos
    premio: Optional[Premio] = Relationship(back_populates="ganhadores")
    usuario: Optional[Usuario] = Relationship(back_populates="ganhadores", sa_relationship_kwargs={"foreign_keys": "[Ganhador.usuario_id]"})
    eixo: Optional[Eixo] = Relationship(back_populates="ganhadores")
    responsavel_entrega: Optional[Usuario] = Relationship(sa_relationship_kwargs={"foreign_keys": "[Ganhador.responsavel_entrega_id]"})


class EstadoSorteio(SQLModel, table=True):
    __tablename__ = "estado_sorteio"

    id: int = Field(default=1, primary_key=True)
    sorteando: bool = Field(default=False)
    status: str = Field(default="idle")  # idle, preparando, sorteando, finalizado
    timestamp_inicio: int = Field(default=0, sa_column=Column(BigInteger, default=0))
    premio_id: Optional[int] = Field(default=None, nullable=True)
    dados_rodada: Optional[str] = Field(default="[]", nullable=True)


class GatekeeperTentativa(SQLModel, table=True):
    __tablename__ = "gatekeeper_tentativas"

    id: Optional[int] = Field(default=None, primary_key=True)
    ip: str = Field(index=True)
    data_tentativa: datetime = Field(default_factory=datetime.utcnow, index=True)
    sucesso: bool = Field(default=False)


class SolicitacaoCancelamento(SQLModel, table=True):
    __tablename__ = "solicitacoes_cancelamento"

    id: Optional[int] = Field(default=None, primary_key=True)
    token: str = Field(unique=True, index=True)
    usuario_id: int = Field(foreign_key="usuarios.id", index=True)
    ingresso_id: int = Field(foreign_key="ingressos.id", index=True)
    codigo_verificacao: str = Field(index=True)
    codigo_expira_em: datetime = Field(index=True)
    codigo_validado: bool = Field(default=False)
    codigo_tentativas: int = Field(default=0)
    codigo_envios: int = Field(default=1)
    codigo_ultimo_envio_em: Optional[datetime] = Field(default=None, nullable=True, index=True)
    foto_ao_vivo_url: Optional[str] = Field(default=None, nullable=True)
    status: str = Field(default="pendente_codigo", index=True)  # pendente_codigo, pendente_foto, pendente_analise, aprovado, rejeitado
    motivo: Optional[str] = Field(default=None, nullable=True)
    motivo_rejeicao: Optional[str] = Field(default=None, nullable=True)
    analisado_por_id: Optional[int] = Field(default=None, foreign_key="usuarios.id", nullable=True)
    analisado_em: Optional[datetime] = Field(default=None, nullable=True)
    criado_em: datetime = Field(default_factory=datetime.now, index=True)
    ip_origem: Optional[str] = Field(default=None, nullable=True)

    # Relacionamentos
    usuario: Optional["Usuario"] = Relationship(sa_relationship_kwargs={"foreign_keys": "[SolicitacaoCancelamento.usuario_id]"})
    ingresso: Optional["Ingresso"] = Relationship()
    analisado_por: Optional["Usuario"] = Relationship(sa_relationship_kwargs={"foreign_keys": "[SolicitacaoCancelamento.analisado_por_id]"})


class BackupLote(SQLModel, table=True):
    __tablename__ = "backups_lotes"

    id: Optional[int] = Field(default=None, primary_key=True)
    lote_id: int = Field(index=True)
    lote_nome: str
    dados_json: str  # JSON completo com metadados do lote e lista de ingressos
    total_ingressos: int = Field(default=0)
    excluido_em: datetime = Field(default_factory=datetime.now, index=True)
    expira_em: datetime = Field(index=True)  # 3 dias de retenção obrigatória
    excluido_por_id: Optional[int] = Field(default=None, foreign_key="usuarios.id", nullable=True)
    excluido_por_nome: Optional[str] = Field(default=None, nullable=True)
    ip_origem: Optional[str] = Field(default=None, nullable=True)
    restaurado: bool = Field(default=False, index=True)
    restaurado_em: Optional[datetime] = Field(default=None, nullable=True)
    restaurado_por_id: Optional[int] = Field(default=None, foreign_key="usuarios.id", nullable=True)

    # Relacionamentos
    excluido_por: Optional["Usuario"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[BackupLote.excluido_por_id]"}
    )
    restaurado_por: Optional["Usuario"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[BackupLote.restaurado_por_id]"}
    )


class TokenExclusaoLote(SQLModel, table=True):
    __tablename__ = "tokens_exclusao_lote"

    id: Optional[int] = Field(default=None, primary_key=True)
    token: str = Field(unique=True, index=True)
    lote_id: int = Field(foreign_key="lotes.id", index=True)
    usuario_id: int = Field(foreign_key="usuarios.id", index=True)
    codigo_verificacao: str = Field(index=True)
    codigo_expira_em: datetime = Field(index=True)
    utilizado: bool = Field(default=False)
    tentativas: int = Field(default=0)
    criado_em: datetime = Field(default_factory=datetime.now)

    # Relacionamentos
    lote: Optional[Lote] = Relationship()
    usuario: Optional["Usuario"] = Relationship()


class SolicitacaoValidacao(SQLModel, table=True):
    __tablename__ = "solicitacoes_validacao"

    id: Optional[int] = Field(default=None, primary_key=True)
    token: Optional[str] = Field(default=None, unique=True, index=True, nullable=True)
    usuario_id: int = Field(foreign_key="usuarios.id", index=True)
    lote_id: int = Field(foreign_key="lotes.id", index=True)
    secretaria_id: Optional[int] = Field(default=None, foreign_key="secretarias.id", nullable=True, index=True)
    status: str = Field(default="pendente_analise", index=True)  # pendente_analise, aprovado, rejeitado
    motivo_rejeicao: Optional[str] = Field(default=None, nullable=True)
    analisado_por_id: Optional[int] = Field(default=None, foreign_key="usuarios.id", nullable=True)
    analisado_em: Optional[datetime] = Field(default=None, nullable=True)
    criado_em: datetime = Field(default_factory=datetime.now, index=True)
    ip_origem: Optional[str] = Field(default=None, nullable=True)
    identificado_api: bool = Field(default=False, index=True)
    comunicado: bool = Field(default=False, index=True)
    comunicado_em: Optional[datetime] = Field(default=None, nullable=True)

    # Relacionamentos
    usuario: Optional["Usuario"] = Relationship(sa_relationship_kwargs={"foreign_keys": "[SolicitacaoValidacao.usuario_id]"})
    lote: Optional["Lote"] = Relationship()
    secretaria: Optional["Secretaria"] = Relationship()
    analisado_por: Optional["Usuario"] = Relationship(sa_relationship_kwargs={"foreign_keys": "[SolicitacaoValidacao.analisado_por_id]"})


class RateLimitTentativa(SQLModel, table=True):
    __tablename__ = "rate_limit_tentativas"

    id: Optional[int] = Field(default=None, primary_key=True)
    ip: str = Field(index=True)
    acao: str = Field(default="reserva", index=True)
    criado_em: datetime = Field(default_factory=datetime.utcnow, index=True)


class LoginRateLimit(SQLModel, table=True):
    __tablename__ = "login_rate_limits"

    id: Optional[int] = Field(default=None, primary_key=True)
    ip: str = Field(index=True, unique=True)
    tentativas_atuais: int = Field(default=0)
    estagio_bloqueio: int = Field(default=0)
    bloqueado_ate: Optional[datetime] = Field(default=None, index=True)
    ultima_tentativa: datetime = Field(default_factory=datetime.utcnow, index=True)


class FaqItem(SQLModel, table=True):
    __tablename__ = "faq_items"

    id: Optional[int] = Field(default=None, primary_key=True)
    pergunta: str = Field(sa_column=Column(Text, nullable=False))
    resposta: str = Field(sa_column=Column(Text, nullable=False))
    ordem: int = Field(default=0, index=True)
    ativo: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
