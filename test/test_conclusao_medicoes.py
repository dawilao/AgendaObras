import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.obra_service import obra_tem_medicoes_concluidas
from db import Database


class TestConclusaoMedicoes(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, 'test_agendaobras.db')
        self.db = Database(self.db_path)
        self.obra_id = self.db.criar_obra(
            'Obra Teste Conclusao',
            'Cliente Teste',
            1000.0,
            '2026-04-15',
            status='Em andamento'
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def _concluir_descricao(self, descricao: str, data_conclusao: str):
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            UPDATE obra_checklist
            SET concluido = 1, data_conclusao = ?
            WHERE obra_id = ? AND descricao = ?
            ''',
            (data_conclusao, self.obra_id, descricao)
        )
        conn.commit()
        conn.close()

    def test_abre_conclusao_quando_restam_so_itens_concluidos(self):
        self.assertTrue(self.db.criar_medicoes_dinamicas(self.obra_id, 3))
        self._concluir_descricao('MEDIÇÃO 04/2026', '2026-04-20')
        self._concluir_descricao('CONFIRMAÇÃO DE MEDIÇÃO 04/2026', '2026-05-10')
        self._concluir_descricao('MEDIÇÃO 05/2026', '2026-05-20')
        self._concluir_descricao('CONFIRMAÇÃO DE MEDIÇÃO 05/2026', '2026-06-10')

        self.assertTrue(self.db.criar_medicoes_dinamicas(self.obra_id, 1))

        self.assertTrue(self.db.verificar_todas_medicoes_concluidas(self.obra_id))
        self.assertTrue(obra_tem_medicoes_concluidas(self.db, self.obra_id))

    def test_nao_abre_quando_obra_ja_esta_finalizada(self):
        self.assertTrue(self.db.criar_medicoes_dinamicas(self.obra_id, 1))
        self._concluir_descricao('MEDIÇÃO 04/2026', '2026-04-20')
        self._concluir_descricao('CONFIRMAÇÃO DE MEDIÇÃO 04/2026', '2026-05-10')
        self.db.registrar_finalizacao_obra(self.obra_id, 'sem_pendencias')

        self.assertFalse(obra_tem_medicoes_concluidas(self.db, self.obra_id))

    def test_reabre_fluxo_quando_medicoes_sao_reconfiguradas(self):
        self.assertTrue(self.db.criar_medicoes_dinamicas(self.obra_id, 1))
        self._concluir_descricao('MEDIÇÃO 04/2026', '2026-04-20')
        self._concluir_descricao('CONFIRMAÇÃO DE MEDIÇÃO 04/2026', '2026-05-10')
        self.db.registrar_finalizacao_obra(self.obra_id, 'sem_pendencias')

        self.assertTrue(self.db.criar_medicoes_dinamicas(self.obra_id, 2))

        obra = self.db.obter_obra(self.obra_id)
        self.assertIsNone(obra.get('status_conclusao_obra'))
        self.assertEqual(obra.get('status'), 'Em Andamento')

        self._concluir_descricao('MEDIÇÃO 05/2026', '2026-05-20')
        self._concluir_descricao('CONFIRMAÇÃO DE MEDIÇÃO 05/2026', '2026-06-10')

        self.assertTrue(obra_tem_medicoes_concluidas(self.db, self.obra_id))


if __name__ == '__main__':
    unittest.main(verbosity=2)
