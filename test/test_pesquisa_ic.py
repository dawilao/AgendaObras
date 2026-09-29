"""
Testes da pesquisa de obras pelo Contrato (IC).
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import Database


class TestPesquisaIC(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix='agendaobras_ic_test_')
        self.db = Database(os.path.join(self.temp_dir.name, 'agendaobras_test.db'))

        self.obra_com_ic = self.db.criar_obra(
            nome_contrato='Reforma Agência Centro',
            cliente='C.E.F BAHIA - 4922.2024',
            valor_contrato=1000.0,
            data_inicio='2026-04-24',
            contrato_ic='IC-7781.2025',
        )
        self.obra_sem_ic = self.db.criar_obra(
            nome_contrato='Pintura Agência Sul',
            cliente='C.E.F BAHIA - 4922.2024',
            valor_contrato=1000.0,
            data_inicio='2026-04-24',
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_listar_obras_encontra_por_ic(self):
        ids = {o['id'] for o in self.db.listar_obras('7781')}
        self.assertEqual(ids, {self.obra_com_ic})

    def test_listar_obras_por_contratos_encontra_por_ic(self):
        ids = {o['id'] for o in self.db.listar_obras_por_contratos(['C.E.F BAHIA - 4922.2024'], '7781')}
        self.assertEqual(ids, {self.obra_com_ic})

    def test_pesquisa_por_nome_continua_funcionando(self):
        ids = {o['id'] for o in self.db.listar_obras('Pintura')}
        self.assertEqual(ids, {self.obra_sem_ic})


if __name__ == '__main__':
    unittest.main()
