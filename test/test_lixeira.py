"""Lixeira dos arquivos do Histórico da equipe: marcar em todas as caixas, restaurar e excluir de vez."""

import hashlib
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from comunicacoes.espaco import attachment_rows
from comunicacoes.lixeira import TRASH_DAYS, Lixeira
from comunicacoes.publishing import publication_fingerprint, publish_message
from comunicacoes.store import MailStore

PLANTA = os.urandom(50_000)
OUTRO = os.urandom(20_000)


def mail(mid='<planta@example.invalid>', files=(('planta.pdf', PLANTA), ('memorial.pdf', OUTRO))):
    msg = EmailMessage()
    msg['Subject'], msg['Message-ID'] = 'MEDINA IC 03738/2026 projeto', mid
    msg['From'], msg['To'] = 'from@example.invalid', 'to@example.invalid'
    msg['Date'] = 'Wed, 23 Sep 2026 10:00:00 -0300'
    msg.set_content('Segue o projeto.')
    for name, data in files:
        msg.add_attachment(data, maintype='application', subtype='pdf', filename=name)
    return msg.as_bytes()


class LixeiraTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        files = root / 'arquivos'
        self.shared = MailStore(root / 'compartilhado' / 'comunicacoes.db', files)
        self.users = [MailStore(root / uid / 'comunicacoes.db', files) for uid in ('1', '2')]
        for number, store in enumerate(self.users, 1):
            store.save_work('1', 'Medina', '03738/2026', ['MEDINA'], True, 'admin')
            mid, _ = store.import_message(mail(), ('caixa', 'INBOX', '1', '1'))
            publish_message(store, self.shared, mid, f'usuario:{number}', {'1'})
        self.trash = Lixeira(self.shared, lambda: self.users)
        self.sha = hashlib.sha256(PLANTA).hexdigest()
        self.public_id = self.shared.messages()[0]['id']

    def names(self, store):
        return sorted(a['name'] for row in store.conversation_rows() for a in row['attachments'])

    def age_files(self):
        old = time.time() - 3 * 24 * 3600
        for path in self.shared.blobs.root.rglob('*'):
            if path.is_file():
                os.utime(path, (old, old))

    def test_send_hides_file_in_every_box_and_keeps_publication_identity(self):
        before = {id(s): publication_fingerprint(s.detail(1)[0], s.fingerprint_attachments(1)) for s in self.users}
        self.trash.send([self.public_id], self.sha, 'usuario:9', 'Admin')
        for store in (self.shared, *self.users):
            self.assertEqual(self.names(store), ['memorial.pdf'])
            self.assertEqual([a['name'] for a in store.detail(1)[1]], ['memorial.pdf'])
            self.assertEqual(store.messages()[0]['attachment_count'], 1)
        trashed = next(a for a in self.shared.fingerprint_attachments(self.public_id) if a['sha256'] == self.sha)
        with self.assertRaises(ValueError):
            self.shared.attachment(trashed['id'])
        # A mensagem pessoal continua sendo reconhecida como já publicada.
        published = self.shared.published_works()
        for store in self.users:
            fingerprint = publication_fingerprint(store.detail(1)[0], store.fingerprint_attachments(1))
            self.assertEqual(fingerprint, before[id(store)])
            self.assertEqual(published[fingerprint], '1')
        item, = self.trash.items()
        self.assertEqual((item['names'], item['days_left'], item['deleted_by_name']), (['planta.pdf'], TRASH_DAYS, 'Admin'))

    def test_restore_brings_file_back_with_same_ids(self):
        ids = [a['id'] for a in self.shared.detail(self.public_id)[1]]
        trash_id = self.trash.send([self.public_id], self.sha, 'usuario:9')
        self.trash.restore(trash_id, 'usuario:9')
        self.assertEqual([a['id'] for a in self.shared.detail(self.public_id)[1]], ids)
        for store in (self.shared, *self.users):
            self.assertEqual(self.names(store), ['memorial.pdf', 'planta.pdf'])
        self.assertEqual(self.trash.items(), [])
        with self.assertRaises(ValueError):
            self.trash.purge(trash_id, 'usuario:9')
        actions = [a['action'] for a in self.shared.detail(self.public_id)[2]]
        self.assertIn('lixeira', actions)
        self.assertIn('restauracao', actions)

    def test_purge_frees_disk_when_no_one_else_uses_the_file(self):
        self.age_files()
        trash_id = self.trash.send([self.public_id], self.sha, 'usuario:9')
        self.assertTrue(self.shared.blobs.exists(self.sha))
        self.assertEqual(self.trash.purge(trash_id, 'usuario:9'), 1)
        self.assertFalse(self.shared.blobs.exists(self.sha))
        self.assertTrue(self.shared.blobs.exists(hashlib.sha256(OUTRO).hexdigest()))
        rows, _ = attachment_rows([Path(s.path) for s in (self.shared, *self.users)])
        self.assertNotIn(self.sha, {sha for sha, _ in rows})
        with self.assertRaises(ValueError):
            self.trash.restore(trash_id, 'usuario:9')
        self.assertEqual(self.names(self.shared), ['memorial.pdf'])

    def test_purge_keeps_content_used_by_another_email(self):
        self.users[0].import_message(mail('<outro@example.invalid>', (('copia.pdf', PLANTA),)),
                                     ('caixa', 'INBOX', '1', '2'))
        self.age_files()
        trash_id = self.trash.send([self.public_id], self.sha, 'usuario:9')
        self.assertEqual(self.trash.purge(trash_id, 'usuario:9'), 0)
        self.assertTrue(self.shared.blobs.exists(self.sha))

    def test_recent_content_is_freed_on_a_later_run(self):
        trash_id = self.trash.send([self.public_id], self.sha, 'usuario:9')
        self.assertEqual(self.trash.purge(trash_id, 'usuario:9'), 0)  # Gravado agora: carência de 24 h.
        self.assertTrue(self.shared.blobs.exists(self.sha))
        self.age_files()
        self.assertEqual(self.trash.purge_expired(), (0, 1))
        self.assertFalse(self.shared.blobs.exists(self.sha))

    def test_expired_items_purged_by_daily_routine(self):
        self.trash.send([self.public_id], self.sha, 'usuario:9')
        self.assertEqual(self.trash.purge_expired()[0], 0)
        later = datetime.now(timezone.utc) + timedelta(days=TRASH_DAYS, minutes=1)
        self.assertEqual(self.trash.purge_expired(later)[0], 1)
        self.assertEqual(self.trash.items(), [])
        purged = [a for a in self.shared.fingerprint_attachments(self.public_id) if a['sha256'] == self.sha]
        self.assertEqual(len(purged), 1)  # A linha fica; só o conteúdo pode sair do disco.

    def test_insurance_file_is_protected(self):
        with self.assertRaises(ValueError):
            self.trash.send([self.public_id], self.sha, 'usuario:9', protected={self.sha})
        self.assertEqual(self.names(self.shared), ['memorial.pdf', 'planta.pdf'])
        self.assertEqual(self.trash.items(), [])

    def test_file_already_trashed_is_rejected(self):
        self.trash.send([self.public_id], self.sha, 'usuario:9')
        with self.assertRaises(ValueError):
            self.trash.send([self.public_id], self.sha, 'usuario:9')

    def legacy_store(self):
        import sqlite3
        from contextlib import closing
        path = Path(self.tmp.name) / '3' / 'comunicacoes.db'
        path.parent.mkdir()
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE attachments (id INTEGER PRIMARY KEY, message_id INTEGER, name TEXT, '
                       'mime TEXT, payload BLOB)')
        return MailStore(path, Path(self.tmp.name) / 'arquivos')

    def test_legacy_personal_box_is_skipped(self):
        # Caixa no formato antigo no meio da lista: as demais são marcadas normalmente.
        stores = [self.users[0], self.legacy_store(), self.users[1]]
        trash = Lixeira(self.shared, lambda: stores)
        trash_id = trash.send([self.public_id], self.sha, 'usuario:9')
        for store in (self.shared, *self.users):
            self.assertEqual(self.names(store), ['memorial.pdf'])
        # Enquanto houver banco antigo, o disco não é liberado, e o motivo fica registrado.
        self.age_files()
        self.assertEqual(trash.purge(trash_id, 'usuario:9'), 0)
        self.assertIn('Disco não liberado', trash.problem)
        self.assertTrue(self.shared.blobs.exists(self.sha))

    def test_unreadable_personal_box_changes_nothing(self):
        import sqlite3

        class Broken:
            path = 'caixa-quebrada.db'
            def connect(self):
                raise sqlite3.OperationalError('disk I/O error')

        trash = Lixeira(self.shared, lambda: [self.users[0], Broken()])
        with self.assertRaises(ValueError) as ctx:
            trash.send([self.public_id], self.sha, 'usuario:9')
        self.assertIn('Nada foi excluído', str(ctx.exception))
        self.assertEqual(trash.items(), [])
        for store in (self.shared, *self.users):
            self.assertEqual(self.names(store), ['memorial.pdf', 'planta.pdf'])

    def test_interrupted_purge_is_completed_by_daily_routine(self):
        self.age_files()
        trash_id = self.trash.send([self.public_id], self.sha, 'usuario:9')
        self.trash._close(trash_id, 'usuario:9', 'excluido')  # Caiu antes de marcar as caixas.
        self.assertTrue(self.shared.blobs.exists(self.sha))
        self.assertEqual(self.trash.purge_expired(), (0, 1))
        self.assertFalse(self.shared.blobs.exists(self.sha))
        self.assertEqual(self.trash.purge_expired(), (0, 0))  # Nada mais a tentar.
        self.assertIsNone(self.trash.problem)

    def test_restore_checks_item_still_in_trash(self):
        trash_id = self.trash.send([self.public_id], self.sha, 'usuario:9')
        self.assertEqual(self.trash.item(trash_id)['obra_id'], '1')
        self.trash.restore(trash_id, 'usuario:9')
        with self.assertRaises(ValueError):
            self.trash.item(trash_id)

    def test_existing_database_gains_trash_columns(self):
        import sqlite3
        from contextlib import closing
        path = Path(self.tmp.name) / 'antigo' / 'comunicacoes.db'
        path.parent.mkdir()
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('''CREATE TABLE attachments (id INTEGER PRIMARY KEY, message_id INTEGER,
                          name TEXT, mime TEXT, sha256 TEXT NOT NULL, size INTEGER NOT NULL)''')
            db.execute("INSERT INTO attachments VALUES(1, 1, 'a.pdf', 'application/pdf', ?, 3)", (self.sha,))
        rows, unreadable = attachment_rows([path])  # Antes da migração também é legível.
        self.assertEqual((len(rows), unreadable), (1, []))
        store = MailStore(path, Path(self.tmp.name) / 'arquivos')
        with store.connect() as db:
            row = dict(db.execute('SELECT * FROM attachments').fetchone())
        self.assertEqual((row['name'], row['trash_id'], row['trashed_at'], row['purged_at']), ('a.pdf', None, None, None))

    def test_publishing_later_keeps_file_in_trash(self):
        root = Path(self.tmp.name)
        fresh = MailStore(root / 'novo' / 'comunicacoes.db', root / 'arquivos')
        user = self.users[0]
        with user.connect() as db:
            db.execute("UPDATE attachments SET trash_id=1, trashed_at='2026-09-01T00:00:00+00:00' WHERE sha256=?",
                       (self.sha,))
        public_id, _ = publish_message(user, fresh, 1, 'usuario:1', {'1'})
        self.assertEqual([a['name'] for a in fresh.detail(public_id)[1]], ['memorial.pdf'])


if __name__ == '__main__':
    unittest.main()
