import asyncio
from app.services.email_service import send_ticket_email_async
import base64
import os
import uuid
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Request, Depends, Form, Query, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func, or_, desc
from sqlalchemy.orm import selectinload

from app.db.session import get_session
from app.models.all_models import Lote, Usuario, Ingresso, Secretaria, ReservaIngresso, UserRole

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

FOTOS_DIR = "app/static/uploads/fotos"
os.makedirs(FOTOS_DIR, exist_ok=True)
VUE_INDEX_PATH = "app/static/dist/index.html"

def extrair_ip_cliente(request: Request) -> str:
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()
    x_fwd = request.headers.get("x-forwarded-for")
    if x_fwd:
        return x_fwd.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"

def validar_cpf_matematico(cpf: str) -> bool:
    """Validação matemática oficial do CPF (módulo 11 com 2 dígitos verificadores)"""
    cpf_limpo = "".join([c for c in cpf if c.isdigit()])
    if len(cpf_limpo) != 11:
        return False
    # Rejeita dígitos repetidos (ex: 000.000.000-00, 111.111.111-11)
    if len(set(cpf_limpo)) == 1:
        return False

    # 1º Dígito Verificador
    soma = sum(int(cpf_limpo[i]) * (10 - i) for i in range(9))
    resto = (soma * 10) % 11
    d1 = 0 if resto == 10 else resto
    if d1 != int(cpf_limpo[9]):
        return False

    # 2º Dígito Verificador
    soma = sum(int(cpf_limpo[i]) * (11 - i) for i in range(10))
    resto = (soma * 10) % 11
    d2 = 0 if resto == 10 else resto
    if d2 != int(cpf_limpo[10]):
        return False

    return True


# ============================================================================
# 1. VALIDAÇÃO DE CPF EM SEGUNDO PLANO
# ============================================================================
@router.get("/api/resgate/validar-cpf")
async def validar_cpf_resgate(
    cpf: str = Query(..., description="CPF com ou sem pontuação"),
    session: AsyncSession = Depends(get_session)
):
    cpf_limpo = "".join([ch for ch in cpf if ch.isdigit()])
    if len(cpf_limpo) != 11:
        return JSONResponse(content={
            "valido": False,
            "tipo_erro": "formato_invalido",
            "mensagem": "CPF incompleto. Digite os 11 dígitos."
        })

    # Validação matemática do CPF (Dígitos Verificadores)
    if not validar_cpf_matematico(cpf_limpo):
        return JSONResponse(content={
            "valido": False,
            "tipo_erro": "cpf_invalido",
            "mensagem": "CPF inválido. Verifique os números digitados."
        })

    # Busca se o usuário já existe na base
    stmt_usuario = select(Usuario).where(
        Usuario.cpf == cpf_limpo,
        Usuario.deleted_at.is_(None)
    )
    res_usuario = await session.execute(stmt_usuario)
    usuario = res_usuario.scalars().first()

    if usuario:
        # i. Se o CPF pertence a alguém da equipe do evento
        if usuario.role != UserRole.servidor:
            return JSONResponse(content={
                "valido": False,
                "tipo_erro": "equipe",
                "mensagem": "Não é possível resgatar para esse CPF."
            })

        # ii. Se o usuário já possui um ingresso resgatado
        stmt_ing = select(Ingresso).where(
            Ingresso.usuario_id == usuario.id,
            Ingresso.deleted_at.is_(None)
        )
        res_ing = await session.execute(stmt_ing)
        ingresso = res_ing.scalars().first()

        if ingresso:
            return JSONResponse(content={
                "valido": False,
                "tipo_erro": "ingresso_existente",
                "mensagem": "Esse CPF já possui um ingresso."
            })

        # Servidor válido já cadastrado (retorna dados para auto-preenchimento opcional)
        return JSONResponse(content={
            "valido": True,
            "usuario_existente": True,
            "nome": usuario.nome,
            "data_nascimento": usuario.data_nascimento,
            "telefone": usuario.telefone,
            "email": usuario.email,
            "secretaria_id": usuario.secretaria_id,
            "setor": usuario.setor,
            "vinculo": usuario.vinculo
        })

    # Novo servidor não cadastrado anteriormente
    return JSONResponse(content={
        "valido": True,
        "usuario_existente": False
    })


# ============================================================================
# 2. STATUS EM TEMPO REAL DA RESERVA (SINCRONIZAÇÃO CROSS-BROWSER)
# ============================================================================
@router.get("/api/resgate/status-reserva")
async def status_reserva(
    token_reserva: str = Query(...),
    session: AsyncSession = Depends(get_session)
):
    agora = datetime.now()
    stmt = select(ReservaIngresso).where(ReservaIngresso.token == token_reserva)
    res = await session.execute(stmt)
    reserva = res.scalars().first()

    if not reserva:
        return JSONResponse(content={"status": "inexistente", "ativa": False, "motivo": "nao_encontrada"})

    if reserva.utilizada:
        return JSONResponse(content={"status": "utilizada", "ativa": False, "motivo": "utilizada"})

    if reserva.expira_em <= datetime(2000, 1, 2):
        return JSONResponse(content={"status": "desistida", "ativa": False, "motivo": "desistida"})

    if agora > reserva.expira_em:
        return JSONResponse(content={"status": "expirada", "ativa": False, "motivo": "tempo_esgotado"})

    segundos_restantes = max(1, int((reserva.expira_em - agora).total_seconds()))
    return JSONResponse(content={
        "status": "ativa",
        "ativa": True,
        "segundos_restantes": segundos_restantes,
        "expira_em_ms": int(reserva.expira_em.timestamp() * 1000)
    })


# ============================================================================
# 3. DESISTIR DA VAGA RESERVADA (LIBERAÇÃO IMEDIATA)
# ============================================================================
@router.post("/api/resgate/desistir")
async def desistir_reserva(
    request: Request,
    token_reserva: str = Form(...),
    session: AsyncSession = Depends(get_session)
):
    stmt = select(ReservaIngresso).where(
        ReservaIngresso.token == token_reserva
    )
    res = await session.execute(stmt)
    reserva = res.scalars().first()

    if reserva and not reserva.utilizada:
        # Marca com timestamp histórico para indicar explicitamente desistência voluntária
        reserva.expira_em = datetime(2000, 1, 1)
        session.add(reserva)
        await session.commit()

    return JSONResponse(content={
        "sucesso": True,
        "mensagem": "Vaga liberada com sucesso."
    })


# ============================================================================
# 4. PÁGINA E API DE RESGATE COM RESERVA ATÔMICA & CROSS-BROWSER DEVICE ID
# ============================================================================
@router.get("/resgate/{lote_id}")
@router.get("/api/resgate/{lote_id}")
async def pagina_resgate(
    request: Request, 
    lote_id: int, 
    device_fingerprint: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_session)
):
    agora = datetime.now()
    server_time_ms = int(agora.timestamp() * 1000)
    client_ip = extrair_ip_cliente(request)
    
    # Identificador do dispositivo: Prioriza hardware device fingerprint, depois cookie, depois UUID
    header_fp = request.headers.get("x-device-fingerprint")
    cookie_device_id = request.cookies.get("festa_device_id")
    
    device_id = device_fingerprint or header_fp or cookie_device_id
    novo_device_cookie = False

    if not device_id:
        device_id = str(uuid.uuid4())
        novo_device_cookie = True

    # 1. Busca o Lote com bloqueio atômico para controle rigoroso de concorrência
    stmt_lote = select(Lote).where(Lote.id == lote_id).with_for_update()
    res_lote = await session.execute(stmt_lote)
    lote = res_lote.scalars().first()
    if not lote or not lote.ativo:
        if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
            raise HTTPException(status_code=400, detail="Este lote está temporariamente pausado ou inativo pela organização.")
        if os.path.exists(VUE_INDEX_PATH):
            return FileResponse(VUE_INDEX_PATH)
        return templates.TemplateResponse(
            request=request,
            name="erro.html",
            context={"mensagem": "Este lote está temporariamente pausado ou inativo pela organização."}
        )

    # 2. Regra Soberana de Horário
    if lote.data_abertura and agora < lote.data_abertura:
        if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
            raise HTTPException(status_code=400, detail=f"O período de resgate deste lote ainda não iniciou. Abertura prevista para {lote.data_abertura.strftime('%d/%m/%Y às %H:%M')}.")
        if os.path.exists(VUE_INDEX_PATH):
            return FileResponse(VUE_INDEX_PATH)
        return templates.TemplateResponse(
            request=request,
            name="erro.html",
            context={"mensagem": f"O período de resgate deste lote ainda não iniciou. Abertura prevista para {lote.data_abertura.strftime('%d/%m/%Y às %H:%M')}."}
        )

    if lote.data_fechamento and agora > lote.data_fechamento:
        if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
            raise HTTPException(status_code=400, detail="O período de resgate deste lote já foi encerrado.")
        if os.path.exists(VUE_INDEX_PATH):
            return FileResponse(VUE_INDEX_PATH)
        return templates.TemplateResponse(
            request=request,
            name="erro.html",
            context={"mensagem": "O período de resgate deste lote já foi encerrado."}
        )

    # 3. VERIFICA SE ESTE DISPOSITIVO JÁ POSSUI UMA RESERVA ATIVA EM ANDAMENTO
    # Permite 1 única reserva ativa por dispositivo (independente do navegador que ele usar)
    stmt_existente = (
        select(ReservaIngresso)
        .where(
            ReservaIngresso.lote_id == lote.id,
            ReservaIngresso.utilizada == False,
            ReservaIngresso.expira_em > agora,
            or_(
                ReservaIngresso.device_id == device_id,
                ReservaIngresso.device_id == cookie_device_id
            )
        )
        .order_by(desc(ReservaIngresso.expira_em))
    )
    res_existente = await session.execute(stmt_existente)
    reserva_existente = res_existente.scalars().first()

    if reserva_existente:
        # Re-atacha à reserva existente do mesmo dispositivo
        token_reserva = reserva_existente.token
        reserva_expira_em_ms = int(reserva_existente.expira_em.timestamp() * 1000)
        tempo_restante_segundos = max(1, int((reserva_existente.expira_em - agora).total_seconds()))
    else:
        # 4. Se não tem reserva existente, verifica vagas disponíveis no lote
        stmt_reservas = (
            select(func.count(ReservaIngresso.id))
            .where(
                ReservaIngresso.lote_id == lote.id,
                ReservaIngresso.utilizada == False,
                ReservaIngresso.expira_em > agora
            )
        )
        res_count = await session.execute(stmt_reservas)
        reservas_ativas = res_count.scalar() or 0

        vagas_disponiveis = lote.quantidade_total - (lote.quantidade_resgatada + reservas_ativas)

        if vagas_disponiveis <= 0:
            if lote.quantidade_resgatada >= lote.quantidade_total:
                msg = "Todos os ingressos deste lote já foram resgatados."
            else:
                msg = "Todas as vagas restantes estão temporariamente em processo de preenchimento por outros servidores. Aguarde alguns instantes na tela inicial para tentar caso alguma vaga seja liberada."
            
            if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
                raise HTTPException(status_code=400, detail=msg)
            if os.path.exists(VUE_INDEX_PATH):
                return FileResponse(VUE_INDEX_PATH)
            return templates.TemplateResponse(
                request=request,
                name="erro.html",
                context={"mensagem": msg}
            )

        # 5. Cria uma Nova Reserva Ativa de 5 Minutos vinculada a este dispositivo
        token_reserva = str(uuid.uuid4())
        expira_em = agora + timedelta(minutes=5)
        
        nova_reserva = ReservaIngresso(
            token=token_reserva,
            lote_id=lote.id,
            criada_em=agora,
            expira_em=expira_em,
            utilizada=False,
            ip_origem=client_ip,
            device_id=device_id
        )
        session.add(nova_reserva)
        await session.commit()
        reserva_expira_em_ms = int(expira_em.timestamp() * 1000)
        tempo_restante_segundos = 300

    if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
        return JSONResponse(content={
            "token_reserva": token_reserva,
            "server_time_ms": server_time_ms,
            "reserva_expira_em_ms": reserva_expira_em_ms,
            "tempo_restante_segundos": tempo_restante_segundos
        })

    if os.path.exists(VUE_INDEX_PATH):
        response = FileResponse(VUE_INDEX_PATH)
    else:
        stmt_sec = select(Secretaria).order_by(Secretaria.nome)
        res_sec = await session.execute(stmt_sec)
        secretarias = res_sec.scalars().all()

        response = templates.TemplateResponse(
            request=request,
            name="resgate.html",
            context={
                "lote": lote,
                "secretarias": secretarias,
                "token_reserva": token_reserva,
                "server_time_ms": server_time_ms,
                "reserva_expira_em_ms": reserva_expira_em_ms,
                "tempo_restante_segundos": tempo_restante_segundos
            }
        )

    if novo_device_cookie or not cookie_device_id:
        response.set_cookie(
            key="festa_device_id",
            value=device_id,
            max_age=31536000,
            httponly=True,
            samesite="lax"
        )

    return response


# ============================================================================
# 5. PROCESSAMENTO DO RESGATE COM VALIDAÇÃO DE IDADE (18+), EQUIPE E CPF
# ============================================================================
@router.post("/resgate/{lote_id}")
@router.post("/api/resgate/{lote_id}")
async def processar_resgate(
    request: Request, 
    lote_id: int,
    token_reserva: str = Form(...),
    cpf: str = Form(...),
    nome: str = Form(...),
    data_nascimento: str = Form(...),
    setor: str = Form(...),
    secretaria_id: int = Form(...),
    vinculo: str = Form(...),
    telefone: str = Form(...),
    email: str = Form(...),
    foto_base64: str = Form(...),
    session: AsyncSession = Depends(get_session)
):
    agora = datetime.now()
    cpf_limpo = "".join([ch for ch in cpf if ch.isdigit()]).zfill(11)

    # 1. Validação Matemática do CPF
    if not validar_cpf_matematico(cpf_limpo):
        raise HTTPException(
            status_code=400,
            detail="CPF inválido. Verifique os números digitados."
        )

    # 2. Validação da Reserva de 5 Minutos
    stmt_reserva = select(ReservaIngresso).where(
        ReservaIngresso.token == token_reserva,
        ReservaIngresso.lote_id == lote_id
    )
    res_reserva = await session.execute(stmt_reserva)
    reserva = res_reserva.scalars().first()

    if not reserva:
        raise HTTPException(status_code=400, detail="Reserva de vaga inválida ou não encontrada.")

    if reserva.utilizada:
        raise HTTPException(status_code=400, detail="Esta reserva já foi utilizada para emitir um ingresso.")

    if reserva.expira_em <= datetime(2000, 1, 2):
        raise HTTPException(status_code=400, detail="Você desistiu desta vaga por outro navegador.")

    if agora > reserva.expira_em:
        raise HTTPException(
            status_code=400, 
            detail="O seu tempo de 5 minutos para preenchimento expirou. Por favor, inicie um novo resgate na página inicial."
        )

    # 3. Validação de Maioridade (18+ Anos)
    try:
        data_nasc_limpa = data_nascimento.strip()
        if "-" in data_nasc_limpa:
            dt_nasc = datetime.strptime(data_nasc_limpa, "%Y-%m-%d")
        elif "/" in data_nasc_limpa:
            dt_nasc = datetime.strptime(data_nasc_limpa, "%d/%m/%Y")
        else:
            raise ValueError()

        idade = agora.year - dt_nasc.year - ((agora.month, agora.day) < (dt_nasc.month, dt_nasc.day))
        if idade < 18:
            raise HTTPException(
                status_code=400,
                detail="O resgate de ingressos é permitido exclusivamente para maiores de 18 anos."
            )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Data de nascimento inválida.")

    # 4. Validação do Lote com bloqueio atômico
    stmt_lote = select(Lote).where(Lote.id == lote_id).with_for_update()
    res_lote = await session.execute(stmt_lote)
    lote = res_lote.scalars().first()
    if not lote or not lote.ativo:
        raise HTTPException(status_code=400, detail="Este lote foi pausado ou desativado pela organização.")

    if lote.data_abertura and agora < lote.data_abertura:
        raise HTTPException(status_code=400, detail="O lote ainda não está aberto para resgates.")

    if lote.data_fechamento and agora > lote.data_fechamento:
        raise HTTPException(status_code=400, detail="O período de resgate deste lote já foi encerrado.")

    if lote.secretaria_id and lote.secretaria_id != secretaria_id:
        raise HTTPException(status_code=400, detail="Este lote é exclusivo para servidores da secretaria selecionada.")

    # 5. Validação de Unicidade por CPF e Bloqueio de Equipe
    stmt_usuario = select(Usuario).where(
        Usuario.cpf == cpf_limpo,
        Usuario.deleted_at.is_(None)
    )
    res_usuario = await session.execute(stmt_usuario)
    usuario = res_usuario.scalars().first()

    if usuario:
        # Bloqueia membros da equipe do evento
        if usuario.role != UserRole.servidor:
            raise HTTPException(
                status_code=400,
                detail="Não é possível resgatar para esse CPF."
            )

        # Bloqueia duplicidade de ingresso
        stmt_ing_existente = select(Ingresso).where(
            Ingresso.usuario_id == usuario.id,
            Ingresso.deleted_at.is_(None)
        )
        res_ing = await session.execute(stmt_ing_existente)
        if res_ing.scalars().first():
            raise HTTPException(
                status_code=400, 
                detail="Esse CPF já possui um ingresso."
            )

    # 6. Processamento da Foto Facial Obrigatória
    if not foto_base64 or not foto_base64.startswith("data:image"):
        raise HTTPException(status_code=400, detail="A foto facial ao vivo é obrigatória para validação.")

    try:
        header, encoded = foto_base64.split(",", 1)
        foto_bytes = base64.b64decode(encoded)
        nome_arquivo_foto = f"selfie_{cpf_limpo}_{int(datetime.now().timestamp())}.jpg"
        caminho_foto = os.path.join(FOTOS_DIR, nome_arquivo_foto)
        
        with open(caminho_foto, "wb") as f:
            f.write(foto_bytes)
            
        foto_url = f"/static/uploads/fotos/{nome_arquivo_foto}"
    except Exception as e:
        raise HTTPException(status_code=400, detail="Erro ao processar e salvar a foto facial.")

    # 7. Criação ou Atualização do Usuário
    if not usuario:
        usuario = Usuario(
            cpf=cpf_limpo,
            nome=nome.strip(),
            data_nascimento=data_nascimento.strip(),
            setor=setor.strip(),
            secretaria_id=secretaria_id,
            vinculo=vinculo.strip(),
            telefone=telefone.strip(),
            email=email.strip().lower(),
            foto_rosto_url=foto_url,
            role=UserRole.servidor
        )
        session.add(usuario)
        await session.flush()
    else:
        usuario.nome = nome.strip()
        usuario.data_nascimento = data_nascimento.strip()
        usuario.setor = setor.strip()
        usuario.secretaria_id = secretaria_id
        usuario.vinculo = vinculo.strip()
        usuario.telefone = telefone.strip()
        usuario.email = email.strip().lower()
        usuario.foto_rosto_url = foto_url
        session.add(usuario)

    # 8. Emissão do Ingresso Nominal
    qr_token = str(uuid.uuid4())
    novo_ingresso = Ingresso(
        usuario_id=usuario.id,
        lote_id=lote.id,
        qr_code_token=qr_token,
        data_resgate=agora
    )
    session.add(novo_ingresso)

    # 9. Atualização do Lote e Conclusão da Reserva
    lote.quantidade_resgatada += 1
    session.add(lote)

    reserva.utilizada = True
    session.add(reserva)

    await session.commit()

    # Disparo assíncrono do e-mail com QR Code em background
    if email_dest := (usuario.email or "").strip():
        sec_obj = await session.get(Secretaria, secretaria_id) if secretaria_id else None
        sec_nome = sec_obj.nome if sec_obj else None
        cpf_fmt = f"{cpf_limpo[:3]}.{cpf_limpo[3:6]}.{cpf_limpo[6:9]}-{cpf_limpo[9:]}" if len(cpf_limpo) == 11 else cpf_limpo
        asyncio.create_task(
            send_ticket_email_async(
                usuario_nome=usuario.nome,
                usuario_email=email_dest,
                ingresso_token=qr_token,
                lote_nome=lote.nome,
                secretaria_nome=sec_nome,
                setor=usuario.setor,
                cpf_formatado=cpf_fmt
            )
        )

    if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
        return JSONResponse(content={
            "sucesso": True,
            "ingresso_id": novo_ingresso.id,
            "redirect_url": f"/sucesso/{novo_ingresso.id}"
        })

    return RedirectResponse(
        url=f"/sucesso/{novo_ingresso.id}",
        status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/sucesso/{ingresso_id}")
@router.get("/api/sucesso/{ingresso_id}")
async def pagina_sucesso(
    request: Request, 
    ingresso_id: int, 
    session: AsyncSession = Depends(get_session)
):
    stmt = (
        select(Ingresso)
        .options(selectinload(Ingresso.usuario), selectinload(Ingresso.lote))
        .where(Ingresso.id == ingresso_id, Ingresso.deleted_at.is_(None))
    )
    res = await session.execute(stmt)
    ingresso = res.scalars().first()

    if not ingresso:
        if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
            raise HTTPException(status_code=404, detail="Ingresso não encontrado ou cancelado.")
        if os.path.exists(VUE_INDEX_PATH):
            return FileResponse(VUE_INDEX_PATH)
        return templates.TemplateResponse(
            request=request, 
            name="erro.html", 
            context={"mensagem": "Ingresso não encontrado ou cancelado."}
        )

    secretaria = None
    if ingresso.usuario and ingresso.usuario.secretaria_id:
        stmt_sec = select(Secretaria).where(Secretaria.id == ingresso.usuario.secretaria_id)
        res_sec = await session.execute(stmt_sec)
        secretaria = res_sec.scalars().first()

    if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
        return JSONResponse(content={
            "id": ingresso.id,
            "qr_code_token": ingresso.qr_code_token,
            "data_resgate": ingresso.data_resgate.isoformat() if ingresso.data_resgate else None,
            "data_resgate_formatada": ingresso.data_resgate.strftime("%d/%m/%Y às %H:%M") if ingresso.data_resgate else None,
            "lote_nome": ingresso.lote.nome if ingresso.lote else "Geral",
            "usuario": {
                "nome": ingresso.usuario.nome if ingresso.usuario else "Servidor",
                "cpf_formatado": f"{ingresso.usuario.cpf[:3]}.***.***-{ingresso.usuario.cpf[-2:]}" if ingresso.usuario and len(ingresso.usuario.cpf) == 11 else (ingresso.usuario.cpf if ingresso.usuario else ""),
                "setor": ingresso.usuario.setor if ingresso.usuario else "",
                "secretaria_nome": secretaria.nome if secretaria else "Geral",
                "foto_rosto_url": ingresso.usuario.foto_rosto_url if ingresso.usuario else None
            }
        })

    if os.path.exists(VUE_INDEX_PATH):
        response = FileResponse(VUE_INDEX_PATH)

    return templates.TemplateResponse(
        request=request,
        name="sucesso.html",
        context={
            "ingresso": ingresso,
            "secretaria": secretaria
        }
    )
