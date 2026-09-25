"""Coordenador da obra: coluna no banco e regra de exibição no card."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import Database
from db.contratos_repo import ContratosDatabase
from utils.obras_helper import ObrasHelper

CONTRATO = 'C.E.F PIAUI - 9218.2025'
USUARIOS = [
    {'id': 1, 'nome': 'Ana', 'sobrenome': 'Admin', 'email': 'ana@x', 'is_admin': 1},
    {'id': 2, 'nome': 'Bruno', 'sobrenome': 'Silva', 'email': 'bruno@x', 'is_admin': 0},
    {'id': 3, 'nome': 'Carla', 'sobrenome': 'Souza', 'email': 'carla@x', 'is_admin': 0},
]


class TestCoordenadorBanco(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self.temp_dir.name, 'obras.db'))
        self.obra_id = self.db.criar_obra('Obra Coordenador', CONTRATO, 100_000.0, '2026-01-01')

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_migracao_cria_coluna_vazia(self):
        self.assertIn('coordenador_id', self.db.obter_obra(self.obra_id))
        self.assertIsNone(self.db.obter_obra(self.obra_id)['coordenador_id'])

    def test_define_e_volta_ao_automatico(self):
        self.assertTrue(self.db.atualizar_coordenador_obra(self.obra_id, 3))
        self.assertEqual(self.db.obter_obra(self.obra_id)['coordenador_id'], 3)
        self.assertTrue(self.db.atualizar_coordenador_obra(self.obra_id, None))
        self.assertIsNone(self.db.obter_obra(self.obra_id)['coordenador_id'])

    def test_listar_vinculos(self):
        contratos = ContratosDatabase(os.path.join(self.temp_dir.name, 'contratos.db'))
        contratos.vincular_usuario_contrato(2, CONTRATO)
        contratos.vincular_usuario_contrato(3, CONTRATO)
        self.assertEqual(
            sorted((v['contrato_nome'], v['usuario_id']) for v in contratos.listar_vinculos()),
            [(CONTRATO, 2), (CONTRATO, 3)],
        )


class TestResolverCoordenador(unittest.TestCase):

    def contexto(self, vinculos):
        return ObrasHelper.montar_contexto_coordenadores(USUARIOS, vinculos)

    def test_responsavel_da_obra_tem_prioridade(self):
        ctx = self.contexto([{'contrato_nome': CONTRATO, 'usuario_id': 2}])
        obra = {'cliente': CONTRATO, 'coordenador_id': 3}
        self.assertEqual(ObrasHelper.resolver_coordenador(obra, *ctx), ('Carla Souza', False))

    def test_automatico_lista_vinculados_e_ignora_admin(self):
        ctx = self.contexto([{'contrato_nome': CONTRATO, 'usuario_id': uid} for uid in (3, 1, 2)])
        obra = {'cliente': f'  {CONTRATO} ', 'coordenador_id': None}
        self.assertEqual(ObrasHelper.resolver_coordenador(obra, *ctx), ('Bruno Silva, Carla Souza', True))

    def test_responsavel_excluido_volta_ao_automatico(self):
        ctx = self.contexto([{'contrato_nome': CONTRATO, 'usuario_id': 2}])
        obra = {'cliente': CONTRATO, 'coordenador_id': 99}
        self.assertEqual(ObrasHelper.resolver_coordenador(obra, *ctx), ('Bruno Silva', True))

    def test_sem_ninguem(self):
        ctx = self.contexto([{'contrato_nome': CONTRATO, 'usuario_id': 1}])
        obra = {'cliente': CONTRATO}
        self.assertEqual(ObrasHelper.resolver_coordenador(obra, *ctx), (None, True))


if __name__ == '__main__':
    unittest.main()
