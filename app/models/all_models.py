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
    session_id: Optional[str] = Field(default=None, nullable=True)
    session_device_info: Optional[str] = Field(default=None, nullable=True)

    # Relacionamentos
    secretaria: Optional[Secretaria] = Relationship(back_populates="usuarios")
    ingressos: List["Ingresso"] = Relationship(back_populates="usuario")
    logs_acesso: List["LogAcesso"] = Relationship(back_populates="usuario")
    ganhadores: List["Ganhador"] = Relationship(back_populates="usuario", sa_relationship_kwargs={"foreign_keys": "[Ganhador.usuario_id]"})

    def get_roles_list(self) -> List[str]:
        if self.roles and self.roles.strip():
            return [r.strip() for r in self.roles.split(",") if r.strip()]
        if self.role:
            r_str = self.role.value if hasattr(self.role, "value") else str(self.role)
            return [r_str]
        return ["servidor"]

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

    # Relacionamentos
    secretaria: Optional[Secretaria] = Relationship(back_populates="lotes")
    ingressos: List["Ingresso"] = Relationship(back_populates="lote")
    reservas: List["ReservaIngresso"] = Relationship(back_populates="lote")


class Ingresso(SQLModel, table=True):
    __tablename__ = "ingressos"

    id: Optional[int] = Field(default=None, primary_key=True)
    usuario_id: int = Field(foreign_key="usuarios.id")
    lote_id: int = Field(foreign_key="lotes.id")
    qr_code_token: str = Field(unique=True, index=True)
    data_resgate: datetime = Field(default_factory=datetime.now)
    deleted_at: Optional[datetime] = Field(default=None, nullable=True)

    # Relacionamentos
    usuario: Optional[Usuario] = Relationship(back_populates="ingressos")
    lote: Optional[Lote] = Relationship(back_populates="ingressos")


class ReservaIngresso(SQLModel, table=True):
    __tablename__ = "reservas_ingressos"

    id: Optional[int] = Field(default=None, primary_key=True)
    token: str = Field(unique=True, index=True)
    lote_id: int = Field(foreign_key="lotes.id")
    criada_em: datetime = Field(default_factory=datetime.now)
    expira_em: datetime
    utilizada: bool = Field(default=False)
    ip_origem: Optional[str] = Field(default=None, nullable=True)
    device_id: Optional[str] = Field(default=None, nullable=True)

    # Relacionamentos
    lote: Optional[Lote] = Relationship(back_populates="reservas")


class LogAcesso(SQLModel, table=True):
    __tablename__ = "logs_acesso"

    id: Optional[int] = Field(default=None, primary_key=True)
    usuario_id: int = Field(foreign_key="usuarios.id")
    tipo: MovimentoTipo = Field(default=MovimentoTipo.entrada)
    data_hora: datetime = Field(default_factory=datetime.now)

    # Relacionamentos
    usuario: Optional[Usuario] = Relationship(back_populates="logs_acesso")


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
    premio_id: int = Field(foreign_key="premios.id")
    usuario_id: int = Field(foreign_key="usuarios.id")
    categoria: str = Field(default="categoria_1")
    eixo_id: Optional[int] = Field(default=None, foreign_key="eixos.id", nullable=True)
    data_sorteio: datetime = Field(default_factory=datetime.now)
    entregue: bool = Field(default=False)
    data_entrega: Optional[datetime] = Field(default=None, nullable=True)
    foto_entrega_url: Optional[str] = Field(default=None, nullable=True)
    responsavel_entrega_id: Optional[int] = Field(default=None, foreign_key="usuarios.id", nullable=True)
    anulado: bool = Field(default=False)
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
    timestamp_inicio: int = Field(default=0)
    premio_id: Optional[int] = Field(default=None, nullable=True)


class GatekeeperTentativa(SQLModel, table=True):
    __tablename__ = "gatekeeper_tentativas"

    id: Optional[int] = Field(default=None, primary_key=True)
    ip: str = Field(index=True)
    data_tentativa: datetime = Field(default_factory=datetime.utcnow, index=True)
    sucesso: bool = Field(default=False)
