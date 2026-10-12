import base64
import binascii
import io
import os
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.deps import get_current_admin_geral
from app.db.session import get_session
from app.models.all_models import SponsorLogo, Usuario

router = APIRouter(prefix="/api/sponsor-logos", tags=["Logos de patrocinadores"])
LOGOS_DIR = "app/static/uploads/logos"
MAX_IMAGE_BYTES = 1_500_000
os.makedirs(LOGOS_DIR, exist_ok=True)


class SponsorLogoCreate(BaseModel):
    imagem: str = Field(max_length=2_000_000)


def _logo_payload(logo: SponsorLogo) -> dict:
    return {
        "id": logo.id,
        "url": f"/static/uploads/logos/{logo.filename}",
        "ordem": logo.ordem,
    }


@router.get("")
async def listar_logos(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(SponsorLogo).order_by(SponsorLogo.ordem, SponsorLogo.id))
    return {"itens": [_logo_payload(logo) for logo in result.scalars().all()]}


@router.post("", status_code=201)
async def criar_logo(
    dados: SponsorLogoCreate,
    session: AsyncSession = Depends(get_session),
    admin: Usuario = Depends(get_current_admin_geral),
):
    del admin
    prefix = "data:image/png;base64,"
    if not dados.imagem.startswith(prefix):
        raise HTTPException(status_code=400, detail="Envie a logo recortada no formato PNG.")

    encoded = dados.imagem[len(prefix):]
    if len(encoded) > MAX_IMAGE_BYTES * 4 // 3 + 8:
        raise HTTPException(status_code=413, detail="A logo excede o limite de tamanho.")
    try:
        image_bytes = base64.b64decode(encoded, validate=True)
        with Image.open(io.BytesIO(image_bytes)) as image:
            if image.format != "PNG" or image.width < 1 or image.height < 1 or image.width > 2400 or image.height > 1600:
                raise HTTPException(status_code=400, detail="A imagem recortada não é um PNG válido.")
            image.verify()
    except (binascii.Error, UnidentifiedImageError, OSError, ValueError):
        raise HTTPException(status_code=400, detail="Não foi possível validar a imagem enviada.")

    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="A logo excede o limite de tamanho.")

    result = await session.execute(select(SponsorLogo).order_by(SponsorLogo.ordem.desc()))
    logos = result.scalars().all()
    filename = f"sponsor_{secrets.token_hex(16)}.png"
    path = os.path.join(LOGOS_DIR, filename)
    with open(path, "wb") as image_file:
        image_file.write(image_bytes)

    logo = SponsorLogo(filename=filename, ordem=(logos[0].ordem + 1 if logos else 0), created_at=datetime.now(timezone.utc))
    session.add(logo)
    try:
        await session.commit()
        await session.refresh(logo)
    except Exception:
        await session.rollback()
        if os.path.exists(path):
            os.remove(path)
        raise
    return {"item": _logo_payload(logo)}


@router.delete("/{logo_id}")
async def excluir_logo(
    logo_id: int,
    session: AsyncSession = Depends(get_session),
    admin: Usuario = Depends(get_current_admin_geral),
):
    del admin
    logo = await session.get(SponsorLogo, logo_id)
    if not logo:
        raise HTTPException(status_code=404, detail="Logo não encontrada.")
    filename = logo.filename
    await session.delete(logo)
    await session.commit()
    path = os.path.join(LOGOS_DIR, filename)
    if os.path.isfile(path):
        os.remove(path)
    return {"sucesso": True}
