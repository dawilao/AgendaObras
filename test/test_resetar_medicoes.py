import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import Database


class TestResetarMedicoesObra(unittest.TestCase):
    """Reset de medições pelo card (botão ADM), mesma regra do resetar_medicoes.py."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self.temp_dir.name, 'test_reset.db'))
        self.obra_id = self.db.criar_obra(
            'Obra Reset Teste', 'Cliente Teste', valor_contrato=100_000.0,
            data_inicio='2026-01-01', status='Em Andamento', total_obra=200_000.0,
        )
        self.db.criar_medicoes_dinamicas(self.obra_id, 3)

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def _contar(self, sql):
        conn = self.db.get_connection()
        try:
            return conn.execute(sql, (self.obra_id,)).fetchone()[0]
        finally:
            conn.close()

    def _tarefas_medicao(self):
        return self._contar(
            "SELECT COUNT(*) FROM obra_checklist WHERE obra_id = ? "
            "AND (descricao LIKE 'MEDIÇÃO %' OR descricao LIKE 'CONFIRMAÇÃO DE MEDIÇÃO %')"
        )

    def _primeira_confirmacao(self):
        conn = self.db.get_connection()
        try:
            return conn.execute(
                "SELECT id FROM obra_checklist WHERE obra_id = ? "
                "AND descricao LIKE 'CONFIRMAÇÃO DE MEDIÇÃO %' ORDER BY id",
                (self.obra_id,),
            ).fetchone()['id']
        finally:
            conn.close()

    def test_reset_remove_tarefas_valores_e_zera_quantidade(self):
        self.db.registrar_valor_medido(self._primeira_confirmacao(), 50_000.0, concluir=True)
        total_antes = self._contar('SELECT COUNT(*) FROM obra_checklist WHERE obra_id = ?')

        resultado = self.db.resetar_medicoes_obra(self.obra_id)

        self.assertEqual(resultado, {'tarefas': 6, 'valores': 1})
        self.assertEqual(self._tarefas_medicao(), 0)
        self.assertEqual(self._contar('SELECT COUNT(*) FROM medicoes_valores WHERE obra_id = ?'), 0)
        self.assertEqual(self.db.obter_medicoes_obra(self.obra_id)['quantidade'], 0)
        self.assertEqual(self.db.obter_soma_valores_medidos(self.obra_id), 0.0)
        # As demais tarefas do checklist ficam intactas
        self.assertEqual(self._contar('SELECT COUNT(*) FROM obra_checklist WHERE obra_id = ?'), total_antes - 6)

    def test_reset_permite_reconfigurar_do_zero(self):
        self.db.resetar_medicoes_obra(self.obra_id)
        self.db.criar_medicoes_dinamicas(self.obra_id, 2)
        self.assertEqual(self._tarefas_medicao(), 4)

    def test_reset_bloqueado_em_obra_concluida_ou_em_conclusao(self):
        self.db.registrar_finalizacao_obra(self.obra_id, 'sem_pendencias')
        with self.assertRaises(ValueError):
            self.db.resetar_medicoes_obra(self.obra_id)
        self.assertEqual(self._tarefas_medicao(), 6)


if __name__ == '__main__':
    unittest.main()
