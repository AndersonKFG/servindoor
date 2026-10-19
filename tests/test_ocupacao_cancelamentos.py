"""Rotas e reservas reais com SQLite isolado; sem banco externo ou SMTP."""

import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel, select, func

from app.core import security
from app.models.all_models import Ingresso, Lote, SolicitacaoCancelamento, Usuario, UserRole, ReservaIngresso
from app.routers import admin, cancelamento, public
from app.services import email_service
from app.services.reserva_batch import ReservaBatchService


class TestOcupacaoCancelamentos(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.senha_hash = security.get_password_hash("senha-de-teste")

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        self.sessions = sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        self.session = self.sessions()
        self.admin = Usuario(id=1, cpf="11144477735", nome="Admin", role=UserRole.admin_geral,
                             senha_hash=self.senha_hash)
        self.usuario = Usuario(id=2, cpf="52998224725", nome="Participante")
        self.session.add_all([
            self.admin, self.usuario,
            Lote(id=1, nome="Lote cheio", quantidade_total=1500, quantidade_resgatada=1500),
            Ingresso(id=1, usuario_id=2, lote_id=1, qr_code_token="qr-teste"),
            SolicitacaoCancelamento(id=1, usuario_id=2, ingresso_id=1, token="cancelamento-teste",
                codigo_verificacao="123456", codigo_expira_em=datetime.now(timezone.utc) + timedelta(minutes=5),
                status="pendente_analise"),
        ])
        await self.session.commit()

    async def asyncTearDown(self):
        await self.session.close()
        await self.engine.dispose()

    async def extraviar(self, senha="senha-de-teste"):
        async def receive():
            return {"type": "http.request", "body": json.dumps({"motivo": "Extravio", "senha_admin": senha}).encode()}
        request = Request({"type": "http", "method": "POST", "path": "/api/admin/ingressos/1/cancelar",
                           "headers": [(b"content-type", b"application/json")]}, receive)
        return await admin.cancelar_ingresso(1, request, self.session, self.admin)

    async def aprovar(self):
        return await cancelamento.aprovar_cancelamento(1, self.session, self.admin)

    async def verificar_lote_cheio(self):
        # Usa sessão nova para comprovar persistência, em vez do objeto em memória.
        async with self.sessions() as session:
            ingresso = await session.get(Ingresso, 1)
            usuario = await session.get(Usuario, 2)
            self.assertIsNotNone(ingresso.deleted_at)
            self.assertTrue(usuario.bloqueado_resgate)
            metricas, lotes, _ = await admin.obter_dados_dashboard(session)
            self.assertEqual(metricas["total_resgatados"], 1500)
            self.assertEqual(metricas["taxa_ocupacao"], 100)
            self.assertEqual(lotes[0]["model"].quantidade_resgatada, 1500)
            self.assertEqual(lotes[0]["vagas_restantes"], 0)
            self.assertEqual(lotes[0]["status"]["key"], "esgotado")
            status = await public.coletar_status_lote_para_sse(session, 1)
            self.assertEqual(status["status_slug"], "esgotado")
            self.assertFalse(status["pode_resgatar"])
            # A Home ainda pode exibir o lote esgotado como fallback informativo.
            relevante = await public.obter_lote_relevante(session, datetime.now(timezone.utc))
            self.assertEqual(relevante.id, 1)
            self.assertEqual(public.calcular_status_publico(relevante, 0, datetime.now(timezone.utc))["status_slug"], "esgotado")

        service = ReservaBatchService(self.sessions)
        try:
            result = await service.reserve(lote_id=1, ip="192.0.2.1", rate_key="teste-ocupacao")
            self.assertEqual(result.status_code, 400)
            self.assertEqual(result.codigo, "esgotado")
            self.assertFalse(result.created)
        finally:
            await service.stop()
        async with self.sessions() as session:
            self.assertEqual(await session.scalar(select(func.count(ReservaIngresso.id))), 0)

    async def test_extravio_preserva_ocupacao_status_e_bloqueio_de_nova_reserva(self):
        response = await self.extraviar()
        self.assertTrue(json.loads(response.body)["sucesso"])
        self.assertIn("Ocupação do lote mantida", json.loads(response.body)["mensagem"])
        self.assertEqual((await self.session.get(Ingresso, 1)).cancelado_por_id, self.admin.id)
        await self.verificar_lote_cheio()
        with self.assertRaises(HTTPException) as exc:
            await self.extraviar()
        self.assertEqual(exc.exception.status_code, 404)

    async def test_cancelamento_aprovado_preserva_ocupacao_status_e_bloqueio_de_nova_reserva(self):
        response = await self.aprovar()
        self.assertIn("ocupação do lote foi mantida", json.loads(response.body)["mensagem"])
        self.assertEqual((await self.session.get(SolicitacaoCancelamento, 1)).status, "aprovado")
        await self.verificar_lote_cheio()
        with self.assertRaises(HTTPException) as exc:
            await self.aprovar()
        self.assertEqual(exc.exception.status_code, 400)

    async def test_aprovar_apos_extravio_nao_altera_contador_novamente(self):
        await self.extraviar()
        await self.aprovar()
        await self.verificar_lote_cheio()

    async def test_cancelar_lote_parcial_preserva_ocupacao_sem_esgotar_antes_da_hora(self):
        lote = await self.session.get(Lote, 1)
        lote.quantidade_resgatada = 1000
        await self.session.commit()
        await self.aprovar()
        async with self.sessions() as session:
            metricas, lotes, _ = await admin.obter_dados_dashboard(session)
            self.assertEqual(metricas["total_resgatados"], 1000)
            self.assertEqual(lotes[0]["vagas_restantes"], 500)
            self.assertEqual(lotes[0]["status"]["key"], "aberto")
            self.assertEqual((await public.coletar_status_lote_para_sse(session, 1))["status_slug"], "aberto")

    async def test_senha_incorreta_preserva_ingresso_e_contador(self):
        with self.assertRaises(HTTPException) as exc:
            await self.extraviar("senha-errada")
        self.assertEqual(exc.exception.status_code, 401)
        self.assertIsNone((await self.session.get(Ingresso, 1)).deleted_at)
        self.assertEqual((await self.session.get(Lote, 1)).quantidade_resgatada, 1500)

    async def test_email_de_cancelamento_informa_ocupacao_mantida(self):
        with patch.object(email_service, "enqueue_email", new_callable=AsyncMock, return_value=True) as enviar:
            self.assertTrue(await email_service.send_cancellation_result_email_async(
                "Participante", "participante@example.invalid", True))
        html = enviar.call_args.args[2]
        self.assertIn("continua contabilizado na ocupação do lote", html)
        self.assertNotIn("vaga foi devolvida", html)

    async def test_listagem_administrativa_retorna_motivo_do_participante_e_aceita_legado_sem_motivo(self):
        solicitacao = await self.session.get(SolicitacaoCancelamento, 1)
        motivo = 'Compromisso familiar.\nNão poderei comparecer <por motivos pessoais>.'
        solicitacao.motivo = motivo
        await self.session.commit()
        async with self.sessions() as session:
            response = await cancelamento.listar_solicitacoes_cancelamento(session=session, admin=self.admin)
        dados = json.loads(response.body)["solicitacoes"][0]
        self.assertEqual(dados["motivo"], motivo)
        self.assertIsNone(dados["motivo_rejeicao"])

        solicitacao.motivo = None
        await self.session.commit()
        async with self.sessions() as session:
            response = await cancelamento.listar_solicitacoes_cancelamento(session=session, admin=self.admin)
        self.assertIsNone(json.loads(response.body)["solicitacoes"][0]["motivo"])


if __name__ == "__main__":
    unittest.main()
