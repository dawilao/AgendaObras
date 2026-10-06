import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tempfile
import unittest
from pathlib import Path

from db.auth_repo import AuthDatabase
from services.financeiro_service import (definir_permissao_financeiro, exigir_editar, exigir_ver,
                                         pode_editar_financeiro, pode_ver_financeiro, ve_todas_as_obras)

OBRA = {'id': 10, 'cliente': 'CAIXA', 'coordenador_id': 7}
ADMIN = {'id': 1, 'is_admin': True, 'financeiro': 0}
FINANCEIRO = {'id': 2, 'is_admin': False, 'financeiro': 1}
COORDENADOR = {'id': 7, 'is_admin': False, 'financeiro': 0}
VINCULADO_AO_CONTRATO = {'id': 8, 'is_admin': False, 'financeiro': 0}


class PermissaoTest(unittest.TestCase):
    def test_quem_ve(self):
        for user in (ADMIN, FINANCEIRO, COORDENADOR):
            self.assertTrue(pode_ver_financeiro(user, OBRA))
        for user in (VINCULADO_AO_CONTRATO, None, {}):
            self.assertFalse(pode_ver_financeiro(user, OBRA))

    def test_coordenador_so_da_propria_obra(self):
        self.assertFalse(pode_ver_financeiro(COORDENADOR, dict(OBRA, coordenador_id=99)))
        sem_coordenador = dict(OBRA, coordenador_id=None)
        self.assertFalse(pode_ver_financeiro(COORDENADOR, sem_coordenador))
        self.assertTrue(pode_ver_financeiro(ADMIN, sem_coordenador))
        self.assertTrue(pode_ver_financeiro(FINANCEIRO, sem_coordenador))

    def test_adm_e_financeiro_veem_todas_as_obras(self):
        self.assertTrue(ve_todas_as_obras(ADMIN))
        self.assertTrue(ve_todas_as_obras(FINANCEIRO))
        for user in (COORDENADOR, VINCULADO_AO_CONTRATO, None, {}):
            self.assertFalse(ve_todas_as_obras(user))

    def test_so_o_financeiro_altera(self):
        self.assertTrue(pode_editar_financeiro(FINANCEIRO))
        for user in (ADMIN, COORDENADOR, VINCULADO_AO_CONTRATO, None):
            self.assertFalse(pode_editar_financeiro(user))

    def test_exigir_confere_no_servidor(self):
        self.assertEqual(exigir_ver(OBRA, lambda: COORDENADOR), COORDENADOR)
        with self.assertRaises(PermissionError):
            exigir_ver(OBRA, lambda: VINCULADO_AO_CONTRATO)
        with self.assertRaises(PermissionError):
            exigir_editar(lambda: ADMIN)
        self.assertEqual(exigir_editar(lambda: FINANCEIRO), FINANCEIRO)


class DefinirFinanceiroTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.auth = AuthDatabase(str(Path(self.tmp.name) / 'users.db'))
        self.auth.criar_usuario('Ana', 'Fin', 'ana@x.com', 'senha123')
        self.user_id = self.auth.listar_usuarios()[0]['id']

    def test_coluna_comeca_desligada_e_so_admin_altera(self):
        self.assertEqual(self.auth.obter_usuario_por_id(self.user_id)['financeiro'], 0)
        with self.assertRaises(PermissionError):
            definir_permissao_financeiro(self.user_id, True, lambda: FINANCEIRO, self.auth)
        with self.assertRaises(ValueError):
            definir_permissao_financeiro(self.user_id, 1, lambda: ADMIN, self.auth)
        definir_permissao_financeiro(self.user_id, True, lambda: ADMIN, self.auth)
        self.assertEqual(self.auth.obter_usuario_por_id(self.user_id)['financeiro'], 1)
        self.assertEqual(self.auth.listar_usuarios()[0]['financeiro'], 1)


if __name__ == '__main__':
    unittest.main()
