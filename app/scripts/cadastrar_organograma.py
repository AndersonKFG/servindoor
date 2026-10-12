"""Cadastra os órgãos e eixos do organograma fornecido, sem apagar dados.

Na VPS, após git pull:
    docker compose exec -T web python < app/scripts/cadastrar_organograma.py

Pode ser executado novamente: reaproveita órgãos por nome ou sigla e eixos
por nome, mantendo os IDs e os vínculos existentes.
"""

import asyncio
import re
import unicodedata

from sqlalchemy import text
from sqlmodel import select

from app.db.session import async_session
from app.models.all_models import Eixo, Secretaria


EIXOS = {
    1: "Inovação Social",
    2: "Desenvolvimento Econômico",
    3: "Gestão do Território e da Cidade",
    4: "Cultura e Turismo",
    5: "Gestão e Tecnologia",
}

# Nome oficial, sigla (quando consta no organograma), número do eixo.
# GP e GVP seguem as siglas já cadastradas pelo usuário.
# Consultorias foi excluída conforme solicitado.
ORGAOS = (
    ("Gabinete do Prefeito", "GP", None),
    ("Gabinete da Vice-Prefeita", "GVP", None),
    ("Secretaria de Governo e Relações Institucionais", "SEGOV", None),
    ("Secretaria de Articulação Política", "SAP", None),
    ("Assessorias", None, None),
    ("Secretaria de Comunicação", "SECOM", None),
    ("Secretaria de Projetos Estratégicos", "SEPE", None),
    ("Secretaria de Educação e Esportes", "SEDUC", 1),
    ("Secretaria de Saúde", "SMS", 1),
    ("Secretaria de Assistência Social e Combate à Fome", "SAS", 1),
    ("Secretaria da Mulher", "SEMU", 1),
    (
        "Secretaria de Desenvolvimento Econômico, Turismo, Tecnologia e Economia Criativa",
        "SEDETEC",
        2,
    ),
    ("Secretaria de Desenvolvimento Rural", "SDR", 2),
    ("Central de Abastecimento de Caruaru", "CEACA", 2),
    ("Secretaria de Segurança Municipal de Caruaru", "SM", 3),
    ("Secretaria de Serviços Públicos", "SESP", 3),
    ("Secretaria de Infraestrutura Urbana e Obras", "SIURB", 3),
    ("Autarquia de Urbanização e Meio Ambiente de Caruaru", "URB", 3),
    ("Autarquia de Mobilidade de Caruaru", "AMC", 3),
    ("Secretaria de Sustentabilidade e Bem-Estar Animal", "SSB", 3),
    ("Fundação de Cultura de Caruaru", "FCC", 4),
    ("Secretaria de Planejamento, Orçamento e Gestão", "SEPLAG", 5),
    ("Secretaria de Captação de Recursos", "SECAP", 5),
    ("Secretaria da Fazenda", "SEFAZ", 5),
    ("Controladoria-Geral do Município", "CGM", 5),
    ("Procuradoria-Geral do Município", "PGM", 5),
    ("Secretaria de Administração", "SAD", 5),
    (
        "Instituto de Previdência dos Servidores Municipais de Caruaru",
        "CARUARUPREV",
        5,
    ),
)


def normalizar(valor: str | None) -> str:
    texto = unicodedata.normalize("NFKD", valor or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", texto.casefold()).split())


def nome_eixo(valor: str) -> str:
    # Aceita tanto "Inovação Social" como "Eixo 01 - Inovação Social".
    return re.sub(r"^eixo\s*\d+\s*", "", normalizar(valor))


async def cadastrar() -> None:
    mensagens = []
    eixos_criados = orgaos_criados = orgaos_vinculados = 0
    async with async_session() as session:
        async with session.begin():
            # Evita duplicatas se duas execuções do script ocorrerem juntas.
            await session.execute(text("SELECT pg_advisory_xact_lock(7429185)"))
            eixos = list((await session.execute(select(Eixo))).scalars().all())
            orgaos = list((await session.execute(select(Secretaria))).scalars().all())
            ids_eixos = {}

            for numero, titulo in EIXOS.items():
                candidatos = [e for e in eixos if nome_eixo(e.nome) == normalizar(titulo)]
                if len(candidatos) > 1:
                    raise ValueError(f"Há eixos duplicados para {titulo}. Nenhum dado foi salvo.")
                if candidatos:
                    eixo = candidatos[0]
                else:
                    eixo = Eixo(nome=f"Eixo {numero:02d} - {titulo}", descricao=titulo)
                    session.add(eixo)
                    await session.flush()
                    eixos.append(eixo)
                    eixos_criados += 1
                ids_eixos[numero] = eixo.id

            for nome, sigla, numero in ORGAOS:
                candidatos = [
                    orgao for orgao in orgaos
                    if normalizar(orgao.nome) == normalizar(nome)
                    or (sigla and normalizar(orgao.sigla) == normalizar(sigla))
                ]
                if len(candidatos) > 1:
                    raise ValueError(f"Há órgãos duplicados para {nome}. Nenhum dado foi salvo.")
                eixo_id = ids_eixos.get(numero)
                if candidatos:
                    orgao = candidatos[0]
                    if orgao.eixo_id is None and eixo_id is not None:
                        orgao.eixo_id = eixo_id
                        orgaos_vinculados += 1
                    elif eixo_id is not None and orgao.eixo_id != eixo_id:
                        mensagens.append(
                            f"ATENÇÃO: {orgao.nome} já possui outro eixo; vínculo preservado."
                        )
                    if not orgao.sigla and sigla:
                        orgao.sigla = sigla
                    mensagens.append(f"Reaproveitado: {orgao.nome}")
                else:
                    orgao = Secretaria(nome=nome, sigla=sigla, eixo_id=eixo_id)
                    session.add(orgao)
                    orgaos.append(orgao)
                    orgaos_criados += 1
                    mensagens.append(f"Criado: {nome}")

    # Informa sucesso somente depois de confirmar a transação inteira.
    for mensagem in mensagens:
        print(mensagem)
    print(
        f"Concluído: {eixos_criados} eixos criados, {orgaos_criados} órgãos criados, "
        f"{len(ORGAOS) - orgaos_criados} órgãos reaproveitados e "
        f"{orgaos_vinculados} órgãos existentes vinculados aos eixos."
    )


if __name__ == "__main__":
    try:
        asyncio.run(cadastrar())
    except ValueError as erro:
        raise SystemExit(str(erro)) from erro
