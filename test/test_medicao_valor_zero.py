import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import Database
from utils.obras_helper import ObrasHelper


class TestMedicaoValorZero(unittest.TestCase):
    """Garante que valor_medido = 0.0 é aceito e processado corretamente em toda a cadeia."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self.temp_dir.name, 'test.db'))
        self.obra_id = self.db.criar_obra(
            'Obra Zero', 'Cliente',
            valor_contrato=100_000.0,
            data_inicio='2026-01-01',
            status='Em Andamento',
            total_obra=200_000.0,
        )
        self.db.criar_medicoes_dinamicas(self.obra_id, 2)
        conn = self.db.get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM obra_checklist WHERE obra_id = ? "
            "AND descricao LIKE 'CONFIRMAÇÃO DE MEDIÇÃO %' ORDER BY id",
            (self.obra_id,),
        )
        self._ids = [r['id'] for r in cur.fetchall()]
        conn.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    # ------------------------------------------------------------------ DB
    def test_registrar_zero_retorna_true(self):
        self.assertTrue(self.db.registrar_valor_medido(self._ids[0], 0.0))

    def test_zero_persiste_em_obra_checklist(self):
        self.db.registrar_valor_medido(self._ids[0], 0.0)
        conn = self.db.get_connection()
        row = conn.execute(
            'SELECT valor_medido FROM obra_checklist WHERE id = ?', (self._ids[0],)
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row['valor_medido'], 0.0)

    def test_zero_persiste_em_medicoes_valores(self):
        self.db.registrar_valor_medido(self._ids[0], 0.0)
        conn = self.db.get_connection()
        row = conn.execute(
            'SELECT valor_medido FROM medicoes_valores WHERE tarefa_id = ?', (self._ids[0],)
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row['valor_medido'], 0.0)

    def test_zero_aparece_no_historico(self):
        self.db.registrar_valor_medido(self._ids[0], 0.0)
        historico = self.db.obter_valores_medicoes(self.obra_id)
        valores = [m['valor_medido'] for m in historico]
        self.assertIn(0.0, valores)

    # ---------------------------------------------------------------- soma
    def test_soma_medicao_unica_zerada(self):
        self.db.registrar_valor_medido(self._ids[0], 0.0)
        self.assertEqual(self.db.obter_soma_valores_medidos(self.obra_id), 0.0)

    def test_soma_mista_zero_e_positivo(self):
        self.db.registrar_valor_medido(self._ids[0], 0.0)
        self.db.registrar_valor_medido(self._ids[1], 50_000.0)
        self.assertAlmostEqual(self.db.obter_soma_valores_medidos(self.obra_id), 50_000.0)

    # -------------------------------------------- percentual / progressbar
    def test_percentual_zero_sem_zerodivision(self):
        self.db.registrar_valor_medido(self._ids[0], 0.0)
        pct = self.db.calcular_percentual_faturado(self.obra_id)
        self.assertEqual(pct, 0.0)

    def test_progressbar_value_dentro_de_0_e_1(self):
        self.db.registrar_valor_medido(self._ids[0], 0.0)
        soma = self.db.obter_soma_valores_medidos(self.obra_id)
        total = 200_000.0
        pct = (soma / total * 100) if total > 0 else 0.0
        bar_value = min(pct / 100, 1.0)
        self.assertGreaterEqual(bar_value, 0.0)
        self.assertLessEqual(bar_value, 1.0)

    # ---------------------------------------------------------- formatação
    def test_formatar_valor_zero_int(self):
        self.assertEqual(ObrasHelper.formatar_valor(0), 'R$ 0,00')

    def test_formatar_valor_zero_float(self):
        self.assertEqual(ObrasHelper.formatar_valor(0.0), 'R$ 0,00')

    # -------------------------------------- lógica de campo vazio → 0.0
    def test_campo_vazio_vira_zero(self):
        valor_input_value = None  # simula campo em branco
        valor = float(valor_input_value) if valor_input_value is not None else 0.0
        self.assertEqual(valor, 0.0)

    def test_campo_zero_explicito(self):
        valor_input_value = 0.0  # simula usuário digitando 0
        valor = float(valor_input_value) if valor_input_value is not None else 0.0
        self.assertEqual(valor, 0.0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
