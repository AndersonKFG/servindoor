"""Acesso público restrito a um lote oculto, sem liberar o gatekeeper global."""
from datetime import datetime, timedelta, timezone
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func
from starlette.concurrency import run_in_threadpool

from app.core.http_protection import ResgateFormRoute
from app.core.security import extrair_ip_cliente, verify_password
from app.db.session import get_session
from app.models.all_models import Lote, ReservaIngresso, RateLimitTentativa, Secretaria
from app.services.lotes_ocultos import configuracao, conferir_autorizacao, criar_autorizacao, instante_utc
from app.routers import resgate

router = APIRouter(prefix="/api/avulso", route_class=ResgateFormRoute)


async def obter_lote(token, session, request=None, lock=False):
    stmt = select(Lote).where(Lote.acesso_token == token, Lote.oculto == True,
                              Lote.deleted_at.is_(None))
    if lock:
        stmt = stmt.with_for_update()
    lote = (await session.execute(stmt)).scalars().first()
    if not lote:
        raise HTTPException(404, "Link indisponível ou invalidado.")
    if request is not None:
        conferir_autorizacao(request, lote)
    return lote


async def limitar(session, request, lote, acao, limite):
    agora = datetime.now(timezone.utc)
    chave = f"avulso:{acao}:{lote.id}"
    ip = extrair_ip_cliente(request)
    total = await session.scalar(select(func.count(RateLimitTentativa.id)).where(
        RateLimitTentativa.acao == chave, RateLimitTentativa.ip == ip,
        RateLimitTentativa.criado_em > agora - timedelta(minutes=1)))
    if (total or 0) >= limite:
        raise HTTPException(429, "Muitas tentativas. Aguarde um minuto.")
    session.add(RateLimitTentativa(ip=ip, acao=chave, criado_em=agora))


def dados(lote):
    return {"id": lote.id, "nome": lote.nome, "config": configuracao(lote),
            "tem_senha": bool(lote.acesso_senha_hash)}


@router.post("/{token}/acesso")
async def acesso(token: str, request: Request, session: AsyncSession = Depends(get_session)):
    lote = await obter_lote(token, session, lock=True)
    await limitar(session, request, lote, "senha", 10)
    body = await request.json()
    senha = body.get("senha", "") if isinstance(body, dict) else ""
    valido = not lote.acesso_senha_hash or (
        isinstance(senha, str) and len(senha) == 6 and
        await run_in_threadpool(verify_password, senha, lote.acesso_senha_hash))
    await session.commit()  # Inclusive tentativas incorretas sobrevivem ao erro.
    if not valido:
        return JSONResponse({"detail": "Informe a senha de acesso do lote.", "senha_necessaria": True}, status_code=403)
    return JSONResponse({**dados(lote), "autorizacao": criar_autorizacao(lote)},
                        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@router.post("/{token}/iniciar")
async def iniciar(token: str, request: Request, session: AsyncSession = Depends(get_session)):
    lote = await obter_lote(token, session, request, lock=True)
    agora = datetime.now(timezone.utc)
    if (not lote.ativo or (lote.data_abertura and agora < instante_utc(lote.data_abertura))
            or (lote.data_fechamento and agora > instante_utc(lote.data_fechamento))):
        raise HTTPException(400, "Este lote está indisponível para resgate.")
    browser_token, browser_hash, _ = resgate.obter_ou_criar_browser_id(request)
    anterior = request.headers.get("x-reserva-token")
    reserva = (await session.execute(select(ReservaIngresso).where(
        ReservaIngresso.token == anterior, ReservaIngresso.lote_id == lote.id,
        ReservaIngresso.browser_token_hash == browser_hash,
        ReservaIngresso.acesso_versao == lote.acesso_versao,
        ReservaIngresso.status.in_(["ativa", "rascunho"]),
    ))).scalars().first() if anterior else None
    if reserva and reserva.status == "ativa" and instante_utc(reserva.expira_em) <= agora:
        reserva.status = "expirada"
        reserva = None
    if not reserva:
        await limitar(session, request, lote, "inicio", 60)
        temporizado = configuracao(lote)["temporizado"]
        if temporizado:
            ativas = await session.scalar(select(func.count(ReservaIngresso.id)).where(
                ReservaIngresso.lote_id == lote.id, ReservaIngresso.status == "ativa",
                ReservaIngresso.expira_em > agora))
            if lote.quantidade_resgatada + (ativas or 0) >= lote.quantidade_total:
                raise HTTPException(409, "Todas as vagas estão ocupadas ou em preenchimento.")
        reserva = ReservaIngresso(token=secrets.token_urlsafe(32), lote_id=lote.id,
            browser_token_hash=browser_hash, acesso_versao=lote.acesso_versao,
            criada_em=agora, expira_em=agora + timedelta(minutes=5),
            status="ativa" if temporizado else "rascunho", ip_origem=extrair_ip_cliente(request))
        session.add(reserva)
    await session.commit()
    response = JSONResponse({**dados(lote), "token_reserva": reserva.token,
        "expira_em_ms": int(instante_utc(reserva.expira_em).timestamp() * 1000) if reserva.status == "ativa" else None,
        "server_time_ms": int(agora.timestamp() * 1000)}, headers={"Cache-Control": "no-store"})
    response.set_cookie(resgate.COOKIE_BROWSER_ID, browser_token, httponly=True,
                        secure=resgate.is_conexao_segura(request), samesite="lax", max_age=31536000)
    return response


@router.get("/{token}/status")
async def status(token: str, request: Request, session: AsyncSession = Depends(get_session)):
    lote = await obter_lote(token, session, request)
    return JSONResponse(dados(lote), headers={"Cache-Control": "no-store"})


@router.get("/{token}/secretarias")
async def secretarias(token: str, request: Request, session: AsyncSession = Depends(get_session)):
    await obter_lote(token, session, request)
    rows = (await session.execute(select(Secretaria).order_by(Secretaria.nome))).scalars().all()
    return [{"id": s.id, "nome": s.nome, "sigla": s.sigla} for s in rows]


@router.get("/{token}/validar-cpf")
async def validar_cpf(token: str, request: Request, session: AsyncSession = Depends(get_session)):
    lote = await obter_lote(token, session, request, lock=True)
    await limitar(session, request, lote, "cpf", 60)
    await session.commit()
    valido, codigo, mensagem, _ = await resgate.verificar_elegibilidade_participante(
        resgate.limpar_cpf(request.query_params.get("cpf", "")), session)
    return {"valido": valido, "tipo_erro": codigo, "mensagem": mensagem}


@router.post("/{token}/resgatar")
async def resgatar(token: str, request: Request, session: AsyncSession = Depends(get_session)):
    lote = await obter_lote(token, session, request)
    form = await request.form()
    campos = ("token_reserva", "cpf", "nome", "data_nascimento", "setor", "secretaria_id",
              "vinculo", "telefone", "email", "foto_base64")
    if any(not isinstance(form.get(c), str) or not form[c].strip() for c in campos):
        raise HTTPException(400, "Todos os campos do formulário e a foto são obrigatórios.")
    valores = {c: form[c] for c in campos}
    if not valores["secretaria_id"].isdigit():
        raise HTTPException(400, "Secretaria inválida.")
    valores["secretaria_id"] = int(valores["secretaria_id"])
    return await resgate.processar_resgate(request=request, lote_id=lote.id, session=session, **valores)


@router.get("/{token}/confirmacao")
async def confirmacao(token: str, request: Request, session: AsyncSession = Depends(get_session)):
    lote = await obter_lote(token, session, request)
    return await resgate.recuperar_confirmacao_resgate(request=request, lote_id=lote.id,
        token_reserva=request.query_params.get("token_reserva", ""),
        cpf=request.query_params.get("cpf", ""), session=session)


@router.post("/{token}/desistir")
async def desistir(token: str, request: Request, session: AsyncSession = Depends(get_session)):
    lote = await obter_lote(token, session, request, lock=True)
    form = await request.form()
    reserva = (await session.execute(select(ReservaIngresso).where(
        ReservaIngresso.token == form.get("token_reserva"), ReservaIngresso.lote_id == lote.id,
    ).with_for_update())).scalars().first()
    _, browser_hash, _ = resgate.obter_ou_criar_browser_id(request)
    if not reserva or reserva.browser_token_hash != browser_hash:
        raise HTTPException(403, "Reserva não autorizada.")
    if reserva.status in ("ativa", "rascunho"):
        reserva.status = "cancelada"
        await session.commit()
    return {"sucesso": True}
