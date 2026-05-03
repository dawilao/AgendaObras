import datetime
import os
import tempfile
import unittest
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Database


class TestMedicoesDinamicas(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, 'test_agendaobras.db')
        self.db = Database(self.db_path)

        self.obra_id = self.db.criar_obra(
            'Obra Teste Medicoes',
            'Cliente Teste',
            1000.0,
            '2026-04-15',
            status='Em andamento'
        )

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def _buscar_tarefas_medicao(self):
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT descricao, data_limite, concluido, mes_referencia
            FROM obra_checklist
            WHERE obra_id = ?
              AND (
                    descricao LIKE 'MEDIÇÃO %'
                    OR descricao LIKE 'CONFIRMAÇÃO DE MEDIÇÃO %'
                  )
            ORDER BY descricao
            ''',
            (self.obra_id,)
        )
        rows = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows

    def test_cria_pares_mensais_com_datas_corretas(self):
        self.assertTrue(self.db.criar_medicoes_dinamicas(self.obra_id, 3))

        tarefas = self._buscar_tarefas_medicao()
        self.assertEqual(len(tarefas), 6)

        datas = {item['descricao']: item['data_limite'] for item in tarefas}
        # A nomenclatura segue a competência da medição.
        self.assertEqual(datas['MEDIÇÃO 04/2026'], '2026-04-20')
        self.assertEqual(datas['MEDIÇÃO 05/2026'], '2026-05-20')
        self.assertEqual(datas['MEDIÇÃO 06/2026'], '2026-06-20')
        self.assertEqual(datas['CONFIRMAÇÃO DE MEDIÇÃO 04/2026'], '2026-05-10')
        self.assertEqual(datas['CONFIRMAÇÃO DE MEDIÇÃO 05/2026'], '2026-06-10')
        self.assertEqual(datas['CONFIRMAÇÃO DE MEDIÇÃO 06/2026'], '2026-07-10')

    def test_idempotencia_na_reexecucao(self):
        self.assertTrue(self.db.criar_medicoes_dinamicas(self.obra_id, 2))
        self.assertTrue(self.db.criar_medicoes_dinamicas(self.obra_id, 2))

        tarefas = self._buscar_tarefas_medicao()
        self.assertEqual(len(tarefas), 4)
        self.assertEqual(
            sorted(item['descricao'] for item in tarefas),
            [
                'CONFIRMAÇÃO DE MEDIÇÃO 04/2026',
                'CONFIRMAÇÃO DE MEDIÇÃO 05/2026',
                'MEDIÇÃO 04/2026',
                'MEDIÇÃO 05/2026',
            ]
        )

    def test_reduz_quantidade_sem_duplicar_concluidas(self):
        self.assertTrue(self.db.criar_medicoes_dinamicas(self.obra_id, 4))

        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            UPDATE obra_checklist
            SET concluido = 1, data_conclusao = ?
            WHERE obra_id = ? AND descricao = ?
            ''',
            ('2026-04-21', self.obra_id, 'MEDIÇÃO 06/2026')
        )
        conn.commit()
        conn.close()

        self.assertTrue(self.db.criar_medicoes_dinamicas(self.obra_id, 2))

        tarefas = self._buscar_tarefas_medicao()
        descricoes = {item['descricao'] for item in tarefas}
        self.assertSetEqual(
            descricoes,
            {
                'CONFIRMAÇÃO DE MEDIÇÃO 04/2026',
                'CONFIRMAÇÃO DE MEDIÇÃO 05/2026',
                'CONFIRMAÇÃO DE MEDIÇÃO 06/2026',
                'MEDIÇÃO 04/2026',
                'MEDIÇÃO 05/2026',
                'MEDIÇÃO 06/2026',
            }
        )

    def test_verifica_conclusao_so_com_todas_as_tarefas_fechadas(self):
        self.assertTrue(self.db.criar_medicoes_dinamicas(self.obra_id, 1))
        self.assertFalse(self.db.verificar_todas_medicoes_concluidas(self.obra_id))

        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            UPDATE obra_checklist
            SET concluido = 1, data_conclusao = ?
            WHERE obra_id = ? AND descricao = ?
            ''',
            ('2026-04-20', self.obra_id, 'MEDIÇÃO 04/2026')
        )
        conn.commit()
        conn.close()

        self.assertFalse(self.db.verificar_todas_medicoes_concluidas(self.obra_id))

        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            UPDATE obra_checklist
            SET concluido = 1, data_conclusao = ?
            WHERE obra_id = ? AND descricao = ?
            ''',
            ('2026-05-10', self.obra_id, 'CONFIRMAÇÃO DE MEDIÇÃO 04/2026')
        )
        conn.commit()
        conn.close()

        self.assertTrue(self.db.verificar_todas_medicoes_concluidas(self.obra_id))

    def test_primeira_medicao_apos_dia_20(self):
        # Cria uma obra com início no dia 20 -> primeira medição no mês seguinte
        obra_id2 = self.db.criar_obra(
            'Obra Teste Inicio 20',
            'Cliente Teste',
            2000.0,
            '2026-04-20',
            status='Em andamento'
        )

        self.assertTrue(self.db.criar_medicoes_dinamicas(obra_id2, 1))

        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT descricao, data_limite FROM obra_checklist
            WHERE obra_id = ? AND descricao LIKE 'MEDIÇÃO %'
            ''',
            (obra_id2,)
        )
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['descricao'], 'MEDIÇÃO 05/2026')
        self.assertEqual(rows[0]['data_limite'], '2026-05-20')


if __name__ == '__main__':
    unittest.main(verbosity=2)