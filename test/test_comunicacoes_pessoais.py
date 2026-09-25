import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from comunicacoes.runtime import get_store, owner_id, authorize_user
from comunicacoes.store import MailStore
from comunicacoes.imap_reader import IMAPConfig, sync_mail
from comunicacoes.session import register, unregister, disconnect_user, temporary_import
from comunicacoes.publishing import publish_message
from test_comunicacoes import mail


class PersonalMailTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.a = get_store(1, self.tmp.name)
        self.b = get_store(2, self.tmp.name)
        self.shared = MailStore(Path(self.tmp.name) / 'shared.db')
        for store in [self.a, self.b]:
            store.save_work('10', 'Medina', '03738/2026', ['MEDINA'], True, 'test')

    def import_one(self, store, raw=None, uid='1'):
        return store.import_message(raw or mail(), ('pilot@example.invalid', 'INBOX', '1', uid))[0]

    def test_users_are_isolated(self):
        self.import_one(self.a)
        self.assertEqual(len(self.a.messages()), 1)
        self.assertEqual(self.b.messages(), [])
        self.assertEqual(self.shared.messages(), [])
        self.assertNotEqual(self.a.path, self.b.path)

    def test_owner_id_rejects_traversal(self):
        for value in [None, True, '../2', '1/2', -1, 0]:
            with self.assertRaises(PermissionError):
                owner_id(value)

    def test_disconnect_only_affects_owner(self):
        first, second = register(1), register(2)
        try:
            disconnect_user(1)
            self.assertTrue(first.is_set())
            self.assertFalse(second.is_set())
        finally:
            unregister(1, first)
            unregister(2, second)

    def test_password_discarded_success_and_failure(self):
        def ok(store, config, cancel=None):
            return 'done'
        def fail(store, config, cancel=None):
            raise RuntimeError('failed')
        for reader in [ok, fail]:
            cfg = IMAPConfig('host', 'user', 'temporary-secret', ['INBOX'], ['MEDINA'])
            try:
                temporary_import(self.a, cfg, threading.Event(), reader)
            except RuntimeError:
                pass
            self.assertEqual(cfg.password, '')

    def test_cancel_before_connect(self):
        event = threading.Event()
        event.set()
        def should_not_connect(*args, **kwargs):
            self.fail('Conexão não deveria ser iniciada.')
        result = sync_mail(self.a, IMAPConfig('host', 'user', 'secret', ['INBOX'], ['MEDINA']), should_not_connect, event)
        self.assertIn('interrompida', result)
        self.assertEqual(self.a.last_run()['status'], 'interrompido')

    def test_publish_persists_independent_of_connection(self):
        mid = self.import_one(self.a, mail(attachment=True))
        pid, fresh = publish_message(self.a, self.shared, mid, 'user:1', {'10'})
        disconnect_user(1)
        self.assertTrue(fresh)
        self.assertEqual(self.shared.detail(pid)[0]['obra_id'], '10')
        self.assertEqual(len(self.shared.detail(pid)[1]), 1)

    def test_same_message_from_two_users_published_once(self):
        a = self.import_one(self.a)
        b = self.import_one(self.b)
        publish_message(self.a, self.shared, a, 'user:1', {'10'})
        _, fresh = publish_message(self.b, self.shared, b, 'user:2', {'10'})
        self.assertFalse(fresh)
        self.assertEqual(len(self.shared.messages()), 1)

    def test_new_reply_is_added_without_republishing_original(self):
        a = self.import_one(self.a)
        b = self.import_one(self.a, mail(mid='<reply@example.invalid>', body='Nova informação', ref='<one@example.invalid>'), '2')
        publish_message(self.a, self.shared, a, 'user:1', {'10'})
        publish_message(self.a, self.shared, b, 'user:1', {'10'})
        self.assertEqual(len(self.shared.messages()), 2)

    def test_publish_requires_work_permission(self):
        mid = self.import_one(self.a)
        with self.assertRaises(PermissionError):
            publish_message(self.a, self.shared, mid, 'user:1', set())
        self.assertEqual(self.shared.messages(), [])

    def test_changed_content_does_not_silently_overwrite(self):
        a = self.import_one(self.a)
        b = self.import_one(self.b, mail(body='Dados divergentes'))
        publish_message(self.a, self.shared, a, 'user:1', {'10'})
        with self.assertRaises(ValueError):
            publish_message(self.b, self.shared, b, 'user:2', {'10'})
        self.assertEqual(len(self.shared.messages()), 1)

    def test_page_owner_cannot_change_with_session(self):
        fake_app = SimpleNamespace(storage=SimpleNamespace(user={'user_id': 2}))
        with patch('nicegui.app', fake_app), patch('services.auth_service.verificar_autenticacao', return_value=True):
            with self.assertRaises(PermissionError):
                authorize_user(1)


if __name__ == '__main__':
    unittest.main()
