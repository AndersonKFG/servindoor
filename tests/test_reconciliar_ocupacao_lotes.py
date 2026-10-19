"""Planos e aplicação em banco SQLite isolado, sem credenciais de produção."""

import copy
import argparse
import os
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlmodel import SQLModel

from app.models.all_models import Ingresso, Lote, ReservaIngresso, SolicitacaoValidacao, Usuario
from tools.reconciliar_ocupacao_lotes import aplicar_plano, gerar_plano
from tools import reconciliar_ocupacao_lotes as tool


class TestReconciliarOcupacao(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        async with AsyncSession(self.engine) as session:
            session.add(Lote(id=1, nome="Lote teste", quantidade_total=3, quantidade_resgatada=2))
            for identifier in range(1, 5):
                session.add(Usuario(id=identifier, cpf=str(identifier).zfill(11), nome="Teste"))
            for identifier, status in [(1, "aprovado"), (2, "pendente_analise"), (3, "rejeitado")]:
                # O terceiro resgate é legado, sem reserva vinculada.
                if identifier != 3:
                    session.add(ReservaIngresso(id=identifier, token=f"reserva-{identifier}", lote_id=1,
                        status="concluida", utilizada=True,
                        expira_em=datetime.now(timezone.utc) - timedelta(days=1)))
                session.add(SolicitacaoValidacao(id=identifier, usuario_id=identifier, lote_id=1,
                    status=status, reserva_id=identifier if identifier != 3 else None))
            session.add(Ingresso(id=1, usuario_id=1, lote_id=1, qr_code_token="cancelado",
                                deleted_at=datetime.now(timezone.utc)))
            await session.commit()

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def plano(self, ids=(1,)):
        async with self.engine.connect() as conn:
            return await gerar_plano(conn, ids, "banco-teste")

    async def contador(self):
        async with self.engine.connect() as conn:
            return await conn.scalar(text("SELECT quantidade_resgatada FROM lotes WHERE id=1"))

    async def sql(self, statement):
        async with self.engine.begin() as conn:
            await conn.execute(text(statement))

    async def aplicar(self, plano, origem="banco-teste"):
        async with self.engine.begin() as conn:
            return await aplicar_plano(conn, plano, origem)

    async def test_diagnostico_inclui_cancelado_pendente_rejeitado_e_legado_sem_duplicar(self):
        plano = await self.plano()
        lote = plano["lotes"][0]
        self.assertEqual(lote["ocupacao_reconstruida"], 3)
        self.assertEqual(lote["acrescimo"], 1)
        self.assertEqual(lote["bloqueios"], [])
        self.assertEqual(await self.contador(), 2)  # Diagnóstico não escreve.
        await self.aplicar(plano)
        self.assertEqual(await self.contador(), 3)
        novo = await self.plano()
        self.assertEqual(novo["lotes"][0]["acrescimo"], 0)
        await self.aplicar(novo)
        self.assertEqual(await self.contador(), 3)  # Nunca soma cancelados de novo.

    async def test_recusa_reaplicar_o_mesmo_plano_antigo(self):
        plano = await self.plano()
        await self.aplicar(plano)
        with self.assertRaisesRegex(ValueError, "Dados mudaram"):
            await self.aplicar(plano)
        self.assertEqual(await self.contador(), 3)

    async def test_recusa_outro_banco_e_valores_editados_no_plano(self):
        plano = await self.plano()
        with self.assertRaisesRegex(ValueError, "outro banco"):
            await self.aplicar(plano, "outro-banco")
        editado = copy.deepcopy(plano)
        editado["lotes"][0]["contador_proposto"] = 999
        with self.assertRaisesRegex(ValueError, "plano foi editado"):
            await self.aplicar(editado)
        self.assertEqual(await self.contador(), 2)

    async def test_recusa_plano_se_houver_novo_resgate_ou_contador_alterado(self):
        plano = await self.plano()
        await self.sql("UPDATE lotes SET quantidade_resgatada=3 WHERE id=1")
        with self.assertRaisesRegex(ValueError, "Dados mudaram"):
            await self.aplicar(plano)
        self.assertEqual(await self.contador(), 3)

    async def test_recusa_plano_se_evidencia_mudar_sem_alterar_contador(self):
        plano = await self.plano()
        await self.sql("UPDATE solicitacoes_validacao SET status='aprovado' WHERE id=2")
        with self.assertRaisesRegex(ValueError, "Dados mudaram"):
            await self.aplicar(plano)
        self.assertEqual(await self.contador(), 2)

    async def test_multiplos_ingressos_do_mesmo_usuario_bloqueiam_correcao(self):
        await self.sql("INSERT INTO ingressos (id, usuario_id, lote_id, qr_code_token, data_resgate) "
                       "VALUES (2,1,1,'duplicado',CURRENT_TIMESTAMP)")
        plano = await self.plano()
        self.assertIn("multiplos_ingressos_do_mesmo_usuario_no_lote", plano["lotes"][0]["bloqueios"])
        with self.assertRaisesRegex(ValueError, "ambiguidades"):
            await self.aplicar(plano)
        self.assertEqual(await self.contador(), 2)

    async def test_historico_insuficiente_nunca_reduz_contador(self):
        await self.sql("UPDATE lotes SET quantidade_resgatada=4 WHERE id=1")
        plano = await self.plano()
        self.assertEqual(plano["lotes"][0]["contador_proposto"], 4)
        with self.assertRaisesRegex(ValueError, "ambiguidades"):
            await self.aplicar(plano)
        self.assertEqual(await self.contador(), 4)

    async def test_nao_trunca_ocupacao_historica_superior_a_capacidade(self):
        await self.sql("UPDATE lotes SET quantidade_total=2 WHERE id=1")
        plano = await self.plano()
        self.assertTrue(plano["lotes"][0]["avisos"])
        self.assertEqual(plano["lotes"][0]["contador_proposto"], 3)
        await self.aplicar(plano)
        self.assertEqual(await self.contador(), 3)

    async def test_ingresso_legado_sem_solicitacao_conta_uma_vez(self):
        await self.sql("INSERT INTO ingressos (id, usuario_id, lote_id, qr_code_token, data_resgate, deleted_at) "
                       "VALUES (2,4,1,'legado',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
        plano = await self.plano()
        self.assertEqual(plano["lotes"][0]["ingressos_sem_solicitacao"], 1)
        self.assertEqual(plano["lotes"][0]["ocupacao_reconstruida"], 4)
        await self.aplicar(plano)
        self.assertEqual(await self.contador(), 4)

    async def test_divergencia_nao_explicada_por_cancelamentos_bloqueia(self):
        await self.sql("UPDATE ingressos SET deleted_at=NULL WHERE id=1")
        plano = await self.plano()
        self.assertIn("diferenca_nao_explicada_por_ingressos_cancelados", plano["lotes"][0]["bloqueios"])
        with self.assertRaisesRegex(ValueError, "ambiguidades"):
            await self.aplicar(plano)

    async def test_ingresso_antigo_nao_e_confundido_com_resgate_posterior(self):
        await self.sql("UPDATE ingressos SET data_resgate='2000-01-01 00:00:00' WHERE id=1")
        plano = await self.plano()
        self.assertIn("vinculo_entre_ingresso_e_solicitacao_ambiguo", plano["lotes"][0]["bloqueios"])
        with self.assertRaisesRegex(ValueError, "ambiguidades"):
            await self.aplicar(plano)

    async def test_reserva_orfa_ou_vinculo_inconsistente_bloqueiam(self):
        await self.sql("UPDATE solicitacoes_validacao SET reserva_id=NULL WHERE id=1")
        plano = await self.plano()
        self.assertIn("reservas_concluidas_sem_solicitacao", plano["lotes"][0]["bloqueios"])
        await self.sql("UPDATE solicitacoes_validacao SET reserva_id=1 WHERE id=1")
        await self.sql("UPDATE reservas_ingressos SET utilizada=FALSE WHERE id=1")
        plano = await self.plano()
        self.assertIn("solicitacao_com_reserva_inconsistente", plano["lotes"][0]["bloqueios"])
        with self.assertRaisesRegex(ValueError, "ambiguidades"):
            await self.aplicar(plano)

    async def test_erro_na_segunda_escrita_reverte_todos_os_lotes(self):
        # Uma falha na segunda escrita não pode deixar o primeiro lote corrigido.
        await self.sql("INSERT INTO lotes (id,nome,quantidade_total,quantidade_resgatada,ativo) VALUES (2,'Outro',1,0,TRUE)")
        await self.sql("INSERT INTO ingressos (id,usuario_id,lote_id,qr_code_token,data_resgate,deleted_at) "
                       "VALUES (2,4,2,'outro',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
        plano = await self.plano((1, 2))
        await self.sql("CREATE TRIGGER simular_falha BEFORE UPDATE ON lotes WHEN OLD.id=2 "
                       "BEGIN SELECT RAISE(ABORT, 'falha simulada'); END")
        with self.assertRaises(Exception):
            await self.aplicar(plano)
        self.assertEqual(await self.contador(), 2)


class TestArquivosReconciliacao(unittest.TestCase):
    def test_destino_existente_nao_e_sobrescrito_nem_acessa_banco(self):
        with tempfile.TemporaryDirectory() as pasta:
            destino = Path(pasta) / "plano.json"
            destino.write_text("preservar", encoding="utf-8")
            with patch("sys.argv", ["reconciliar", "--lote-id", "2", "--saida", str(destino)]), \
                    patch.object(tool, "executar", new_callable=AsyncMock) as executar, \
                    patch("sys.stderr"):
                self.assertEqual(tool.main(), 1)
                executar.assert_not_awaited()
            self.assertEqual(destino.read_text(encoding="utf-8"), "preservar")

    def test_falha_durante_aplicacao_mantem_plano_no_recibo_para_conferencia(self):
        with tempfile.TemporaryDirectory() as pasta:
            plano = Path(pasta) / "plano.json"
            recibo = Path(pasta) / "recibo.json"
            conteudo = {"versao": tool.VERSAO, "lotes": [{"lote_id": 2}], "origem": "teste"}
            import json
            plano.write_text(json.dumps(conteudo), encoding="utf-8")
            with patch("sys.argv", ["reconciliar", "--aplicar", str(plano), "--saida", str(recibo)]), \
                    patch.object(tool, "executar", new_callable=AsyncMock, side_effect=RuntimeError), \
                    patch("sys.stderr"):
                self.assertEqual(tool.main(), 1)
            registro = json.loads(recibo.read_text(encoding="utf-8"))
            self.assertEqual(registro["estado"], "verificar_banco")
            self.assertEqual(registro["plano"], conteudo)


@unittest.skipUnless(os.environ.get("RECONCILIACAO_TEST_DATABASE_URL"), "PostgreSQL descartável não configurado")
class TestReconciliarPostgres(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        url = make_url(os.environ["RECONCILIACAO_TEST_DATABASE_URL"])
        if url.host not in {"127.0.0.1", "localhost"} or url.database != "codex_ocupacao_test":
            raise ValueError("O teste PostgreSQL exige localhost e banco codex_ocupacao_test descartável.")
        self.schema = "ocupacao_test_" + uuid.uuid4().hex
        self.root_engine = create_async_engine(url)
        async with self.root_engine.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.engine = create_async_engine(url, connect_args={"server_settings": {"search_path": self.schema}})
        async with self.engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        async with AsyncSession(self.engine) as session:
            session.add(Usuario(id=1, cpf="00000000001", nome="Teste"))
            session.add(Lote(id=1, nome="Teste", quantidade_total=1, quantidade_resgatada=0))
            await session.flush()
            # create_all usa TIMESTAMP sem fuso nestes campos legados.
            instante = datetime.now(timezone.utc).replace(tzinfo=None)
            session.add(Ingresso(id=1, usuario_id=1, lote_id=1, qr_code_token="teste",
                                data_resgate=instante, deleted_at=instante))
            await session.commit()
        self.engine_patch = patch("app.db.session.engine", self.engine)
        self.engine_patch.start()

    async def asyncTearDown(self):
        self.engine_patch.stop()
        await self.engine.dispose()
        async with self.root_engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        await self.root_engine.dispose()

    async def diagnostico(self):
        return await tool.executar(argparse.Namespace(aplicar=None, lote_id=[1]), None)

    async def test_transacao_somente_leitura_e_aplicacao_real_com_repeticao_segura(self):
        gerar = tool.gerar_plano

        async def conferir_somente_leitura(conn, ids, origem):
            self.assertEqual(await conn.scalar(text("SHOW transaction_read_only")), "on")
            return await gerar(conn, ids, origem)

        with patch.object(tool, "gerar_plano", side_effect=conferir_somente_leitura):
            plano = await self.diagnostico()
        self.assertEqual(plano["lotes"][0]["contador_atual"], 0)
        await tool.executar(argparse.Namespace(aplicar=True), plano)
        conferencia = await self.diagnostico()
        self.assertEqual(conferencia["lotes"][0]["contador_atual"], 1)
        self.assertEqual(conferencia["lotes"][0]["acrescimo"], 0)
        with self.assertRaisesRegex(ValueError, "Dados mudaram"):
            await tool.executar(argparse.Namespace(aplicar=True), plano)

    async def test_lock_concorrente_falha_por_timeout_sem_alterar_contador(self):
        plano = await self.diagnostico()
        async with self.engine.begin() as outra_transacao:
            await outra_transacao.execute(text("LOCK TABLE ingressos IN ROW EXCLUSIVE MODE"))
            with self.assertRaises(DBAPIError) as exc:
                await tool.executar(argparse.Namespace(aplicar=True), plano)
            self.assertEqual(exc.exception.orig.sqlstate, "55P03")
        conferencia = await self.diagnostico()
        self.assertEqual(conferencia["lotes"][0]["contador_atual"], 0)


if __name__ == "__main__":
    unittest.main()
