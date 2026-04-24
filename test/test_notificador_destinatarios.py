"""
Testes de destinatários do notificador por vínculo de contrato.

Regra esperada:
- admin recebe alertas de todos os contratos
- não-admin recebe apenas alertas de contratos vinculados
- fallback para config.email_destinatarios quando não há base de usuários
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auth_database import AuthDatabase
from contratos_database import ContratosDatabase
from database import Database
from notificador_prazos import NotificadorPrazos


class _DummyConfig:
    def __init__(self, fallback=None, critico=''):
        self.email_destinatarios = fallback or []
        self.email_critico = critico


class _DummyEmailService:
    def __init__(self, config):
        self.config = config


class _DummyGerador:
    def gerar_tarefas_mensais(self):
        return None


class TestNotificadorDestinatarios(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix='agenda_notif_dest_')
        self.agenda_db = os.path.join(self.temp_dir.name, 'agendaobras.db')
        self.users_db = os.path.join(self.temp_dir.name, 'users.db')
        self.contratos_db = os.path.join(self.temp_dir.name, 'contratos.db')

        self.old_env = {
            'AGENDA_OBRAS_DB_PATH': os.getenv('AGENDA_OBRAS_DB_PATH'),
            'AGENDA_OBRAS_USERS_DB_PATH': os.getenv('AGENDA_OBRAS_USERS_DB_PATH'),
            'AGENDA_OBRAS_CONTRATOS_DB_PATH': os.getenv('AGENDA_OBRAS_CONTRATOS_DB_PATH'),
        }

        os.environ['AGENDA_OBRAS_DB_PATH'] = self.agenda_db
        os.environ['AGENDA_OBRAS_USERS_DB_PATH'] = self.users_db
        os.environ['AGENDA_OBRAS_CONTRATOS_DB_PATH'] = self.contratos_db

        self.db = Database(self.agenda_db)
        self.auth_db = AuthDatabase(self.users_db)
        self.contr_db = ContratosDatabase(self.contratos_db)

    def tearDown(self):
        for key, value in self.old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temp_dir.cleanup()

    def _criar_notificador(self, fallback=None, critico=''):
        email_service = _DummyEmailService(_DummyConfig(fallback=fallback, critico=critico))
        return NotificadorPrazos(self.db, email_service, _DummyGerador())

    def test_admin_recebe_todos_contratos_nao_admin_so_vinculado(self):
        self.auth_db.criar_usuario('Admin', 'Master', 'admin@empresa.com', '123456', is_admin=True)
        self.auth_db.criar_usuario('Usuario', 'A', 'a@empresa.com', '123456', is_admin=False)
        self.auth_db.criar_usuario('Usuario', 'B', 'b@empresa.com', '123456', is_admin=False)

        usuarios = {u['email']: u['id'] for u in self.auth_db.listar_usuarios()}

        self.contr_db.vincular_usuario_contrato(usuarios['a@empresa.com'], 'C.E.F BAHIA - 4922.2024')
        self.contr_db.vincular_usuario_contrato(usuarios['b@empresa.com'], 'C.E.F MANAUS - 4569.2024')

        notificador = self._criar_notificador()

        destinatarios_bahia = notificador._obter_destinatarios_por_contrato('C.E.F BAHIA - 4922.2024')
        self.assertIn('admin@empresa.com', destinatarios_bahia)
        self.assertIn('a@empresa.com', destinatarios_bahia)
        self.assertNotIn('b@empresa.com', destinatarios_bahia)

        destinatarios_manaus = notificador._obter_destinatarios_por_contrato('C.E.F MANAUS - 4569.2024')
        self.assertIn('admin@empresa.com', destinatarios_manaus)
        self.assertIn('b@empresa.com', destinatarios_manaus)
        self.assertNotIn('a@empresa.com', destinatarios_manaus)

    def test_fallback_quando_sem_usuarios(self):
        fallback = ['fallback1@empresa.com', 'fallback2@empresa.com']
        notificador = self._criar_notificador(fallback=fallback)

        destinatarios = notificador._obter_destinatarios_por_contrato('C.E.F BAHIA - 4922.2024')
        self.assertEqual(destinatarios, fallback)

    def test_email_critico_adicionado_quando_alerta_critico(self):
        self.auth_db.criar_usuario('Admin', 'Master', 'admin@empresa.com', '123456', is_admin=True)
        notificador = self._criar_notificador(critico='critico@empresa.com')

        destinatarios = notificador._obter_destinatarios_por_contrato(
            'C.E.F BAHIA - 4922.2024', tem_critico=True
        )
        self.assertIn('admin@empresa.com', destinatarios)
        self.assertIn('critico@empresa.com', destinatarios)


if __name__ == '__main__':
    unittest.main()
