"""Paginação e filtros da validação com transações SQLite isoladas."""

import json
import unittest

from sqlalchemy import text
from sqlmodel import SQLModel, Session, create_engine

from app.models.all_models import Lote, Secretaria, SolicitacaoValidacao, Usuario, UserRole
from app.routers.validacoes import listar_solicitacoes_validacao


class AsyncSessionAdapter:
    def __init__(self, session):
        self.session = session

    async def execute(self, statement, params=None):
        return self.session.execute(statement, params or {})


class TestValidacoesPaginacao(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)
        self.db.execute(text("CREATE TABLE resgate_jobs (solicitacao_id INTEGER, status TEXT, job_type TEXT)"))
        self.db.add_all([Secretaria(id=i, nome=f"Secretaria {i}") for i in (1, 2, 3)])
        self.db.add(Lote(id=1, nome="Lote de teste"))
        self.admin = Usuario(id=100, cpf="11144477735", nome="Admin", role=UserRole.admin_geral)
        self.db.add(self.admin)
        for i in range(1, 62):
            secretaria_id = 1 if i <= 40 else (2 if i <= 60 else 3)
            self.db.add(Usuario(id=i, cpf=str(i).zfill(11), nome=f"Pessoa {i}", secretaria_id=secretaria_id))
            self.db.add(SolicitacaoValidacao(
                id=i, usuario_id=i, lote_id=1, secretaria_id=secretaria_id if i != 40 else None,
                status="pendente_analise" if i <= 45 else ("aprovado" if i <= 55 else "rejeitado"),
                identificado_api=i % 2 == 0, comunicado=i >= 51,
            ))
        self.db.execute(text("INSERT INTO resgate_jobs VALUES (45, 'done', 'external_validation')"))
        self.db.commit()
        self.db.expunge_all()
        self.session = AsyncSessionAdapter(self.db)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    async def listar(self, *, page=1, limit=25, busca="", status="pendente_analise", secretaria=None, usuario=None):
        result = await listar_solicitacoes_validacao(
            status_filtro=status, secretaria_id=secretaria, session=self.session,
            validador=usuario or self.admin, page=page, limit=limit, busca=busca,
        )
        return json.loads(result.body)

    async def test_pagina_so_carrega_os_registros_necessarios_e_preserva_kpis(self):
        primeira = await self.listar()
        self.assertEqual([s["id"] for s in primeira["solicitacoes"]], list(range(45, 20, -1)))
        self.assertEqual(primeira["pagination"], {"page": 1, "limit": 25, "total": 45, "total_pages": 2})
        self.assertEqual(primeira["kpis"]["total_geral"], 61)
        self.assertEqual(primeira["kpis"]["total_pendentes"], 45)
        self.assertEqual(primeira["kpis"]["total_confirmados_api"], 22)
        self.assertEqual(primeira["kpis"]["total_comunicacao_pendente"], 5)
        self.assertEqual(primeira["solicitacoes"][0]["validacao_externa_status"], "done")
        carregadas = [obj for obj in self.db.identity_map.values() if isinstance(obj, SolicitacaoValidacao)]
        self.assertLessEqual(len(carregadas), 25)
        segunda = await self.listar(page=2)
        self.assertEqual([s["id"] for s in segunda["solicitacoes"]], list(range(20, 0, -1)))
        self.assertEqual(primeira["kpis"], segunda["kpis"])
        self.assertEqual({s["id"] for s in primeira["secretarias_disponiveis"]}, {1, 2, 3})

    async def test_busca_antes_de_paginar_nome_cpf_protocolo_secretaria(self):
        for busca, esperado in [("Pessoa 2", {2, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29}),
                                ("00000000002", {2}), ("VAL-000002", {2}),
                                ("Secretaria 2", {41, 42, 43, 44, 45})]:
            with self.subTest(busca=busca):
                data = await self.listar(busca=busca, limit=50)
                self.assertEqual({s["id"] for s in data["solicitacoes"]}, esperado)
                self.assertEqual(data["pagination"]["total"], len(esperado))
        parcial = await self.listar(busca="val-0000", limit=50, status="todos")
        self.assertEqual(parcial["pagination"]["total"], 61)
        literal = await self.listar(busca="%")
        self.assertEqual(literal["pagination"]["total"], 0)

    async def test_confirmados_api_filtrados_antes_da_paginacao(self):
        data = await self.listar(status="confirmados_api", page=2, limit=10)
        self.assertEqual(data["pagination"], {"page": 2, "limit": 10, "total": 22, "total_pages": 3})
        self.assertTrue(all(s["identificado_api"] and s["status"] == "pendente_analise" for s in data["solicitacoes"]))

    async def test_secretaria_do_usuario_e_usada_quando_solicitacao_nao_tem(self):
        data = await self.listar(secretaria=1, limit=50)
        self.assertEqual(data["pagination"]["total"], 40)
        self.assertIn(40, [s["id"] for s in data["solicitacoes"]])

    async def test_permissoes_limitam_cards_totais_e_opcoes_de_secretaria(self):
        validador = Usuario(cpf="52998224725", nome="Validador", role=UserRole.validador, secretarias_validador="1")
        data = await self.listar(usuario=validador, status="todos", limit=50)
        self.assertEqual(data["pagination"]["total"], 40)
        self.assertEqual(data["kpis"]["total_geral"], 40)
        self.assertEqual(data["secretarias_disponiveis"], [{"id": 1, "nome": "Secretaria 1"}])
        self.assertTrue(all(s["secretaria_id"] == 1 for s in data["solicitacoes"]))
        proibido = await self.listar(usuario=validador, secretaria=2)
        self.assertEqual(proibido["pagination"]["total"], 0)
        validador.secretarias_validador = None
        vazio = await self.listar(usuario=validador)
        self.assertEqual(vazio["kpis"]["total_geral"], 0)
        self.assertEqual(vazio["solicitacoes"], [])
        self.assertEqual(vazio["secretarias_disponiveis"], [])

    async def test_admin_consulta_todas_as_secretarias_com_ou_sem_atribuicoes(self):
        for roles in (None, "admin", "validador, admin"):
            for atribuicoes in (None, "1"):
                with self.subTest(roles=roles, atribuicoes=atribuicoes):
                    admin = Usuario(
                        cpf="52998224725", nome="Administrador",
                        role=UserRole.admin if roles is None else UserRole.validador,
                        roles=roles, secretaria_id=1, secretarias_validador=atribuicoes,
                    )
                    pendentes = await self.listar(usuario=admin)
                    self.assertEqual(pendentes["pagination"]["total"], 45)
                    primeira = await self.listar(usuario=admin, status="todos", limit=50)
                    segunda = await self.listar(usuario=admin, status="todos", limit=50, page=2)
                    self.assertEqual(primeira["pagination"]["total"], 61)
                    self.assertEqual(
                        {s["id"] for s in primeira["solicitacoes"] + segunda["solicitacoes"]},
                        set(range(1, 62)),
                    )
                    self.assertEqual(primeira["kpis"]["total_geral"], 61)
                    self.assertEqual(primeira["kpis"]["total_pendentes"], 45)
                    self.assertEqual({s["id"] for s in primeira["secretarias_disponiveis"]}, {1, 2, 3})
                    self.assertFalse(primeira["is_superadmin"])
                    filtrada = await self.listar(usuario=admin, status="todos", secretaria=3)
                    self.assertEqual([s["id"] for s in filtrada["solicitacoes"]], [61])
                    busca = await self.listar(usuario=admin, status="todos", busca="Pessoa 61")
                    self.assertEqual([s["id"] for s in busca["solicitacoes"]], [61])

    async def test_pagina_fora_do_intervalo_e_ajustada_apos_remocao_do_ultimo_card(self):
        data = await self.listar(page=999, limit=10)
        self.assertEqual(data["pagination"]["page"], 5)
        self.assertEqual(len(data["solicitacoes"]), 5)
        self.db.execute(text("UPDATE solicitacoes_validacao SET status = 'aprovado' WHERE id <= 5"))
        self.db.commit()
        data = await self.listar(page=5, limit=10)
        self.assertEqual(data["pagination"]["page"], 4)
        self.assertEqual(len(data["solicitacoes"]), 10)


if __name__ == "__main__":
    unittest.main()
