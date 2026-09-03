from pydantic import BaseModel
import json
import time
import base64
import os
import secrets
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Request, Depends, Form, HTTPException, status, Query
from fastapi.responses import JSONResponse, FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func, or_, desc
from sqlalchemy.orm import selectinload

from app.db.session import get_session
from app.models.all_models import (
    Eixo, Secretaria, Usuario, Premio, Ganhador, LogAcesso, EstadoSorteio,
    MovimentoTipo, PremioCategoria, UserRole
)
from app.core.deps import get_current_admin, get_current_staff, get_current_entregador

router = APIRouter()

PREMIOS_DIR = "app/static/uploads/premios"
ENTREGAS_DIR = "app/static/uploads/entregas"
os.makedirs(PREMIOS_DIR, exist_ok=True)
os.makedirs(ENTREGAS_DIR, exist_ok=True)

# Estado em memória para animação do telão
live_sorteio_state = {
    "sorteando": False,
    "timestamp_inicio": 0,
    "premio_id": None
}

class ItemMesaPreparar(BaseModel):
    premio_id: int
    quantidade: int

class PrepararMesaRequest(BaseModel):
    itens: List[ItemMesaPreparar]

@router.get("/api/sorteios/live-telao")
async def live_telao(session: AsyncSession = Depends(get_session)):
    """Retorna o estado do telão de projeção em tempo real com suporte a baterias de prêmios"""
    # 1. Busca estado persistido da mesa de sorteio
    stmt_estado = select(EstadoSorteio).where(EstadoSorteio.id == 1)
    res_estado = await session.execute(stmt_estado)
    estado_atual = res_estado.scalars().first()
    if not estado_atual:
        estado_atual = EstadoSorteio(id=1, status="idle", sorteando=False, timestamp_inicio=0, dados_rodada="[]")
        session.add(estado_atual)
        await session.commit()
        await session.refresh(estado_atual)

    agora_ms = int(datetime.now().timestamp() * 1000)

    # Autotransição: se está sorteando e já passaram pelo menos 13s (13000ms), transiciona para finalizado
    if estado_atual.status == "sorteando" and estado_atual.timestamp_inicio > 0:
        if agora_ms - estado_atual.timestamp_inicio >= 13000:
            estado_atual.status = "finalizado"
            estado_atual.sorteando = False
            session.add(estado_atual)
            await session.commit()
            await session.refresh(estado_atual)

    # 2. Itens preparados da rodada atual
    try:
        premios_rodada = json.loads(estado_atual.dados_rodada or "[]")
    except Exception:
        premios_rodada = []

    # 3. Busca ganhadores QUE AINDA NÃO RESGATARAM O PRÊMIO (entregue == False) e não anulados
    stmt_ultimos = (
        select(Ganhador)
        .where(Ganhador.anulado == False, Ganhador.entregue == False)
        .options(
            selectinload(Ganhador.usuario).selectinload(Usuario.secretaria),
            selectinload(Ganhador.premio).selectinload(Premio.eixo),
            selectinload(Ganhador.eixo)
        )
        .order_by(desc(Ganhador.data_sorteio))
        .limit(100)
    )

    # NÃO DÁ SPOILER: se ainda estiver sorteando, exclui os ganhadores da rodada atual da barra lateral
    if estado_atual.status == "sorteando":
        ids_atuais = [
            it.get("ganhador", {}).get("id")
            for it in premios_rodada
            if it.get("ganhador", {}).get("id")
        ]
        if ids_atuais:
            stmt_ultimos = stmt_ultimos.where(Ganhador.id.not_in(ids_atuais))

    res_ultimos = await session.execute(stmt_ultimos)
    ganhadores_raw = res_ultimos.scalars().all()

    historico = []
    for g in ganhadores_raw:
        u = g.usuario
        p = g.premio
        cpf_u = u.cpf or ""
        cpf_fmt = f"{cpf_u[:3]}.***.***-{cpf_u[-2:]}" if len(cpf_u) == 11 else cpf_u
        historico.append({
            "ganhador_id": g.id,
            "servidor_nome": u.nome if u else "Servidor",
            "servidor_cpf": cpf_fmt,
            "servidor_foto": u.foto_rosto_url or u.foto_url if u else None,
            "secretaria_nome": u.secretaria.nome if u and u.secretaria else "Geral",
            "premio_nome": p.nome if p else "Prêmio",
            "premio_foto": p.foto_url if p else None,
            "data_sorteio": g.data_sorteio.strftime("%H:%M:%S")
        })

    # 4. Busca amostra ampla de servidores presentes para a roleta (sem o limite fixo de 25)
    subq_ultimo_log = (
        select(func.max(LogAcesso.id).label("max_id"))
        .group_by(LogAcesso.usuario_id)
        .subquery()
    )

    stmt_presentes = (
        select(Usuario)
        .join(LogAcesso, LogAcesso.usuario_id == Usuario.id)
        .join(subq_ultimo_log, LogAcesso.id == subq_ultimo_log.c.max_id)
        .where(LogAcesso.tipo == MovimentoTipo.entrada, Usuario.deleted_at.is_(None), Usuario.ativo == True)
        .options(selectinload(Usuario.secretaria))
        .order_by(func.random())
        .limit(60)
    )
    res_presentes = await session.execute(stmt_presentes)
    presentes_raw = res_presentes.scalars().all()

    candidatos_animacao = [
        {
            "id": u.id,
            "nome": u.nome,
            "foto_url": u.foto_rosto_url or u.foto_url,
            "secretaria": u.secretaria.nome if u.secretaria else "Geral"
        }
        for u in presentes_raw
    ]

    return JSONResponse(
        content={
            "status": estado_atual.status,  # idle, preparando, sorteando, finalizado
            "sorteio_em_andamento": estado_atual.sorteando,
            "timestamp_inicio": estado_atual.timestamp_inicio,
            "duracao_ms": 10000,
            "premios_rodada": premios_rodada,
            "candidatos_animacao": candidatos_animacao,
            "ultimos_ganhadores": historico
        },
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
    )


@router.post("/api/sorteios/mesa/preparar")
async def preparar_mesa(
    payload: PrepararMesaRequest,
    session: AsyncSession = Depends(get_session),
    current_user: Usuario = Depends(get_current_admin)
):
    """Prepara os prêmios da rodada que serão exibidos no Telão antes do sorteio"""
    if not payload.itens:
        raise HTTPException(status_code=400, detail="Selecione pelo menos um prêmio para preparar a rodada.")

    premios_rodada = []
    item_counter = 1

    for item_req in payload.itens:
        if item_req.quantidade <= 0:
            continue
        premio = await session.get(Premio, item_req.premio_id)
        if not premio or not premio.ativo:
            raise HTTPException(status_code=404, detail=f"Prêmio ID {item_req.premio_id} não encontrado ou inativo.")

        disponiveis = premio.quantidade - premio.quantidade_sorteada
        if item_req.quantidade > disponiveis:
            raise HTTPException(
                status_code=400,
                detail=f"Quantidade solicitada ({item_req.quantidade}) excede o estoque disponível ({disponiveis}) para '{premio.nome}'."
            )

        eixo_nome = None
        if premio.eixo_id:
            eixo = await session.get(Eixo, premio.eixo_id)
            if eixo:
                eixo_nome = eixo.nome

        categoria_str = premio.categoria.value if hasattr(premio.categoria, "value") else str(premio.categoria)

        for _ in range(item_req.quantidade):
            premios_rodada.append({
                "item_id": f"item_{premio.id}_{item_counter}_{secrets.token_hex(3)}",
                "premio_id": premio.id,
                "premio_nome": premio.nome,
                "premio_descricao": premio.descricao or "",
                "premio_foto": premio.foto_url,
                "categoria": categoria_str,
                "eixo_id": premio.eixo_id,
                "eixo_nome": eixo_nome or "Todos os Presentes",
                "ganhador": None
            })
            item_counter += 1

    if not premios_rodada:
        raise HTTPException(status_code=400, detail="Nenhum item válido para preparar.")

    stmt_estado = select(EstadoSorteio).where(EstadoSorteio.id == 1)
    res_estado = await session.execute(stmt_estado)
    estado = res_estado.scalars().first()
    if not estado:
        estado = EstadoSorteio(id=1)
        session.add(estado)

    estado.status = "preparando"
    estado.sorteando = False
    estado.timestamp_inicio = 0
    estado.dados_rodada = json.dumps(premios_rodada)
    session.add(estado)
    await session.commit()

    return JSONResponse(content={
        "sucesso": True,
        "status": "preparando",
        "premios_rodada": premios_rodada
    })


@router.post("/api/sorteios/mesa/iniciar")
async def iniciar_sorteio_mesa(
    session: AsyncSession = Depends(get_session),
    current_user: Usuario = Depends(get_current_admin)
):
    """Dá o aval para iniciar o sorteio de todos os prêmios preparados na mesa"""
    stmt_estado = select(EstadoSorteio).where(EstadoSorteio.id == 1)
    res_estado = await session.execute(stmt_estado)
    estado = res_estado.scalars().first()
    if not estado or estado.status not in ["preparando", "finalizado"]:
        raise HTTPException(status_code=400, detail="A mesa não está em estado de preparação. Adicione prêmios antes de iniciar.")

    try:
        premios_rodada = json.loads(estado.dados_rodada or "[]")
    except Exception:
        premios_rodada = []

    if not premios_rodada:
        raise HTTPException(status_code=400, detail="Nenhum prêmio preparado na mesa para sortear.")

    # 1. Busca IDs de servidores que estão atualmente DENTRO do evento (último log = entrada)
    subq_ultimo_log = (
        select(func.max(LogAcesso.id).label("max_id"))
        .group_by(LogAcesso.usuario_id)
        .subquery()
    )
    stmt_checkin = (
        select(LogAcesso.usuario_id)
        .join(subq_ultimo_log, LogAcesso.id == subq_ultimo_log.c.max_id)
        .where(LogAcesso.tipo == MovimentoTipo.entrada, Usuario.deleted_at.is_(None), Usuario.ativo == True)
    )
    res_checkin = await session.execute(stmt_checkin)
    presentes_ids = set(res_checkin.scalars().all())

    if not presentes_ids:
        raise HTTPException(status_code=400, detail="Nenhum servidor com check-in ativo registrado na portaria.")

    # 2. Rastreia quem já ganhou nesta rodada para evitar duplicações
    ganhadores_nesta_rodada_ids = set()
    agora = datetime.now()

    for item in premios_rodada:
        premio = await session.get(Premio, item["premio_id"])
        if not premio or not premio.ativo:
            continue

        categoria_alvo = item["categoria"]

        # Busca quem já ganhou nesta categoria
        stmt_ja_ganhou = (
            select(Ganhador.usuario_id)
            .where(
                Ganhador.categoria == categoria_alvo,
                Ganhador.anulado == False
            )
        )
        res_ja_ganhou = await session.execute(stmt_ja_ganhou)
        ja_ganharam_cat = set(res_ja_ganhou.scalars().all())

        candidatos_ids = presentes_ids - ja_ganharam_cat - ganhadores_nesta_rodada_ids

        if not candidatos_ids:
            raise HTTPException(
                status_code=400,
                detail=f"Não há servidores elegíveis suficientes para o prêmio '{premio.nome}' nesta categoria."
            )

        if categoria_alvo == "categoria_2" or categoria_alvo == PremioCategoria.categoria_2:
            if not item.get("eixo_id"):
                raise HTTPException(status_code=400, detail=f"Prêmio '{premio.nome}' de Categoria 2 sem eixo vinculado.")
            stmt_sec_eixo = select(Secretaria.id).where(Secretaria.eixo_id == item["eixo_id"])
            res_sec_eixo = await session.execute(stmt_sec_eixo)
            sec_ids_eixo = set(res_sec_eixo.scalars().all())

            stmt_elegiveis = (
                select(Usuario)
                .where(
                    Usuario.id.in_(candidatos_ids),
                    Usuario.secretaria_id.in_(sec_ids_eixo),
                    Usuario.deleted_at.is_(None),
                    Usuario.ativo == True
                )
                .options(selectinload(Usuario.secretaria))
            )
        else:
            stmt_elegiveis = (
                select(Usuario)
                .where(
                    Usuario.id.in_(candidatos_ids),
                    Usuario.deleted_at.is_(None),
                    Usuario.ativo == True
                )
                .options(selectinload(Usuario.secretaria))
            )

        res_elegiveis = await session.execute(stmt_elegiveis)
        elegiveis = res_elegiveis.scalars().all()

        if not elegiveis:
            raise HTTPException(
                status_code=400,
                detail=f"Nenhum servidor elegível presente encontrado para o prêmio '{premio.nome}'."
            )

        # Sorteia 1 vencedor
        sorteado = secrets.choice(elegiveis)
        ganhadores_nesta_rodada_ids.add(sorteado.id)

        # Registra Ganhador no banco
        novo_ganhador = Ganhador(
            premio_id=premio.id,
            usuario_id=sorteado.id,
            categoria=categoria_alvo,
            eixo_id=item.get("eixo_id"),
            data_sorteio=agora
        )
        session.add(novo_ganhador)
        premio.quantidade_sorteada += 1
        session.add(premio)
        await session.flush()

        # Formata CPF exatamente como 000.***.***-00
        cpf_raw = sorteado.cpf or ""
        cpf_mascarado = f"{cpf_raw[:3]}.***.***-{cpf_raw[-2:]}" if len(cpf_raw) == 11 else cpf_raw

        item["ganhador"] = {
            "ganhador_id": novo_ganhador.id,
            "id": sorteado.id,
            "nome": sorteado.nome,
            "cpf": cpf_mascarado,
            "secretaria": sorteado.secretaria.nome if sorteado.secretaria else "Geral",
            "setor": sorteado.setor or "",
            "vinculo": sorteado.vinculo or "",
            "foto_url": sorteado.foto_rosto_url or sorteado.foto_url
        }

    now_ms = int(datetime.now().timestamp() * 1000)
    estado.status = "sorteando"
    estado.sorteando = True
    estado.timestamp_inicio = now_ms
    estado.dados_rodada = json.dumps(premios_rodada)
    session.add(estado)
    await session.commit()

    return JSONResponse(content={
        "sucesso": True,
        "status": "sorteando",
        "timestamp_inicio": now_ms,
        "duracao_ms": 10000,
        "premios_rodada": premios_rodada
    })


@router.post("/api/sorteios/mesa/limpar")
async def limpar_mesa(
    session: AsyncSession = Depends(get_session),
    current_user: Usuario = Depends(get_current_admin)
):
    """Limpa a mesa para permitir preparar a próxima rodada"""
    stmt_estado = select(EstadoSorteio).where(EstadoSorteio.id == 1)
    res_estado = await session.execute(stmt_estado)
    estado = res_estado.scalars().first()
    if not estado:
        estado = EstadoSorteio(id=1)

    estado.status = "idle"
    estado.sorteando = False
    estado.timestamp_inicio = 0
    estado.dados_rodada = "[]"
    session.add(estado)
    await session.commit()

    return JSONResponse(content={"sucesso": True, "status": "idle"})


@router.post("/api/sorteios/executar/{premio_id}")
async def executar_sorteio(
    premio_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: Usuario = Depends(get_current_admin)
):
    """Executa o sorteio de um prêmio respeitando todas as regras de presença e unicidade por categoria"""
    premio = await session.get(Premio, premio_id)
    if not premio or not premio.ativo:
        raise HTTPException(status_code=404, detail="Prêmio não encontrado ou inativo.")

    if premio.quantidade_sorteada >= premio.quantidade:
        raise HTTPException(status_code=400, detail="Este prêmio já atingiu a quantidade máxima de sorteios.")

    # 1. Busca IDs de servidores que estão atualmente DENTRO do evento (último log = entrada)
    subq_ultimo_log = (
        select(func.max(LogAcesso.id).label("max_id"))
        .group_by(LogAcesso.usuario_id)
        .subquery()
    )
    stmt_checkin = (
        select(LogAcesso.usuario_id)
        .join(subq_ultimo_log, LogAcesso.id == subq_ultimo_log.c.max_id)
        .where(LogAcesso.tipo == MovimentoTipo.entrada, Usuario.deleted_at.is_(None), Usuario.ativo == True)
    )
    res_checkin = await session.execute(stmt_checkin)
    presentes_ids = set(res_checkin.scalars().all())

    if not presentes_ids:
        raise HTTPException(status_code=400, detail="Nenhum servidor com check-in registrado na portaria até o momento.")

    # 2. Busca IDs de servidores que JÁ ganharam nesta mesma categoria
    categoria_alvo = premio.categoria
    stmt_ganhadores_cat = (
        select(Ganhador.usuario_id)
        .where(
            Ganhador.categoria == categoria_alvo,
            Ganhador.anulado == False
        )
    )
    res_ganhadores_cat = await session.execute(stmt_ganhadores_cat)
    ja_ganharam_nesta_cat = set(res_ganhadores_cat.scalars().all())

    # 3. Filtra usuários presentes que ainda não ganharam nesta categoria
    candidatos_ids = presentes_ids - ja_ganharam_nesta_cat

    if not candidatos_ids:
        raise HTTPException(
            status_code=400,
            detail="Todos os servidores presentes já foram sorteados nesta categoria."
        )

    # 4. Se for Categoria 2 (Eixo), filtra apenas secretarias que pertencem ao eixo do prêmio
    if categoria_alvo == PremioCategoria.categoria_2 or str(categoria_alvo) == "categoria_2":
        if not premio.eixo_id:
            raise HTTPException(status_code=400, detail="Prêmio de Categoria 2 deve estar vinculado a um Eixo.")

        stmt_sec_eixo = select(Secretaria.id).where(Secretaria.eixo_id == premio.eixo_id)
        res_sec_eixo = await session.execute(stmt_sec_eixo)
        sec_ids_eixo = set(res_sec_eixo.scalars().all())

        if not sec_ids_eixo:
            raise HTTPException(status_code=400, detail="Nenhuma secretaria está vinculada a este Eixo.")

        stmt_elegiveis = (
            select(Usuario)
            .where(
                Usuario.id.in_(candidatos_ids),
                Usuario.secretaria_id.in_(sec_ids_eixo),
                Usuario.deleted_at.is_(None),
                Usuario.ativo == True
            )
            .options(selectinload(Usuario.secretaria))
        )
    else:
        # Categoria 1: Qualquer secretaria
        stmt_elegiveis = (
            select(Usuario)
            .where(
                Usuario.id.in_(candidatos_ids),
                Usuario.deleted_at.is_(None),
                Usuario.ativo == True
            )
            .options(selectinload(Usuario.secretaria))
        )

    res_elegiveis = await session.execute(stmt_elegiveis)
    elegiveis = res_elegiveis.scalars().all()

    if not elegiveis:
        raise HTTPException(
            status_code=400,
            detail="Nenhum servidor elegível presente encontrado para este sorteio."
        )

    # 5. Sorteio criptograficamente seguro e aleatório
    vencedor = secrets.choice(elegiveis)

    # 6. Registra o Ganhador
    novo_ganhador = Ganhador(
        premio_id=premio.id,
        usuario_id=vencedor.id,
        categoria=categoria_alvo,
        eixo_id=premio.eixo_id,
        data_sorteio=datetime.now(),
        entregue=False,
        anulado=False
    )
    session.add(novo_ganhador)

    # 7. Atualiza contador do prêmio
    premio.quantidade_sorteada += 1
    session.add(premio)

    await session.commit()
    await session.refresh(novo_ganhador)

    # Atualiza estado no banco para sincronização multi-worker
    stmt_est = select(EstadoSorteio).where(EstadoSorteio.id == 1)
    res_est = await session.execute(stmt_est)
    estado_sort = res_est.scalars().first()
    agora_ts = int(datetime.now().timestamp() * 1000)
    if not estado_sort:
        estado_sort = EstadoSorteio(id=1, sorteando=True, timestamp_inicio=agora_ts, premio_id=premio.id)
        session.add(estado_sort)
    else:
        estado_sort.sorteando = True
        estado_sort.timestamp_inicio = agora_ts
        estado_sort.premio_id = premio.id
        session.add(estado_sort)
    await session.commit()

    return JSONResponse(content={
        "sucesso": True,
        "ganhador_id": novo_ganhador.id,
        "servidor_nome": vencedor.nome,
        "premio_nome": premio.nome,
        "categoria": str(categoria_alvo)
    })


@router.post("/api/sorteios/anular/{ganhador_id}")
async def anular_sorteio(
    ganhador_id: int,
    motivo: str = Form("Servidor ausente no momento do sorteio"),
    session: AsyncSession = Depends(get_session),
    current_user: Usuario = Depends(get_current_admin)
):
    """Anula um sorteio e reabre a vaga do prêmio para novo sorteio"""
    ganhador = await session.get(Ganhador, ganhador_id)
    if not ganhador:
        raise HTTPException(status_code=404, detail="Ganhador não encontrado.")

    if ganhador.anulado:
        raise HTTPException(status_code=400, detail="Este sorteio já foi anulado anteriormente.")

    ganhador.anulado = True
    ganhador.motivo_anulacao = motivo
    session.add(ganhador)

    # Devolve a cota ao prêmio
    premio = await session.get(Premio, ganhador.premio_id)
    if premio and premio.quantidade_sorteada > 0:
        premio.quantidade_sorteada -= 1
        session.add(premio)

    # Se estiver nos dados da rodada do telão, marca como anulado
    stmt_est = select(EstadoSorteio).where(EstadoSorteio.id == 1)
    res_est = await session.execute(stmt_est)
    estado = res_est.scalars().first()
    if estado and estado.dados_rodada:
        try:
            itens_rodada = json.loads(estado.dados_rodada)
            alterou = False
            for it in itens_rodada:
                if it.get("ganhador") and it["ganhador"].get("ganhador_id") == ganhador_id:
                    it["ganhador"]["anulado"] = True
                    it["ganhador"]["motivo_anulacao"] = motivo
                    alterou = True
            if alterou:
                estado.dados_rodada = json.dumps(itens_rodada)
                session.add(estado)
        except Exception:
            pass

    await session.commit()

    return JSONResponse(content={"sucesso": True, "mensagem": "Sorteio anulado com sucesso e prêmio reaberto."})


@router.get("/api/sorteios/premios")
async def listar_premios(session: AsyncSession = Depends(get_session)):
    """Lista todos os prêmios com informações de categoria, eixo e contagem de elegíveis"""
    # 1. Contagem de presentes
    stmt_checkin = select(LogAcesso.usuario_id).where(LogAcesso.tipo == MovimentoTipo.entrada, Usuario.deleted_at.is_(None), Usuario.ativo == True).distinct()
    res_checkin = await session.execute(stmt_checkin)
    presentes_ids = set(res_checkin.scalars().all())

    # Ganhadores por categoria
    stmt_g1 = select(Ganhador.usuario_id).where(Ganhador.categoria == PremioCategoria.categoria_1, Ganhador.anulado == False)
    res_g1 = await session.execute(stmt_g1)
    ganhadores_cat1 = set(res_g1.scalars().all())

    stmt_g2 = select(Ganhador.usuario_id).where(Ganhador.categoria == PremioCategoria.categoria_2, Ganhador.anulado == False)
    res_g2 = await session.execute(stmt_g2)
    ganhadores_cat2 = set(res_g2.scalars().all())

    # Busca prêmios
    stmt_premios = (
        select(Premio)
        .options(selectinload(Premio.eixo), selectinload(Premio.ganhadores))
        .order_by(Premio.ordem.asc(), Premio.id.asc())
    )
    res_premios = await session.execute(stmt_premios)
    premios_raw = res_premios.scalars().all()

    # Secretarias por eixo
    stmt_sec = select(Secretaria)
    res_sec = await session.execute(stmt_sec)
    secretarias = res_sec.scalars().all()
    eixo_sec_map = {}
    for s in secretarias:
        if s.eixo_id:
            eixo_sec_map.setdefault(s.eixo_id, set()).add(s.id)

    # Usuários com secretaria
    stmt_users = select(Usuario.id, Usuario.secretaria_id).where(Usuario.id.in_(presentes_ids))
    res_users = await session.execute(stmt_users)
    user_sec_map = dict(res_users.all())

    premios_processados = []
    for p in premios_raw:
        cat_str = p.categoria.value if hasattr(p.categoria, "value") else str(p.categoria)
        
        # Calcula elegíveis presentes para este prêmio
        if cat_str == "categoria_1":
            elegiveis_count = len([uid for uid in presentes_ids if uid not in ganhadores_cat1])
        else:
            sec_ids = eixo_sec_map.get(p.eixo_id, set())
            elegiveis_count = len([
                uid for uid in presentes_ids
                if uid not in ganhadores_cat2 and user_sec_map.get(uid) in sec_ids
            ])

        premios_processados.append({
            "id": p.id,
            "nome": p.nome,
            "descricao": p.descricao,
            "foto_url": p.foto_url,
            "categoria": cat_str,
            "categoria_label": "Categoria 1 (Geral)" if cat_str == "categoria_1" else "Categoria 2 (Eixo Setorial)",
            "eixo_id": p.eixo_id,
            "eixo_nome": p.eixo.nome if p.eixo else None,
            "quantidade": p.quantidade,
            "quantidade_sorteada": p.quantidade_sorteada,
            "disponiveis": max(0, p.quantidade - p.quantidade_sorteada),
            "ativo": p.ativo,
            "ordem": p.ordem,
            "elegiveis_presentes": elegiveis_count
        })

    return JSONResponse(content={"premios": premios_processados, "total_presentes": len(presentes_ids)})


@router.post("/api/sorteios/premios")
async def criar_premio(
    nome: str = Form(...),
    descricao: Optional[str] = Form(None),
    categoria: str = Form("categoria_1"),
    eixo_id: Optional[str] = Form(None),
    quantidade: int = Form(1),
    foto_base64: Optional[str] = Form(None),
    session: AsyncSession = Depends(get_session),
    current_user: Usuario = Depends(get_current_admin)
):
    """Cria um novo prêmio para sorteio"""
    foto_url = None
    if foto_base64 and foto_base64.startswith("data:image"):
        try:
            _, encoded = foto_base64.split(",", 1)
            foto_bytes = base64.b64decode(encoded)
            nome_arquivo = f"premio_{int(datetime.now().timestamp())}_{secrets.token_hex(4)}.jpg"
            caminho = os.path.join(PREMIOS_DIR, nome_arquivo)
            with open(caminho, "wb") as f:
                f.write(foto_bytes)
            foto_url = f"/static/uploads/premios/{nome_arquivo}"
        except Exception as e:
            print("Erro salvando foto do premio:", e)

    eixo_id_val = int(eixo_id) if eixo_id and eixo_id.strip() and eixo_id != "0" else None
    cat_enum = PremioCategoria.categoria_2 if categoria in ["categoria_2", PremioCategoria.categoria_2] else PremioCategoria.categoria_1

    novo_premio = Premio(
        nome=nome.strip(),
        descricao=descricao.strip() if descricao else None,
        foto_url=foto_url,
        categoria=cat_enum,
        eixo_id=eixo_id_val,
        quantidade=quantidade,
        quantidade_sorteada=0,
        ativo=True
    )
    session.add(novo_premio)
    await session.commit()
    await session.refresh(novo_premio)

    return JSONResponse(content={"sucesso": True, "id": novo_premio.id})


@router.put("/api/sorteios/premios/{premio_id}")
async def editar_premio(
    premio_id: int,
    nome: str = Form(...),
    descricao: Optional[str] = Form(None),
    categoria: str = Form("categoria_1"),
    eixo_id: Optional[str] = Form(None),
    quantidade: int = Form(1),
    foto_base64: Optional[str] = Form(None),
    ativo: Optional[bool] = Form(True),
    session: AsyncSession = Depends(get_session),
    current_user: Usuario = Depends(get_current_admin)
):
    """Edita um prêmio existente"""
    premio = await session.get(Premio, premio_id)
    if not premio:
        raise HTTPException(status_code=404, detail="Prêmio não encontrado.")

    if foto_base64 and foto_base64.startswith("data:image"):
        try:
            _, encoded = foto_base64.split(",", 1)
            foto_bytes = base64.b64decode(encoded)
            nome_arquivo = f"premio_{premio.id}_{int(datetime.now().timestamp())}.jpg"
            caminho = os.path.join(PREMIOS_DIR, nome_arquivo)
            with open(caminho, "wb") as f:
                f.write(foto_bytes)
            premio.foto_url = f"/static/uploads/premios/{nome_arquivo}"
        except Exception as e:
            print("Erro atualizando foto do premio:", e)

    eixo_id_val = int(eixo_id) if eixo_id and eixo_id.strip() and eixo_id != "0" else None
    cat_enum = PremioCategoria.categoria_2 if categoria in ["categoria_2", PremioCategoria.categoria_2] else PremioCategoria.categoria_1

    premio.nome = nome.strip()
    premio.descricao = descricao.strip() if descricao else None
    premio.categoria = cat_enum
    premio.eixo_id = eixo_id_val
    premio.quantidade = quantidade
    if ativo is not None:
        premio.ativo = ativo

    session.add(premio)
    await session.commit()

    return JSONResponse(content={"sucesso": True})


@router.delete("/api/sorteios/premios/{premio_id}")
async def excluir_premio(
    premio_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: Usuario = Depends(get_current_admin)
):
    """Exclui um prêmio caso ainda não tenha sido sorteado"""
    premio = await session.get(Premio, premio_id)
    if not premio:
        raise HTTPException(status_code=404, detail="Prêmio não encontrado.")

    if premio.quantidade_sorteada > 0:
        raise HTTPException(status_code=400, detail="Não é possível excluir um prêmio que já possui ganhadores.")

    await session.delete(premio)
    await session.commit()

    return JSONResponse(content={"sucesso": True})


@router.get("/api/sorteios/eixos")
async def listar_eixos(session: AsyncSession = Depends(get_session)):
    """Lista todos os eixos e as secretarias vinculadas"""
    stmt_eixos = select(Eixo).options(selectinload(Eixo.secretarias)).order_by(Eixo.nome)
    res_eixos = await session.execute(stmt_eixos)
    eixos = res_eixos.scalars().all()

    stmt_sec = select(Secretaria).order_by(Secretaria.nome)
    res_sec = await session.execute(stmt_sec)
    todas_secretarias = res_sec.scalars().all()

    eixos_data = [
        {
            "id": e.id,
            "nome": e.nome,
            "descricao": e.descricao,
            "secretarias": [{"id": s.id, "nome": s.nome, "sigla": s.sigla} for s in e.secretarias],
            "secretarias_count": len(e.secretarias)
        }
        for e in eixos
    ]

    return JSONResponse(content={
        "eixos": eixos_data,
        "todas_secretarias": [{"id": s.id, "nome": s.nome, "sigla": s.sigla, "eixo_id": s.eixo_id} for s in todas_secretarias]
    })


@router.post("/api/sorteios/eixos")
async def salvar_eixo(
    nome: str = Form(...),
    descricao: Optional[str] = Form(None),
    secretaria_ids: Optional[str] = Form(None), # Lista separada por vírgula "1,2,3"
    eixo_id: Optional[int] = Form(None),
    session: AsyncSession = Depends(get_session),
    current_user: Usuario = Depends(get_current_admin)
):
    """Cria ou edita um Eixo e associa secretarias"""
    if eixo_id:
        eixo = await session.get(Eixo, eixo_id)
        if not eixo:
            raise HTTPException(status_code=404, detail="Eixo não encontrado.")
        eixo.nome = nome.strip()
        eixo.descricao = descricao.strip() if descricao else None
        session.add(eixo)
    else:
        eixo = Eixo(nome=nome.strip(), descricao=descricao.strip() if descricao else None)
        session.add(eixo)
        await session.flush()

    # Atualiza as secretarias associadas
    ids_selecionados = []
    if secretaria_ids and secretaria_ids.strip():
        ids_selecionados = [int(i.strip()) for i in secretaria_ids.split(",") if i.strip().isdigit()]

    # 1. Desvincula secretarias anteriores deste eixo
    stmt_desvincular = select(Secretaria).where(Secretaria.eixo_id == eixo.id)
    res_desv = await session.execute(stmt_desvincular)
    for s in res_desv.scalars().all():
        if s.id not in ids_selecionados:
            s.eixo_id = None
            session.add(s)

    # 2. Vincula as novas secretarias
    if ids_selecionados:
        stmt_vincular = select(Secretaria).where(Secretaria.id.in_(ids_selecionados))
        res_vinc = await session.execute(stmt_vincular)
        for s in res_vinc.scalars().all():
            s.eixo_id = eixo.id
            session.add(s)

    await session.commit()
    return JSONResponse(content={"sucesso": True, "id": eixo.id})


@router.delete("/api/sorteios/eixos/{eixo_id}")
async def excluir_eixo(
    eixo_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: Usuario = Depends(get_current_admin)
):
    """Exclui um eixo e desvincula as secretarias"""
    eixo = await session.get(Eixo, eixo_id)
    if not eixo:
        raise HTTPException(status_code=404, detail="Eixo não encontrado.")

    # Desvincula secretarias
    stmt_sec = select(Secretaria).where(Secretaria.eixo_id == eixo_id)
    res_sec = await session.execute(stmt_sec)
    for s in res_sec.scalars().all():
        s.eixo_id = None
        session.add(s)

    await session.delete(eixo)
    await session.commit()

    return JSONResponse(content={"sucesso": True})


@router.get("/api/sorteios/entregas-pendentes")
async def listar_entregas_pendentes(
    session: AsyncSession = Depends(get_session),
    current_user: Usuario = Depends(get_current_entregador)
):
    """Lista sorteios realizados pendentes ou com entrega já realizada"""
    stmt = (
        select(Ganhador)
        .where(Ganhador.anulado == False)
        .options(
            selectinload(Ganhador.usuario).selectinload(Usuario.secretaria),
            selectinload(Ganhador.premio),
            selectinload(Ganhador.responsavel_entrega)
        )
        .order_by(Ganhador.entregue.asc(), desc(Ganhador.data_sorteio))
    )
    res = await session.execute(stmt)
    ganhadores = res.scalars().all()

    lista = []
    for g in ganhadores:
        u = g.usuario
        p = g.premio
        resp = g.responsavel_entrega
        lista.append({
            "id": g.id,
            "servidor_nome": u.nome if u else "Servidor",
            "servidor_cpf": f"{u.cpf[:3]}.{u.cpf[3:6]}.{u.cpf[6:9]}-{u.cpf[9:]}" if u and len(u.cpf) == 11 else (u.cpf if u else ""),
            "servidor_foto": u.foto_rosto_url or u.foto_url if u else None,
            "secretaria_nome": u.secretaria.nome if u and u.secretaria else "Geral",
            "setor": u.setor if u else "",
            "telefone": u.telefone if u else "",
            "premio_nome": p.nome if p else "Prêmio",
            "premio_foto": p.foto_url if p else None,
            "categoria": g.categoria.value if hasattr(g.categoria, "value") else str(g.categoria),
            "data_sorteio": g.data_sorteio.strftime("%d/%m/%Y às %H:%M"),
            "entregue": g.entregue,
            "data_entrega": g.data_entrega.strftime("%d/%m/%Y às %H:%M") if g.data_entrega else None,
            "foto_entrega_url": g.foto_entrega_url,
            "responsavel_entrega": resp.nome if resp else None
        })

    return JSONResponse(content={"entregas": lista})


@router.post("/api/sorteios/registrar-entrega/{ganhador_id}")
async def registrar_entrega(
    ganhador_id: int,
    foto_base64: str = Form(...),
    session: AsyncSession = Depends(get_session),
    current_user: Usuario = Depends(get_current_entregador)
):
    """Registra a entrega do prêmio com foto de comprovação do ganhador segurando o prêmio"""
    ganhador = await session.get(Ganhador, ganhador_id)
    if not ganhador:
        raise HTTPException(status_code=404, detail="Registro de sorteio não encontrado.")

    if ganhador.anulado:
        raise HTTPException(status_code=400, detail="Este sorteio foi anulado.")

    if not foto_base64 or not foto_base64.startswith("data:image"):
        raise HTTPException(status_code=400, detail="A foto de comprovação segurando o prêmio é obrigatória.")

    try:
        _, encoded = foto_base64.split(",", 1)
        foto_bytes = base64.b64decode(encoded)
        nome_arquivo = f"entrega_ganhador_{ganhador.id}_{int(datetime.now().timestamp())}.jpg"
        caminho = os.path.join(ENTREGAS_DIR, nome_arquivo)
        with open(caminho, "wb") as f:
            f.write(foto_bytes)
        foto_url = f"/static/uploads/entregas/{nome_arquivo}"
    except Exception as e:
        raise HTTPException(status_code=400, detail="Erro ao processar e salvar a foto de comprovação.")

    ganhador.entregue = True
    ganhador.data_entrega = datetime.now()
    ganhador.foto_entrega_url = foto_url
    ganhador.responsavel_entrega_id = current_user.id

    session.add(ganhador)
    await session.commit()

    return JSONResponse(content={"sucesso": True, "foto_entrega_url": foto_url})


@router.get("/api/sorteios/meus-premios")
async def consultar_meus_premios(
    cpf: str = Query(...),
    data_nascimento: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_session)
):
    """Permite ao servidor consultar os prêmios que ganhou mediante validação de CPF e Data de Nascimento"""
    cpf_limpo = "".join([c for c in cpf if c.isdigit()]).zfill(11)
    
    stmt_user = select(Usuario).where(Usuario.cpf == cpf_limpo, Usuario.deleted_at.is_(None), Usuario.ativo == True)
    res_user = await session.execute(stmt_user)
    usuario = res_user.scalars().first()

    if not usuario:
        return JSONResponse(content={"encontrado": False, "mensagem": "Servidor não localizado.", "premios": []})

    # Validação de Data de Nascimento (se informada ou se cadastrada no banco)
    if data_nascimento and usuario.data_nascimento:
        d_input_clean = "".join([c for c in data_nascimento if c.isdigit()])
        d_user_clean = "".join([c for c in usuario.data_nascimento if c.isdigit()])
        
        match_data = (d_input_clean == d_user_clean)
        if not match_data and len(d_input_clean) == 8 and len(d_user_clean) == 8:
            invert_input = f"{d_input_clean[4:]}{d_input_clean[2:4]}{d_input_clean[:2]}"
            invert_user = f"{d_user_clean[4:]}{d_user_clean[2:4]}{d_user_clean[:2]}"
            match_data = (d_input_clean == invert_user or invert_input == d_user_clean)
        
        if not match_data:
            return JSONResponse(content={
                "encontrado": False,
                "mensagem": "Data de Nascimento não confere com o CPF informado.",
                "premios": []
            })

    stmt_ganhados = (
        select(Ganhador)
        .where(
            Ganhador.usuario_id == usuario.id,
            Ganhador.anulado == False
        )
        .options(selectinload(Ganhador.premio))
        .order_by(desc(Ganhador.data_sorteio))
    )
    res_ganhados = await session.execute(stmt_ganhados)
    ganhados = res_ganhados.scalars().all()

    premios_data = []
    for g in ganhados:
        p = g.premio
        premios_data.append({
            "id": g.id,
            "premio_nome": p.nome if p else "Prêmio Oficial",
            "premio_descricao": p.descricao if p else "",
            "premio_foto": p.foto_url if p else None,
            "categoria": "Categoria 1 (Geral)" if str(g.categoria) == "categoria_1" else "Categoria 2 (Eixo)",
            "data_sorteio": g.data_sorteio.strftime("%d/%m/%Y às %H:%M"),
            "entregue": g.entregue,
            "data_entrega": g.data_entrega.strftime("%d/%m/%Y às %H:%M") if g.data_entrega else None,
            "foto_entrega_url": g.foto_entrega_url
        })

    # Mascara nome do servidor para segurança (LGPD)
    partes_nome = usuario.nome.split()
    if len(partes_nome) > 1:
        nome_mascarado = f"{partes_nome[0]} {partes_nome[-1][0]}***"
    else:
        nome_mascarado = f"{usuario.nome[:3]}***"

    return JSONResponse(content={
        "encontrado": True,
        "servidor_nome": nome_mascarado,
        "premios": premios_data
    })

# =========================================================================
# GESTÃO DE SECRETARIAS (CRUD ADMIN + ROTA PÚBLICA DE RESGATE)
# =========================================================================

@router.get("/api/secretarias")
async def listar_secretarias_publicas(session: AsyncSession = Depends(get_session)):
    """Retorna todas as secretarias oficiais para formulários de resgate e cadastros"""
    stmt = select(Secretaria).options(selectinload(Secretaria.eixo)).order_by(Secretaria.nome)
    res = await session.execute(stmt)
    secretarias = res.scalars().all()
    return JSONResponse(content=[
        {
            "id": s.id,
            "nome": s.nome,
            "sigla": s.sigla,
            "eixo_id": s.eixo_id,
            "eixo_nome": s.eixo.nome if s.eixo else None
        }
        for s in secretarias
    ])


@router.get("/api/sorteios/secretarias")
async def listar_secretarias_admin(
    session: AsyncSession = Depends(get_session),
    current_user: Usuario = Depends(get_current_admin)
):
    """Retorna todas as secretarias com detalhes para o painel administrativo"""
    stmt = select(Secretaria).options(
        selectinload(Secretaria.eixo),
        selectinload(Secretaria.usuarios)
    ).order_by(Secretaria.nome)
    res = await session.execute(stmt)
    secretarias = res.scalars().all()

    stmt_eixos = select(Eixo).order_by(Eixo.nome)
    res_eixos = await session.execute(stmt_eixos)
    eixos = res_eixos.scalars().all()

    return JSONResponse(content={
        "secretarias": [
            {
                "id": s.id,
                "nome": s.nome,
                "sigla": s.sigla,
                "eixo_id": s.eixo_id,
                "eixo_nome": s.eixo.nome if s.eixo else None,
                "total_servidores": len(s.usuarios) if s.usuarios else 0
            }
            for s in secretarias
        ],
        "eixos": [
            {"id": e.id, "nome": e.nome, "descricao": e.descricao}
            for e in eixos
        ]
    })


@router.post("/api/sorteios/secretarias")
async def salvar_secretaria_admin(
    nome: str = Form(...),
    sigla: Optional[str] = Form(None),
    eixo_id: Optional[int] = Form(None),
    secretaria_id: Optional[int] = Form(None),
    session: AsyncSession = Depends(get_session),
    current_user: Usuario = Depends(get_current_admin)
):
    """Cria ou edita uma Secretaria e seu vínculo de Eixo"""
    if not nome or not nome.strip():
        raise HTTPException(status_code=400, detail="O nome da secretaria é obrigatório.")

    if secretaria_id:
        sec = await session.get(Secretaria, secretaria_id)
        if not sec:
            raise HTTPException(status_code=404, detail="Secretaria não encontrada.")
        sec.nome = nome.strip()
        sec.sigla = sigla.strip().upper() if sigla and sigla.strip() else None
        sec.eixo_id = eixo_id if eixo_id and eixo_id > 0 else None
        session.add(sec)
    else:
        sec = Secretaria(
            nome=nome.strip(),
            sigla=sigla.strip().upper() if sigla and sigla.strip() else None,
            eixo_id=eixo_id if eixo_id and eixo_id > 0 else None
        )
        session.add(sec)

    await session.commit()
    await session.refresh(sec)
    return JSONResponse(content={"sucesso": True, "id": sec.id})


@router.delete("/api/sorteios/secretarias/{sec_id}")
async def excluir_secretaria_admin(
    sec_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: Usuario = Depends(get_current_admin)
):
    """Exclui uma secretaria desvinculando servidores ou impedindo caso haja vínculos"""
    sec = await session.get(Secretaria, sec_id)
    if not sec:
        raise HTTPException(status_code=404, detail="Secretaria não encontrada.")

    # Desvincula servidores para não quebrar chaves estrangeiras
    stmt_users = select(Usuario).where(Usuario.secretaria_id == sec_id)
    res_users = await session.execute(stmt_users)
    for u in res_users.scalars().all():
        u.secretaria_id = None
        session.add(u)

    await session.delete(sec)
    await session.commit()
    return JSONResponse(content={"sucesso": True})
