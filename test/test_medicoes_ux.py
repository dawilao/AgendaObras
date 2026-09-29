import datetime
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import Database
from services.medicao_service import eh_tarefa_medicao
from utils.formatters import competencias_medicoes, previa_medicoes, resumo_valor_medicao


class TestCompetenciasEPrevia(unittest.TestCase):
    """Prévia do seletor de quantidade de medições."""

    def test_competencias_viram_o_ano(self):
        self.assertEqual(
            competencias_medicoes(datetime.date(2026, 11, 15), 3),
            [(2026, 11), (2026, 12), (2027, 1)],
        )

    def test_competencias_quantidade_zero(self):
        self.assertEqual(competencias_medicoes(datetime.date(2026, 1, 1), 0), [])

    def test_previa_varias(self):
        self.assertEqual(
            previa_medicoes('2026-01-10', 6),
            'Serão criadas as medições de 01/2026 a 06/2026.',
        )

    def test_previa_uma(self):
        self.assertEqual(previa_medicoes('2026-03-01', 1), 'Será criada a medição de 03/2026.')

    def test_previa_reducao_avisa_remocao(self):
        texto = previa_medicoes('2026-01-01', 2, quantidade_atual=5)
        self.assertIn('de 01/2026 a 02/2026', texto)
        self.assertIn('pendentes após 02/2026 serão removidas', texto)

    def test_previa_data_invalida(self):
        self.assertEqual(previa_medicoes('', 3), '')
        self.assertEqual(previa_medicoes('10/01/2026', 3), '')


class TestEhTarefaMedicao(unittest.TestCase):
    """Separação das tarefas que vão para o campo Medições do checklist."""

    def test_identifica_as_duas_tarefas_do_mes(self):
        self.assertTrue(eh_tarefa_medicao('MEDIÇÃO 01/2026'))
        self.assertTrue(eh_tarefa_medicao('CONFIRMAÇÃO DE MEDIÇÃO 01/2026'))

    def test_ignora_outras_tarefas(self):
        self.assertFalse(eh_tarefa_medicao('RENOVAÇÃO DE SOLICITAÇÃO DE ACESSO'))
        self.assertFalse(eh_tarefa_medicao('MEDIÇÃO'))
        self.assertFalse(eh_tarefa_medicao(None))


class TestResumoValorMedicao(unittest.TestCase):
    """Resumo exibido no pop-up de valor da medição."""

    def test_dentro_do_saldo(self):
        r = resumo_valor_medicao(120_000.0, 30_000.0, 42_000.0)
        self.assertEqual(r['saldo'], 90_000.0)
        self.assertEqual(r['saldo_apos'], 48_000.0)
        self.assertEqual(r['pct_apos'], 60.0)
        self.assertFalse(r['excede'])

    def test_exatamente_o_saldo_nao_excede(self):
        self.assertFalse(resumo_valor_medicao(100_000.0, 60_000.0, 40_000.0)['excede'])

    def test_acima_do_saldo_excede(self):
        r = resumo_valor_medicao(100_000.0, 60_000.0, 40_000.01)
        self.assertTrue(r['excede'])
        self.assertEqual(r['saldo_apos'], -0.01)

    def test_sem_total_nunca_excede(self):
        r = resumo_valor_medicao(0, 0, 50_000.0)
        self.assertFalse(r['excede'])
        self.assertEqual(r['pct_apos'], 0.0)

    def test_valor_vazio(self):
        self.assertEqual(resumo_valor_medicao(100_000.0, 0, None)['saldo_apos'], 100_000.0)


class TestEditarValorMedicao(unittest.TestCase):
    """Editar o valor de uma confirmação já concluída, sem desmarcar."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self.temp_dir.name, 'test.db'))
        self.obra_id = self.db.criar_obra(
            'Obra UX', 'Cliente', valor_contrato=100_000.0,
            data_inicio='2026-01-01', status='Em Andamento', total_obra=100_000.0,
        )
        self.db.criar_medicoes_dinamicas(self.obra_id, 2)
        conn = self.db.get_connection()
        self.tarefa_id = conn.execute(
            "SELECT id FROM obra_checklist WHERE obra_id = ? "
            "AND descricao LIKE 'CONFIRMAÇÃO DE MEDIÇÃO %' ORDER BY mes_referencia",
            (self.obra_id,),
        ).fetchone()['id']
        conn.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_editar_valor_mantem_conclusao_e_data(self):
        self.db.registrar_valor_medido(self.tarefa_id, 30_000.0, concluir=True)
        conn = self.db.get_connection()
        conn.execute("UPDATE obra_checklist SET data_conclusao = '2026-02-08' WHERE id = ?", (self.tarefa_id,))
        conn.commit()
        conn.close()

        self.db.registrar_valor_medido(self.tarefa_id, 35_000.0, concluir=False)

        tarefa = self.db.obter_item_checklist(self.tarefa_id)
        self.assertEqual(tarefa['concluido'], 1)
        self.assertEqual(tarefa['data_conclusao'], '2026-02-08')
        self.assertEqual(tarefa['valor_medido'], 35_000.0)
        self.assertAlmostEqual(self.db.obter_soma_valores_medidos(self.obra_id), 35_000.0)

    def test_tarefas_criadas_batem_com_a_previa(self):
        conn = self.db.get_connection()
        descricoes = [r['descricao'] for r in conn.execute(
            "SELECT descricao FROM obra_checklist WHERE obra_id = ? "
            "AND descricao LIKE 'MEDIÇÃO %' ORDER BY mes_referencia",
            (self.obra_id,),
        ).fetchall()]
        conn.close()
        self.assertEqual(descricoes, ['MEDIÇÃO 01/2026', 'MEDIÇÃO 02/2026'])
        self.assertEqual(previa_medicoes('2026-01-01', 2), 'Serão criadas as medições de 01/2026 a 02/2026.')


if __name__ == '__main__':
    unittest.main(verbosity=2)
