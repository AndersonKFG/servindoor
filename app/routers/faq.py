import logging
from typing import Optional, List
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.db.session import get_session
from app.models.all_models import FaqItem, Usuario
from app.core.deps import get_current_admin_geral

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/faq", tags=["Perguntas Frequentes - FAQ"])

INITIAL_FAQS = [
    {
        "pergunta": "Como funciona o resgate dos ingressos?",
        "resposta": "Após o lote abrir, cada servidor poderá resgatar 1 ingresso por CPF, inserindo as informações no formulário e tirando sua foto ao vivo.",
        "ordem": 1
    },
    {
        "pergunta": "Preciso mesmo tirar a foto?",
        "resposta": "Sim, a foto é essencial para que a equipe da Servindoor possa identificar o servidor caso necessário.",
        "ordem": 2
    },
    {
        "pergunta": "Quando eu vou resgatar fica aparecendo “Continuar resgate”, o que é isso?",
        "resposta": "O sistema foi desenvolvido para 1 aparelho poder resgatar 1 ingresso por vez, isso evita que uma só pessoa consiga segurar mais de 1 vaga.",
        "ordem": 3
    },
    {
        "pergunta": "Então quer dizer que eu só consigo resgatar 1 ingresso por aparelho?",
        "resposta": "Não! Você pode resgatar vários ingressos em um só aparelho, mas apenas 1 ingresso por vez.",
        "ordem": 4
    },
    {
        "pergunta": "Quando eu recebo meu ingresso?",
        "resposta": "Você receberá seu ingresso em até 72 horas após o resgate, isso dá tempo da equipe validar quem realmente é servidor.",
        "ordem": 5
    },
    {
        "pergunta": "Como eu sei se meu resgate deu certo?",
        "resposta": "Você receberá no seu e-mail a confirmação do resgate, caso esteja tudo certo, você receberá o ingresso no seu e-mail posteriormente!",
        "ordem": 6
    },
    {
        "pergunta": "Como eu sei se meu ingresso foi emitido mesmo?",
        "resposta": "Você pode a qualquer momento acessar servindoor.com.br/meu-ingresso e consultar a situação dele.",
        "ordem": 7
    },
    {
        "pergunta": "Quero cancelar meu ingresso, como faço?",
        "resposta": "Para cancelar o ingresso, você deve acessar a tela de consultar o ingresso, e após acessar o seu ingresso, você terá a opção de cancelar ele.",
        "ordem": 8
    }
]

async def seed_faqs_if_empty(session: AsyncSession):
    """Inicializa as 8 perguntas e respostas padrão caso a tabela esteja vazia"""
    try:
        stmt = select(FaqItem)
        res = await session.execute(stmt)
        existentes = res.scalars().all()
        if not existentes:
            for item in INITIAL_FAQS:
                novo = FaqItem(
                    pergunta=item["pergunta"],
                    resposta=item["resposta"],
                    ordem=item["ordem"],
                    ativo=True
                )
                session.add(novo)
            await session.commit()
            logger.info("FAQs padrão semeadas com sucesso no banco de dados.")
    except Exception as e:
        logger.error(f"Erro ao semear FAQs: {e}")


class FaqCreateSchema(BaseModel):
    pergunta: str
    resposta: str
    ordem: Optional[int] = 0
    ativo: Optional[bool] = True


class FaqUpdateSchema(BaseModel):
    pergunta: Optional[str] = None
    resposta: Optional[str] = None
    ordem: Optional[int] = None
    ativo: Optional[bool] = None


@router.get("")
async def listar_faqs(
    request: Request,
    session: AsyncSession = Depends(get_session)
):
    """Retorna a lista de perguntas e respostas da FAQ"""
    await seed_faqs_if_empty(session)

    # Verifica se há administrador geral autenticado na requisição para exibir itens inativos
    is_admin = False
    token = request.cookies.get("access_token")
    if token:
        try:
            from jose import jwt
            from app.core.config import settings
            scheme, _, param = token.partition(" ")
            payload = jwt.decode(param, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            cpf = payload.get("sub")
            if cpf:
                stmt_u = select(Usuario).where(Usuario.cpf == cpf, Usuario.deleted_at.is_(None), Usuario.ativo == True)
                res_u = await session.execute(stmt_u)
                user = res_u.scalars().first()
                if user and user.has_role("admin_geral"):
                    is_admin = True
        except Exception:
            is_admin = False

    query = select(FaqItem)
    if not is_admin:
        query = query.where(FaqItem.ativo == True)
    
    query = query.order_by(FaqItem.ordem.asc(), FaqItem.id.asc())
    res = await session.execute(query)
    faqs = res.scalars().all()

    return {
        "sucesso": True,
        "is_admin_geral": is_admin,
        "total": len(faqs),
        "itens": [
            {
                "id": f.id,
                "pergunta": f.pergunta,
                "resposta": f.resposta,
                "ordem": f.ordem,
                "ativo": f.ativo,
                "created_at": f.created_at.isoformat() if f.created_at else None,
                "updated_at": f.updated_at.isoformat() if f.updated_at else None
            }
            for f in faqs
        ]
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def criar_faq(
    dados: FaqCreateSchema,
    session: AsyncSession = Depends(get_session),
    admin: Usuario = Depends(get_current_admin_geral)
):
    """Permite ao Administrador Geral adicionar uma nova pergunta e resposta à FAQ"""
    pergunta_clean = (dados.pergunta or "").strip()
    resposta_clean = (dados.resposta or "").strip()

    if not pergunta_clean:
        raise HTTPException(status_code=400, detail="A pergunta não pode estar vazia.")
    if not resposta_clean:
        raise HTTPException(status_code=400, detail="A resposta não pode estar vazia.")

    novo_item = FaqItem(
        pergunta=pergunta_clean,
        resposta=resposta_clean,
        ordem=dados.ordem or 0,
        ativo=True if dados.ativo is None else dados.ativo,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    session.add(novo_item)
    await session.commit()
    await session.refresh(novo_item)

    return {
        "sucesso": True,
        "mensagem": "Pergunta frequente criada com sucesso.",
        "item": {
            "id": novo_item.id,
            "pergunta": novo_item.pergunta,
            "resposta": novo_item.resposta,
            "ordem": novo_item.ordem,
            "ativo": novo_item.ativo
        }
    }


@router.put("/{faq_id}")
async def atualizar_faq(
    faq_id: int,
    dados: FaqUpdateSchema,
    session: AsyncSession = Depends(get_session),
    admin: Usuario = Depends(get_current_admin_geral)
):
    """Permite ao Administrador Geral editar uma pergunta e resposta existente"""
    stmt = select(FaqItem).where(FaqItem.id == faq_id)
    res = await session.execute(stmt)
    item = res.scalars().first()

    if not item:
        raise HTTPException(status_code=404, detail="Pergunta frequente não encontrada.")

    if dados.pergunta is not None:
        p_clean = dados.pergunta.strip()
        if not p_clean:
            raise HTTPException(status_code=400, detail="A pergunta não pode ficar vazia.")
        item.pergunta = p_clean

    if dados.resposta is not None:
        r_clean = dados.resposta.strip()
        if not r_clean:
            raise HTTPException(status_code=400, detail="A resposta não pode ficar vazia.")
        item.resposta = r_clean

    if dados.ordem is not None:
        item.ordem = dados.ordem

    if dados.ativo is not None:
        item.ativo = dados.ativo

    item.updated_at = datetime.now(timezone.utc)
    session.add(item)
    await session.commit()
    await session.refresh(item)

    return {
        "sucesso": True,
        "mensagem": "Pergunta frequente atualizada com sucesso.",
        "item": {
            "id": item.id,
            "pergunta": item.pergunta,
            "resposta": item.resposta,
            "ordem": item.ordem,
            "ativo": item.ativo
        }
    }


@router.delete("/{faq_id}")
async def excluir_faq(
    faq_id: int,
    session: AsyncSession = Depends(get_session),
    admin: Usuario = Depends(get_current_admin_geral)
):
    """Permite ao Administrador Geral excluir uma pergunta e resposta da FAQ"""
    stmt = select(FaqItem).where(FaqItem.id == faq_id)
    res = await session.execute(stmt)
    item = res.scalars().first()

    if not item:
        raise HTTPException(status_code=404, detail="Pergunta frequente não encontrada.")

    await session.delete(item)
    await session.commit()

    return {
        "sucesso": True,
        "mensagem": "Pergunta frequente excluída com sucesso."
    }
