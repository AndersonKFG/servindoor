"""Contratos de acesso e configuração dos cadastros avulsos."""
import json
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from jose import JWTError, jwt
from sqlmodel import select, update

from app.core.config import settings
from app.core.security import get_password_hash
from app.models.all_models import Ingresso, Lote, ReservaIngresso, Secretaria, SolicitacaoValidacao

VINCULOS = ("Efetivo", "Comissionado", "Contrato Temporário", "Estagiário",
            "Terceirizado", "Prestador de Serviço", "Aposentado")
CAMPOS = ("secretaria_id", "setor", "vinculo")


def instante_utc(valor):
    """Os novos registros são gravados em UTC, inclusive no SQLite de testes."""
    return valor.replace(tzinfo=timezone.utc) if valor.tzinfo is None else valor.astimezone(timezone.utc)


def configuracao(lote):
    dados = json.loads(lote.avulso_config or "{}")
    return {"temporizado": dados.get("temporizado", True),
            "exige_validacao": dados.get("exige_validacao", True),
            "campos": {nome: dados.get("campos", {}).get(nome, {"modo": "livre", "valor": ""})
                       for nome in CAMPOS}}


async def validar_configuracao(dados, session, secretaria_exclusiva=None):
    if not isinstance(dados, dict) or set(dados) - {"temporizado", "exige_validacao", "campos"}:
        raise HTTPException(400, "Configuração de cadastro avulso inválida.")
    resultado = {}
    for chave in ("temporizado", "exige_validacao"):
        valor = dados.get(chave, True)
        if not isinstance(valor, bool):
            raise HTTPException(400, "As opções de prazo e validação devem ser booleanas.")
        resultado[chave] = valor
    campos = dados.get("campos", {})
    if not isinstance(campos, dict) or set(campos) - set(CAMPOS):
        raise HTTPException(400, "Somente secretaria, setor e vínculo são configuráveis.")
    resultado["campos"] = {}
    for nome in CAMPOS:
        campo = campos.get(nome, {"modo": "livre", "valor": ""})
        if not isinstance(campo, dict) or set(campo) - {"modo", "valor"}:
            raise HTTPException(400, "Configuração de campo inválida.")
        modo = campo.get("modo", "livre")
        if modo not in ("livre", "preenchido", "fixo"):
            raise HTTPException(400, "Modo de campo inválido.")
        valor = str(campo.get("valor", "")).strip() if modo != "livre" else ""
        if modo != "livre":
            if not valor or len(valor) > 200:
                raise HTTPException(400, "Informe um valor válido para cada campo configurado.")
            if nome == "secretaria_id":
                if not valor.isdigit() or not await session.get(Secretaria, int(valor)):
                    raise HTTPException(400, "Escolha uma secretaria cadastrada.")
                if secretaria_exclusiva and int(valor) != secretaria_exclusiva:
                    raise HTTPException(400, "O preenchimento deve respeitar a secretaria exclusiva do lote.")
            if nome == "vinculo" and valor not in VINCULOS:
                raise HTTPException(400, "Escolha um vínculo válido.")
        resultado["campos"][nome] = {"modo": modo, "valor": valor}
    return json.dumps(resultado, ensure_ascii=False)


def senha_hash(senha):
    if senha == "":
        return None
    if not isinstance(senha, str) or len(senha) != 6:
        raise HTTPException(400, "A senha do lote deve ter exatamente 6 caracteres.")
    hashed = get_password_hash(senha)
    if hashed == senha:
        raise HTTPException(503, "Proteção de senha indisponível.")
    return hashed


def criar_autorizacao(lote):
    return jwt.encode({"tipo": "lote_oculto", "lote_id": lote.id,
                       "versao": lote.acesso_versao,
                       "exp": datetime.now(timezone.utc) + timedelta(days=7)},
                      settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def ler_autorizacao(request):
    try:
        payload = jwt.decode(request.headers.get("x-lote-acesso", ""), settings.SECRET_KEY,
                             algorithms=[settings.ALGORITHM])
        return payload if payload.get("tipo") == "lote_oculto" else None
    except JWTError:
        return None


def conferir_autorizacao(request, lote):
    if not lote:
        raise HTTPException(404, "Lote não encontrado.")
    if not lote.oculto:
        return
    grant = ler_autorizacao(request)
    if (not grant or grant.get("lote_id") != lote.id
            or grant.get("versao") != lote.acesso_versao):
        raise HTTPException(403, "Acesso invalidado. Abra novamente o link do lote e reinicie o formulário.")


async def revogar_acessos(lote, session, novo_link=False):
    lote.acesso_versao += 1
    if novo_link:
        lote.acesso_token = secrets.token_urlsafe(32)
    await session.execute(update(ReservaIngresso).where(
        ReservaIngresso.lote_id == lote.id,
        ReservaIngresso.status.in_(["ativa", "rascunho"]),
    ).values(status="cancelada"))


def eh_superadmin(usuario):
    return "admin_geral" in usuario.get_roles_list()


async def exigir_gestao_lote(session, usuario, lote_id):
    if eh_superadmin(usuario):
        return
    lote = await session.get(Lote, lote_id)
    if lote and lote.oculto and not eh_superadmin(usuario):
        raise HTTPException(403, "Somente superadministradores podem gerenciar cadastros avulsos.")


async def exigir_gestao_participante(session, usuario, usuario_id):
    if eh_superadmin(usuario):
        return
    ingresso = (await session.execute(select(Ingresso.id).join(Lote).where(
        Ingresso.usuario_id == usuario_id, Lote.oculto == True))).scalars().first()
    solicitacao = (await session.execute(select(SolicitacaoValidacao.id).join(Lote).where(
        SolicitacaoValidacao.usuario_id == usuario_id, Lote.oculto == True))).scalars().first()
    if ingresso or solicitacao:
        raise HTTPException(403, "Somente superadministradores podem gerenciar cadastros avulsos.")
