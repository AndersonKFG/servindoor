"""Valida isoladamente a função real do limitador, sem importar o app ou abrir banco."""
import ast
import secrets
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Optional


class LimitadorCargaTest(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).resolve().parents[2] / "app/routers/resgate.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name == "_chave_rate_limit_reserva")
        self.now = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
        fixed_now = self.now

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed_now.astimezone(tz) if tz else fixed_now.replace(tzinfo=None)

        self.settings = SimpleNamespace(LOAD_TEST_SECRET="a" * 64, LOAD_TEST_LOTE_ID=99,
                                       LOAD_TEST_UNTIL=(self.now + timedelta(hours=1)).isoformat())
        namespace = {"settings": self.settings, "Request": object, "Optional": Optional,
                     "secrets": secrets, "datetime": Clock, "timezone": timezone}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
        self.resolve = namespace[function.name]
        self.request = SimpleNamespace(headers={"x-load-test-key": "a" * 64})
        self.ip = "203.0.113.8"

    def result(self, lot=99, fingerprint="loadtest_run_1"):
        return self.resolve(self.request, lot, fingerprint, self.ip)

    def test_autorizado_tem_contador_por_dispositivo(self):
        self.assertEqual(self.result(), "loadtest:203.0.113.8:loadtest_run_1")
        self.assertNotEqual(self.result(), self.result(fingerprint="loadtest_run_2"))

    def test_configuracao_padrao_preserva_ip(self):
        self.settings.LOAD_TEST_SECRET = ""
        self.settings.LOAD_TEST_LOTE_ID = 0
        self.settings.LOAD_TEST_UNTIL = ""
        self.assertEqual(self.result(), self.ip)

    def test_chave_curta_ausente_errada_preserva_ip(self):
        for key in ["", "errada", "é" * 32]:
            with self.subTest(key_length=len(key)):
                self.request.headers = {"x-load-test-key": key}
                self.assertEqual(self.result(), self.ip)
        self.request.headers = {}
        self.assertEqual(self.result(), self.ip)
        self.settings.LOAD_TEST_SECRET = "curta"
        self.request.headers = {"x-load-test-key": "curta"}
        self.assertEqual(self.result(), self.ip)

    def test_lote_e_dispositivo_comuns_nao_recebem_excecao(self):
        self.assertEqual(self.result(lot=100), self.ip)
        for fingerprint in [None, "", "hw_abc", "loadtest_" + "x" * 100]:
            with self.subTest(fingerprint=fingerprint):
                self.assertEqual(self.result(fingerprint=fingerprint), self.ip)

    def test_prazo_invalido_expirado_sem_fuso_ou_longo_preserva_ip(self):
        for deadline in ["", "invalido", self.now.isoformat(),
                         (self.now - timedelta(seconds=1)).isoformat(),
                         (self.now + timedelta(hours=3)).isoformat(),
                         (self.now + timedelta(hours=1)).replace(tzinfo=None).isoformat()]:
            with self.subTest(deadline=deadline):
                self.settings.LOAD_TEST_UNTIL = deadline
                self.assertEqual(self.result(), self.ip)

    def test_offsets_diferentes_representam_mesmo_instante(self):
        self.settings.LOAD_TEST_UNTIL = (self.now + timedelta(hours=1)).astimezone(
            timezone(timedelta(hours=-3))).isoformat()
        self.assertTrue(self.result().startswith("loadtest:"))
        self.settings.LOAD_TEST_UNTIL = (self.now + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        self.assertTrue(self.result().startswith("loadtest:"))


if __name__ == "__main__":
    unittest.main()
