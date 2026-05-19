"""Testes para a leitura atualizada do usuário logado."""

import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.auth_repo import AuthDatabase
from services.auth_service import obter_usuario_logado


class TestAuthMiddleware(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix='agendaobras_auth_test_')
        self.users_db_path = os.path.join(self.temp_dir.name, 'users_test.db')
        self.auth_db = AuthDatabase(self.users_db_path)
        self.auth_db.criar_usuario('Ana', 'Admin', 'ana@example.com', '1234', is_admin=False)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_obter_usuario_logado_recarrega_admin_do_banco(self):
        usuario = self.auth_db.autenticar('ana@example.com', '1234')
        self.assertIsNotNone(usuario)
        self.auth_db.promover_para_admin(usuario['id'])

        with patch('services.auth_service.app.storage', SimpleNamespace(user={
            'user_id': usuario['id'],
            'nome': 'Ana',
            'sobrenome': 'Admin',
            'email': 'ana@example.com',
            'is_admin': False,
        })):
            usuario_logado = obter_usuario_logado()

        self.assertTrue(usuario_logado['is_admin'])


if __name__ == '__main__':
    unittest.main()