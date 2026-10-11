import json
import logging
from typing import Dict, Any
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import asyncio

from app.core.config import settings
from app.core.cpf import limpar_cpf

logger = logging.getLogger(__name__)


class ServidorValidationService:
    """
    Serviço desacoplado para consulta e validação de servidores municipais.
    Comunica-se com a API oficial da Escola de Governo de Caruaru.
    """

    @classmethod
    async def verificar_servidor(cls, cpf: str) -> Dict[str, Any]:
        cpf_limpo = limpar_cpf(cpf)
        if not cpf_limpo or len(cpf_limpo) != 11:
            return {"is_servidor": False, "motivo": "CPF inválido", "modo": "local"}

        # 1. Modo Mock (apenas se ativado e nenhuma chave de API estiver configurada)
        if settings.VALIDACAO_EXTERNA_MOCK and not (settings.API_KEY_EGPC or "").strip():
            return cls._simular_resposta_mock(cpf_limpo)

        # 2. Consulta à API Oficial da Escola de Governo de Caruaru
        return await cls._consultar_api_oficial(cpf_limpo)

    @classmethod
    def _simular_resposta_mock(cls, cpf_limpo: str) -> Dict[str, Any]:
        negativos = [
            limpar_cpf(c) for c in (settings.VALIDACAO_EXTERNA_MOCK_NEGATIVOS or "").split(",") if c.strip()
        ]
        if cpf_limpo in negativos or cpf_limpo.endswith(("7", "8", "9")):
            return {
                "is_servidor": False,
                "motivo": "CPF não localizado na base preliminar de servidores.",
                "modo": "mock"
            }

        return {
            "is_servidor": True,
            "motivo": "Servidor identificado com sucesso na base municipal.",
            "modo": "mock"
        }

    @classmethod
    async def _consultar_api_oficial(cls, cpf_limpo: str) -> Dict[str, Any]:
        url = (settings.ESCOLA_GOVERNO_API_URL or "").strip() or "https://escoladegoverno.caruaru.pe.gov.br/api/v1/servidor/verificar"
        api_key = (settings.API_KEY_EGPC or "").strip()

        payload = json.dumps({"cpf": cpf_limpo}).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": api_key,
            "Origin": "https://servindoor.com.br",
            "Accept": "application/json",
            "User-Agent": "Servindoor/1.0"
        }

        def _do_request():
            req = Request(url, data=payload, headers=headers, method="POST")
            try:
                with urlopen(req, timeout=8) as response:
                    status_code = response.getcode()
                    body = response.read().decode("utf-8")
                    if status_code in (200, 201):
                        data = json.loads(body)
                        # API retorna {"sucesso": true, "is_servidor": true} ou {"is_servidor": true}
                        is_serv = bool(data.get("is_servidor", False))
                        if not is_serv and isinstance(data.get("dados"), dict):
                            is_serv = bool(data["dados"].get("is_servidor", False))
                        return {
                            "is_servidor": is_serv,
                            "dados": data,
                            "modo": "api_oficial"
                        }
            except (HTTPError, URLError, TimeoutError) as e:
                logger.warning(f"Aviso na comunicação com API da Escola de Governo ({url}): {e}")
            except Exception as e:
                logger.error(f"Erro inesperado na validação de servidor: {e}")

            return {
                "is_servidor": False,
                "motivo": "API externa indisponível ou resposta não confirmada. Encaminhado para validação da equipe.",
                "modo": "fallback"
            }

        return await asyncio.to_thread(_do_request)