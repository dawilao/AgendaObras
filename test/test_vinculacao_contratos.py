"""
Testes de vinculação de contratos com bancos temporários.
Valida vínculo usuário↔contrato e filtro de obras por contrato.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contratos_database import ContratosDatabase
from database import Database


class TestVinculacaoContratos(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix='agendaobras_vinc_test_')
        self.agenda_db_path = os.path.join(self.temp_dir.name, 'agendaobras_test.db')
        self.contratos_db_path = os.path.join(self.temp_dir.name, 'contratos_test.db')

        self.db = Database(self.agenda_db_path)
        self.contratos_db = ContratosDatabase(self.contratos_db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_vincular_e_listar_contratos_usuario(self):
        ok = self.contratos_db.vincular_usuario_contrato(10, 'C.E.F BAHIA - 4922.2024')
        self.assertTrue(ok)

        contratos_usuario = self.contratos_db.listar_contratos_usuario(10)
        self.assertIn('C.E.F BAHIA - 4922.2024', contratos_usuario)

    def test_vincular_usuario_contrato_normaliza_espacos(self):
        ok = self.contratos_db.vincular_usuario_contrato(11, '   C.E.F BAHIA - 4922.2024   ')
        self.assertTrue(ok)

        contratos_usuario = self.contratos_db.listar_contratos_usuario(11)
        self.assertEqual(contratos_usuario, ['C.E.F BAHIA - 4922.2024'])

    def test_substituir_vinculos_usuario_remove_antigos(self):
        self.contratos_db.vincular_usuario_contrato(20, 'C.E.F BAHIA - 4922.2024')
        self.contratos_db.vincular_usuario_contrato(20, 'C.E.F MANAUS - 4569.2024')

        ok = self.contratos_db.substituir_vinculos_usuario(
            20,
            ['C.E.F CURITIBA - 534.2025', 'C.E.F MANAUS - 4569.2024'],
        )
        self.assertTrue(ok)

        contratos_usuario = self.contratos_db.listar_contratos_usuario(20)
        self.assertEqual(
            contratos_usuario,
            ['C.E.F CURITIBA - 534.2025', 'C.E.F MANAUS - 4569.2024'],
        )

    def test_listar_obras_por_contratos_filtra_na_coluna_cliente(self):
        obra_permitida = self.db.criar_obra(
            nome_contrato='Obra Permitida',
            cliente='C.E.F BAHIA - 4922.2024',
            valor_contrato=1000.0,
            data_inicio='2026-04-24',
        )
        obra_bloqueada = self.db.criar_obra(
            nome_contrato='Obra Bloqueada',
            cliente='C.E.F MANAUS - 4569.2024',
            valor_contrato=1500.0,
            data_inicio='2026-04-24',
        )

        obras = self.db.listar_obras_por_contratos(['C.E.F BAHIA - 4922.2024'])
        ids = {o['id'] for o in obras}

        self.assertIn(obra_permitida, ids)
        self.assertNotIn(obra_bloqueada, ids)

    def test_listar_obras_por_contratos_sem_lista_retorna_vazio(self):
        self.db.criar_obra(
            nome_contrato='Obra X',
            cliente='C.E.F BAHIA - 4922.2024',
            valor_contrato=1000.0,
            data_inicio='2026-04-24',
        )

        obras_sem_permissao = self.db.listar_obras_por_contratos([])
        self.assertEqual(obras_sem_permissao, [])

    def test_listar_obras_por_contratos_funciona_com_cliente_legado_com_espacos(self):
        obra_legada = self.db.criar_obra(
            nome_contrato='Obra Legada',
            cliente='  C.E.F BAHIA - 4922.2024  ',
            valor_contrato=1000.0,
            data_inicio='2026-04-24',
        )

        obras = self.db.listar_obras_por_contratos(['C.E.F BAHIA - 4922.2024'])
        ids = {o['id'] for o in obras}
        self.assertIn(obra_legada, ids)


if __name__ == '__main__':
    unittest.main()
