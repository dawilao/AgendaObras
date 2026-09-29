import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import Database
from utils.formatters import calcular_split_medicao, calcular_valor_parceiro


class TestRegrasMedicoesFinanceiro(unittest.TestCase):
    """Regras de medição que afetam a aba Financeiro."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self.temp_dir.name, 'test.db'))
        self.obra_id = self.db.criar_obra(
            'Obra Regras', 'Cliente',
            valor_contrato=100_000.0,
            data_inicio='2026-01-01',
            status='Em Andamento',
            valor_percentual=10.0,
            valor_aditivo=20_000.0,
            total_obra=120_000.0,
        )
        self.db.criar_medicoes_dinamicas(self.obra_id, 3)
        self._ids = self._ids_confirmacao()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _ids_confirmacao(self):
        conn = self.db.get_connection()
        rows = conn.execute(
            "SELECT id FROM obra_checklist WHERE obra_id = ? "
            "AND descricao LIKE 'CONFIRMAÇÃO DE MEDIÇÃO %' ORDER BY mes_referencia",
            (self.obra_id,),
        ).fetchall()
        conn.close()
        return [r['id'] for r in rows]

    def _confirmar(self, tarefa_id, valor, pct=10.0):
        vp, ve = calcular_split_medicao(valor, pct)
        self.db.registrar_valor_medido(tarefa_id, valor, valor_parceiro_medicao=vp, valor_empresa_medicao=ve)
        self.db.marcar_item_checklist(tarefa_id, True)

    def _qtd_valores_tarefa(self, tarefa_id):
        conn = self.db.get_connection()
        n = conn.execute('SELECT COUNT(*) AS n FROM medicoes_valores WHERE tarefa_id = ?', (tarefa_id,)).fetchone()['n']
        conn.close()
        return n

    # ---------------------------------------------- desmarcar confirmação
    def test_desmarcar_confirmacao_exclui_valor(self):
        self._confirmar(self._ids[0], 30_000.0)
        self.db.marcar_item_checklist(self._ids[0], False)
        self.assertEqual(self._qtd_valores_tarefa(self._ids[0]), 0)
        self.assertEqual(self.db.obter_soma_valores_medidos(self.obra_id), 0.0)
        self.assertEqual(self.db.obter_valores_medicoes(self.obra_id), [])

    def test_desmarcar_uma_mantem_as_outras(self):
        self._confirmar(self._ids[0], 30_000.0)
        self._confirmar(self._ids[1], 20_000.0)
        self.db.marcar_item_checklist(self._ids[0], False)
        self.assertAlmostEqual(self.db.obter_soma_valores_medidos(self.obra_id), 20_000.0)

    def test_valor_de_tarefa_nao_concluida_nao_conta(self):
        """Valores legados de confirmações desmarcadas não entram no Financeiro."""
        self.db.registrar_valor_medido(self._ids[0], 30_000.0)
        self.assertEqual(self.db.obter_soma_valores_medidos(self.obra_id), 0.0)
        self.assertEqual(self.db.obter_valores_medicoes(self.obra_id), [])

    # ---------------------------------------------- pop-up (valor + conclusão)
    def test_registrar_com_concluir_conclui_na_mesma_transacao(self):
        self.assertTrue(self.db.registrar_valor_medido(self._ids[0], 30_000.0, concluir=True))
        self.assertEqual(self.db.obter_item_checklist(self._ids[0])['concluido'], 1)
        self.assertAlmostEqual(self.db.obter_soma_valores_medidos(self.obra_id), 30_000.0)

    def test_registrar_sem_concluir_nao_conclui(self):
        self.db.registrar_valor_medido(self._ids[0], 30_000.0)
        self.assertEqual(self.db.obter_item_checklist(self._ids[0])['concluido'], 0)

    def test_falha_ao_concluir_desfaz_o_valor(self):
        def _falhar(*args, **kwargs):
            raise RuntimeError('falha simulada')
        self.db._aplicar_marcacao_item = _falhar
        with patch('db.checklist_repo.log_error'):  # não grava a falha simulada na pasta erros/
            self.assertFalse(self.db.registrar_valor_medido(self._ids[0], 30_000.0, concluir=True))
        self.assertEqual(self._qtd_valores_tarefa(self._ids[0]), 0)

    def test_cancelar_popup_nao_mexe_no_status_da_obra(self):
        """Desmarcar uma confirmação que nunca foi concluída não reabre/altera a obra."""
        conn = self.db.get_connection()
        conn.execute("UPDATE obras SET status = 'Atrasada' WHERE id = ?", (self.obra_id,))
        conn.commit()
        conn.close()
        self.assertIsNone(self.db.marcar_item_checklist(self._ids[0], False))
        self.assertEqual(self.db.obter_obra(self.obra_id)['status'], 'Atrasada')

    # ---------------------------------------------- excluir obra
    def test_deletar_obra_remove_registros_de_medicao(self):
        self._confirmar(self._ids[0], 30_000.0)
        self.db.deletar_obra(self.obra_id)
        conn = self.db.get_connection()
        valores = conn.execute('SELECT COUNT(*) AS n FROM medicoes_valores WHERE obra_id = ?', (self.obra_id,)).fetchone()['n']
        config = conn.execute('SELECT COUNT(*) AS n FROM medicoes_obra WHERE obra_id = ?', (self.obra_id,)).fetchone()['n']
        conn.close()
        self.assertEqual((valores, config), (0, 0))

    # ---------------------------------------------- reduzir quantidade
    def test_reduzir_quantidade_remove_valores_das_tarefas_apagadas(self):
        ultima = self._ids[2]
        self.db.registrar_valor_medido(ultima, 10_000.0)  # valor pendurado, tarefa não concluída
        self.db.criar_medicoes_dinamicas(self.obra_id, 2)
        self.assertEqual(self._qtd_valores_tarefa(ultima), 0)

    def test_reduzir_quantidade_preserva_mes_concluido(self):
        ultima = self._ids[2]
        self._confirmar(ultima, 10_000.0)
        self.db.criar_medicoes_dinamicas(self.obra_id, 2)
        self.assertAlmostEqual(self.db.obter_soma_valores_medidos(self.obra_id), 10_000.0)

    # ---------------------------------------------- % Parceiro
    def test_valor_parceiro_incide_sobre_total_da_obra(self):
        self.assertAlmostEqual(calcular_valor_parceiro(100_000.0, 120_000.0, 10.0), 12_000.0)

    def test_valor_parceiro_sem_total_usa_contrato(self):
        self.assertAlmostEqual(calcular_valor_parceiro(100_000.0, None, 10.0), 10_000.0)

    def test_split_medicao(self):
        self.assertEqual(calcular_split_medicao(1_000.0, 12.5), (125.0, 875.0))

    def _atualizar_pct(self, pct):
        self.db.atualizar_obra(
            self.obra_id, 'Obra Regras', 'Cliente', 100_000.0, '2026-01-01', 'Em Andamento',
            valor_percentual=pct, valor_aditivo=20_000.0, total_obra=120_000.0,
        )

    def test_mudar_percentual_recalcula_medicoes(self):
        self._confirmar(self._ids[0], 30_000.0)
        self._confirmar(self._ids[1], 10_000.0)
        self._atualizar_pct(25.0)
        historico = {m['tarefa_id']: m for m in self.db.obter_valores_medicoes(self.obra_id)}
        self.assertAlmostEqual(historico[self._ids[0]]['valor_parceiro_medicao'], 7_500.0)
        self.assertAlmostEqual(historico[self._ids[0]]['valor_empresa_medicao'], 22_500.0)
        self.assertAlmostEqual(historico[self._ids[1]]['valor_parceiro_medicao'], 2_500.0)
        self.assertAlmostEqual(historico[self._ids[0]]['valor_medido'], 30_000.0)

    def test_zerar_percentual_passa_tudo_para_empresa(self):
        self._confirmar(self._ids[0], 30_000.0)
        self._atualizar_pct(0)
        med = self.db.obter_valores_medicoes(self.obra_id)[0]
        self.assertEqual(med['valor_parceiro_medicao'], 0.0)
        self.assertAlmostEqual(med['valor_empresa_medicao'], 30_000.0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
