import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import Database


class TestCalculosFinanceiros(unittest.TestCase):
    """Testa os cálculos dinâmicos da aba Financeiro (Fase 3)."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self.temp_dir.name, 'test_financeiro.db')
        self.db = Database(db_path)

        self.obra_id = self.db.criar_obra(
            'Obra Financeiro Teste',
            'Cliente Teste',
            valor_contrato=100_000.0,
            data_inicio='2026-01-01',
            status='Em Andamento',
            total_obra=200_000.0,
        )
        # Cria 2 medições dinâmicas para ter tarefas de CONFIRMAÇÃO disponíveis
        self.db.criar_medicoes_dinamicas(self.obra_id, 2)
        self._ids_confirmacao = self._ids_tarefas_confirmacao()

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def _ids_tarefas_confirmacao(self):
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM obra_checklist WHERE obra_id = ? AND descricao LIKE 'CONFIRMAÇÃO DE MEDIÇÃO %' ORDER BY id",
            (self.obra_id,),
        )
        ids = [row['id'] for row in cursor.fetchall()]
        conn.close()
        return ids

    # ------------------------------------------------------------------ soma
    def test_soma_zero_sem_medicoes(self):
        soma = self.db.obter_soma_valores_medidos(self.obra_id)
        self.assertEqual(soma, 0.0)

    def test_soma_uma_medicao(self):
        self.db.registrar_valor_medido(self._ids_confirmacao[0], 50_000.0)
        self.assertAlmostEqual(self.db.obter_soma_valores_medidos(self.obra_id), 50_000.0)

    def test_soma_duas_medicoes(self):
        self.db.registrar_valor_medido(self._ids_confirmacao[0], 50_000.0)
        self.db.registrar_valor_medido(self._ids_confirmacao[1], 30_000.0)
        self.assertAlmostEqual(self.db.obter_soma_valores_medidos(self.obra_id), 80_000.0)

    def test_soma_substitui_valor_anterior_mesma_tarefa(self):
        """Registrar duas vezes a mesma tarefa substitui, não acumula."""
        self.db.registrar_valor_medido(self._ids_confirmacao[0], 50_000.0)
        self.db.registrar_valor_medido(self._ids_confirmacao[0], 70_000.0)
        self.assertAlmostEqual(self.db.obter_soma_valores_medidos(self.obra_id), 70_000.0)

    # ------------------------------------------------- percentual faturado
    def test_percentual_zero_sem_medicoes(self):
        self.assertEqual(self.db.calcular_percentual_faturado(self.obra_id), 0.0)

    def test_percentual_50_porcento(self):
        # total_obra = 200_000, medição = 100_000 → 50 %
        self.db.registrar_valor_medido(self._ids_confirmacao[0], 100_000.0)
        self.assertAlmostEqual(self.db.calcular_percentual_faturado(self.obra_id), 50.0)

    def test_percentual_100_porcento(self):
        self.db.registrar_valor_medido(self._ids_confirmacao[0], 200_000.0)
        self.assertAlmostEqual(self.db.calcular_percentual_faturado(self.obra_id), 100.0)

    def test_percentual_acima_de_100(self):
        """Medições acima do total_obra devem resultar em percentual > 100."""
        self.db.registrar_valor_medido(self._ids_confirmacao[0], 250_000.0)
        pct = self.db.calcular_percentual_faturado(self.obra_id)
        self.assertGreater(pct, 100.0)
        self.assertAlmostEqual(pct, 125.0)

    def test_percentual_total_obra_zero(self):
        """total_obra = 0 não deve lançar exceção — retorna 0."""
        obra_id = self.db.criar_obra(
            'Obra Sem Total',
            'Cliente',
            valor_contrato=1000.0,
            data_inicio='2026-01-01',
            total_obra=0,
        )
        self.assertEqual(self.db.calcular_percentual_faturado(obra_id), 0.0)

    # -------------------------------------------------- total a faturar
    def test_saldo_igual_total_obra_sem_medicoes(self):
        saldo = self.db.calcular_total_faturar(self.obra_id)
        self.assertAlmostEqual(saldo, 200_000.0)

    def test_saldo_positivo(self):
        self.db.registrar_valor_medido(self._ids_confirmacao[0], 80_000.0)
        saldo = self.db.calcular_total_faturar(self.obra_id)
        self.assertAlmostEqual(saldo, 120_000.0)

    def test_saldo_zero_exatamente_faturado(self):
        self.db.registrar_valor_medido(self._ids_confirmacao[0], 200_000.0)
        self.assertAlmostEqual(self.db.calcular_total_faturar(self.obra_id), 0.0)

    def test_saldo_negativo_acima_do_orcamento(self):
        """Quando medições ultrapassam total_obra o saldo deve ser negativo."""
        self.db.registrar_valor_medido(self._ids_confirmacao[0], 250_000.0)
        saldo = self.db.calcular_total_faturar(self.obra_id)
        self.assertLess(saldo, 0.0)
        self.assertAlmostEqual(saldo, -50_000.0)

    def test_arredondamento_duas_casas(self):
        self.db.registrar_valor_medido(self._ids_confirmacao[0], 33_333.333)
        saldo = self.db.calcular_total_faturar(self.obra_id)
        # Verifica que o resultado tem no máximo 2 casas decimais
        self.assertEqual(saldo, round(saldo, 2))


if __name__ == '__main__':
    unittest.main(verbosity=2)
