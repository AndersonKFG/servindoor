"""Homologação por CPF com SQLite isolado; sem e-mails, API externa ou produção."""

import json
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from sqlmodel import SQLModel, Session, create_engine

from app.core.deps import get_current_user
from app.db.session import get_session
from app.models.all_models import Ingresso, Lote, SolicitacaoValidacao, Usuario, UserRole
from app.routers import validacoes as routes


def cpf_valido(numero):
    digitos = str(numero).zfill(9)
    for tamanho in (9, 10):
        resto = sum(int(digitos[i]) * (tamanho + 1 - i) for i in range(tamanho)) * 10 % 11
        digitos += str(0 if resto == 10 else resto)
    return digitos


class AsyncSQLiteSession:
    def __init__(self, db):
        self.db = db
        self.fail_commit = False

    async def execute(self, statement):
        return self.db.execute(statement)

    def add(self, instance):
        self.db.add(instance)

    async def commit(self):
        if self.fail_commit:
            raise RuntimeError("Falha simulada no commit")
        self.db.commit()


class TestValidacoesListaCpfs(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)
        self.session = AsyncSQLiteSession(self.db)
        self.admin = Usuario(id=10000, cpf="11144477735", nome="Admin", role=UserRole.admin_geral)
        self.db.add_all([self.admin, Lote(id=1, nome="Lote", quantidade_total=5000, quantidade_resgatada=1200)])
        self.db.commit()
        self.ticket_email = patch.object(routes, "send_ticket_email_async", AsyncMock()).start()
        self.rejection_email = patch.object(routes, "send_validation_rejection_email_async", AsyncMock()).start()
        self.addCleanup(patch.stopall)

    def tearDown(self):
        self.ticket_email.assert_not_awaited()
        self.rejection_email.assert_not_awaited()
        self.db.close()
        self.engine.dispose()

    def criar(self, identifier, *, status="pendente_analise", identificado_api=False, ativo=True, excluido=False):
        self.db.add(Usuario(id=identifier, cpf=cpf_valido(identifier), nome=f"Pessoa {identifier}", ativo=ativo,
                            deleted_at=datetime.now(timezone.utc) if excluido else None))
        self.db.add(SolicitacaoValidacao(id=identifier, usuario_id=identifier, lote_id=1, status=status,
                                        identificado_api=identificado_api))

    def salvar(self):
        self.db.commit()
        self.db.expunge_all()

    async def processar(self, texto, confirmar=False):
        response = await routes.homologar_por_lista_cpfs(
            routes.HomologarListaCpfsRequest(lista_cpfs=texto, confirmar=confirmar), self.session, self.admin,
        )
        return json.loads(response.body)

    def ingressos(self):
        return self.db.execute(text("SELECT COUNT(*) FROM ingressos WHERE deleted_at IS NULL")).scalar_one()

    async def test_conferencia_normaliza_pontuacao_mantem_zero_deduplica_e_nao_altera_dados(self):
        self.criar(1)
        self.criar(2, identificado_api=True)
        self.salvar()
        cpf = cpf_valido(1)
        formatado = f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}"
        resultado = await self.processar(f"{formatado}\n{cpf};{cpf_valido(2)}, {cpf_valido(9)}\t123 11111111111")
        self.assertEqual(resultado["total_informados"], 6)
        self.assertEqual(resultado["cpfs_validos"], 3)
        self.assertEqual(resultado["cpfs_duplicados"], 1)
        self.assertEqual(resultado["cpfs_invalidos"], 2)
        self.assertEqual(resultado["cpfs_sem_pendencia"], 1)
        self.assertEqual(resultado["pendentes_encontrados"], 2)
        self.assertFalse(resultado["confirmado"])
        self.assertEqual(resultado["servidores_a_homologar"], [
            {"usuario_id": i, "nome": f"Pessoa {i}", "cpf": cpf_valido(i),
             "cpf_formatado": routes.formatar_cpf(cpf_valido(i))}
            for i in (1, 2)
        ])
        self.assertEqual(self.ingressos(), 0)
        self.assertFalse(self.db.get(Usuario, 1).validado)
        self.assertEqual(self.db.get(SolicitacaoValidacao, 1).status, "pendente_analise")

    async def test_aplica_somente_pendentes_da_lista_e_preserva_finalizados_e_cotas(self):
        for i, status in [(1, "pendente_analise"), (2, "pendente_analise"), (3, "aprovado"),
                          (4, "rejeitado"), (5, "pendente_analise")]:
            self.criar(i, status=status, identificado_api=i == 2)
        self.criar(6, ativo=False)
        self.criar(7, excluido=True)
        self.db.get(SolicitacaoValidacao, 3).comunicado = True
        self.db.get(Usuario, 4).bloqueado_resgate = True
        self.salvar()
        result = await self.processar("\n".join(cpf_valido(i) for i in (1, 2, 3, 4, 6, 7)), True)
        self.assertEqual((result["aprovados"], result["ingressos_emitidos"]), (2, 2))
        self.assertEqual(result["cpfs_sem_pendencia"], 4)
        for i in (1, 2):
            solicitacao = self.db.get(SolicitacaoValidacao, i)
            self.assertEqual(solicitacao.status, "aprovado")
            self.assertEqual(solicitacao.analisado_por_id, self.admin.id)
            self.assertIsNotNone(solicitacao.analisado_em)
            self.assertFalse(solicitacao.comunicado)
            self.assertIsNone(solicitacao.comunicado_em)
            self.assertTrue(self.db.get(Usuario, i).validado)
        self.assertFalse(self.db.get(SolicitacaoValidacao, 1).identificado_api)
        self.assertTrue(self.db.get(SolicitacaoValidacao, 2).identificado_api)
        self.assertTrue(self.db.get(SolicitacaoValidacao, 3).comunicado)
        self.assertTrue(self.db.get(Usuario, 4).bloqueado_resgate)
        self.assertEqual(self.db.get(SolicitacaoValidacao, 4).status, "rejeitado")
        for i in (5, 6, 7):
            self.assertEqual(self.db.get(SolicitacaoValidacao, i).status, "pendente_analise")
        self.assertEqual(self.db.get(Lote, 1).quantidade_resgatada, 1200)

    async def test_1200_cpfs_sao_homologados_sem_limite_da_paginacao_e_sem_reenvios(self):
        for i in range(1, 1201):
            self.criar(i)
        self.salvar()
        lista = "\n".join(cpf_valido(i) for i in range(1, 1201))
        conferencia = await self.processar(lista)
        self.assertEqual(conferencia["pendentes_encontrados"], 1200)
        self.assertEqual(len(conferencia["servidores_a_homologar"]), 1200)
        self.assertEqual({s["cpf"] for s in conferencia["servidores_a_homologar"]}, set(lista.splitlines()))
        result = await self.processar(lista, True)
        self.assertEqual((result["aprovados"], self.ingressos()), (1200, 1200))
        self.assertEqual((await self.processar(lista, True))["aprovados"], 0)
        self.assertEqual(self.ingressos(), 1200)

    async def test_preserva_ingresso_ativo_e_cargo_e_nao_duplica_em_multiplas_pendencias(self):
        self.criar(1)
        self.db.add(Lote(id=2, nome="Outro lote"))
        self.db.add(SolicitacaoValidacao(id=2, usuario_id=1, lote_id=2))
        self.db.add(Ingresso(usuario_id=1, lote_id=1, qr_code_token="token-preservado"))
        self.db.get(Usuario, 1).role = UserRole.portaria
        self.salvar()
        conferencia = await self.processar(cpf_valido(1))
        self.assertEqual(len(conferencia["servidores_a_homologar"]), 1)
        self.assertEqual(conferencia["pendentes_encontrados"], 2)
        result = await self.processar(cpf_valido(1), True)
        self.assertEqual((result["aprovados"], result["ingressos_emitidos"]), (2, 0))
        self.assertEqual(self.ingressos(), 1)
        self.assertEqual(self.db.get(Usuario, 1).role, UserRole.portaria)
        self.assertEqual(self.db.execute(text("SELECT qr_code_token FROM ingressos")).scalar_one(), "token-preservado")

    async def test_reconfere_pendencias_ao_aplicar_sem_reverter_decisao_posterior(self):
        self.criar(1)
        self.salvar()
        self.assertEqual((await self.processar(cpf_valido(1)))["pendentes_encontrados"], 1)
        self.db.get(SolicitacaoValidacao, 1).status = "rejeitado"
        self.db.commit()
        self.assertEqual((await self.processar(cpf_valido(1), True))["aprovados"], 0)
        self.assertEqual(self.ingressos(), 0)

    async def test_falha_no_commit_reverte_homologacao_validacao_e_ingresso(self):
        self.criar(1)
        self.salvar()
        self.session.fail_commit = True
        with self.assertRaises(RuntimeError):
            await self.processar(cpf_valido(1), True)
        self.db.rollback()
        self.assertEqual(self.db.get(SolicitacaoValidacao, 1).status, "pendente_analise")
        self.assertFalse(self.db.get(Usuario, 1).validado)
        self.assertEqual(self.ingressos(), 0)

    async def test_rejeita_listas_vazias_invalidas_ou_excessivas_sem_truncar_cpfs(self):
        for lista in ("   ", "123", "11111111111", "152998224725", "abc52998224725", f"{cpf_valido(1)} " * 10001):
            with self.subTest(lista=lista[:30]), self.assertRaises(HTTPException) as error:
                await self.processar(lista, True)
            self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(self.ingressos(), 0)

    async def test_endpoint_exclusivo_do_admin_geral(self):
        app = FastAPI()
        app.include_router(routes.router)

        async def sessao():
            yield self.session

        async def usuario():
            return self.admin

        app.dependency_overrides[get_session] = sessao
        app.dependency_overrides[get_current_user] = usuario
        for role in (UserRole.admin, UserRole.validador, UserRole.portaria, UserRole.servidor, UserRole.admin_geral):
            self.admin.role = role
            messages = []

            async def receive():
                return {"type": "http.request", "body": json.dumps({"lista_cpfs": cpf_valido(1)}).encode(), "more_body": False}

            async def send(message):
                messages.append(message)

            await app({
                "type": "http", "asgi": {"version": "3.0"}, "method": "POST", "scheme": "http",
                "path": "/api/admin/validacoes/homologar-por-cpfs", "query_string": b"",
                "headers": [(b"content-type", b"application/json")],
            }, receive, send)
            status = next(m["status"] for m in messages if m["type"] == "http.response.start")
            self.assertEqual(status, 200 if role == UserRole.admin_geral else 403)


if __name__ == "__main__":
    unittest.main()
