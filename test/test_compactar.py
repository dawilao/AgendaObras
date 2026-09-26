"""Compactação dos anexos já gravados, limpeza de órfãos e relatório de espaço."""

import hashlib
import lzma
import os
import sys
import tempfile
import time
import unittest
import zipfile
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from comunicacoes.blobs import BlobStore
from comunicacoes.compactar import compact
from comunicacoes.espaco import ORPHAN_GRACE, orphans, remove, report
from comunicacoes.store import MailStore
from test_blobs import TEXTO, make_zip


def message(subject, attachments):
    msg = EmailMessage()
    msg['Subject'], msg['Message-ID'] = subject, f'<{subject}@example.invalid>'
    msg['From'], msg['To'] = 'from@example.invalid', 'to@example.invalid'
    msg.set_content('Segue.')
    for name, data in attachments:
        msg.add_attachment(data, maintype='application', subtype='octet-stream', filename=name)
    return msg.as_bytes()


class CompactarTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bancos = Path(self.tmp.name) / 'usuarios'
        self.arquivos = Path(self.tmp.name) / 'arquivos'
        self.store = MailStore(self.bancos / '1' / 'comunicacoes.db', self.arquivos)
        # Anexos gravados como antes desta versão: todos no formato original.
        self.store.blobs.compact = False
        prancha = os.urandom(300_000)
        self.store.import_message(message('R00', [
            ('nfe.xml', TEXTO),
            ('plantas_R00.zip', make_zip(('P01.pdf', prancha, zipfile.ZIP_DEFLATED),
                                         ('P02.pdf', os.urandom(100_000), zipfile.ZIP_DEFLATED)))]),
            ('caixa', 'INBOX', '1', '1'))
        self.store.import_message(message('R01', [
            ('plantas_R01.zip', make_zip(('P01.pdf', prancha, zipfile.ZIP_DEFLATED),
                                         ('P02.pdf', os.urandom(100_000), zipfile.ZIP_DEFLATED)))]),
            ('caixa', 'INBOX', '1', '2'))
        self.blobs = BlobStore(self.arquivos)
        self.ids = [a['id'] for mid in (1, 2) for a in self.store.detail(mid)[1]]
        self.payloads = {aid: self.store.attachment(aid)['payload'] for aid in self.ids}

    def snapshot(self):
        return sorted((p.name, p.stat().st_size) for _, _, p in self.blobs.files())

    def orphan(self, age):
        sha, _ = BlobStore(self.arquivos, compact=False).put(os.urandom(1000))
        old = time.time() - age
        os.utime(self.blobs.path(sha), (old, old))
        return self.blobs.path(sha)

    def test_simulation_changes_nothing(self):
        before = self.snapshot()
        text, failures = compact(self.bancos, self.arquivos, apply=False, remove_orphans=True)
        self.assertEqual(failures, [])
        self.assertIn('Simulação', text)
        self.assertIn('zip 2', text)
        self.assertIn('lzma 1', text)
        self.assertEqual(self.snapshot(), before)

    def test_apply_compacts_and_keeps_bytes(self):
        before = sum(size for _, size in self.snapshot())
        text, failures = compact(self.bancos, self.arquivos, apply=True)
        self.assertEqual(failures, [])
        suffixes = sorted(suffix for _, suffix, _ in self.blobs.files())
        self.assertEqual(suffixes.count('.zipm'), 2)
        self.assertEqual(suffixes.count('.xz'), 1)
        # A prancha repetida entre as revisões passa a ocupar espaço uma vez só.
        self.assertLess(sum(size for _, size in self.snapshot()), before - 290_000)
        self.assertEqual({aid: self.store.attachment(aid)['payload'] for aid in self.ids}, self.payloads)
        again, _ = compact(self.bancos, self.arquivos, apply=True)
        result = next(line for line in again.splitlines() if line.startswith('Resultado'))
        self.assertNotIn('zip', result)
        self.assertNotIn('lzma', result)

    def test_old_orphans_removed_recent_kept(self):
        old, recent = self.orphan(3 * 24 * 3600), self.orphan(60)
        compact(self.bancos, self.arquivos, apply=True, remove_orphans=True)
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())
        self.assertEqual({aid: self.store.attachment(aid)['payload'] for aid in self.ids}, self.payloads)

    def test_unreadable_manifest_blocks_orphan_cleanup(self):
        compact(self.bancos, self.arquivos, apply=True)
        manifest = next(p for _, suffix, p in self.blobs.files() if suffix == '.zipm')
        manifest.write_bytes(b'lixo')
        before, old = self.snapshot(), self.orphan(3 * 24 * 3600)
        _, failures = compact(self.bancos, self.arquivos, apply=True, remove_orphans=True)
        self.assertEqual(len(failures), 1)
        self.assertIn('manifesto ilegível', failures[0])
        self.assertTrue(old.exists())
        self.assertTrue(set(before) <= set(self.snapshot()))
        self.assertIn('Órfãos: não verificados', report(self.bancos, self.arquivos))

    def test_too_many_orphans_refused_unless_forced(self):
        lost = [self.orphan(3 * 24 * 3600) for _ in range(12)]
        _, failures = compact(self.bancos, self.arquivos, apply=True, remove_orphans=True)
        self.assertEqual(len(failures), 1)
        self.assertIn('--forcar', failures[0])
        self.assertTrue(all(path.exists() for path in lost))
        self.assertIn('órfãos demais', report(self.bancos, self.arquivos))
        _, failures = compact(self.bancos, self.arquivos, apply=True, remove_orphans=True, force=True)
        self.assertEqual(failures, [])
        self.assertFalse(any(path.exists() for path in lost))
        self.assertEqual({aid: self.store.attachment(aid)['payload'] for aid in self.ids}, self.payloads)

    def test_orphan_reused_after_scan_is_kept(self):
        old = self.orphan(3 * 24 * 3600)
        now = time.time()
        in_use = {sha for sha, _, path in self.blobs.files() if path != old}
        lost = orphans(self.blobs, in_use, now)
        self.assertEqual(lost, [old])
        os.utime(old)  # Mesmo conteúdo chegou de novo por outro e-mail.
        self.assertEqual(remove(lost, now - ORPHAN_GRACE), 0)
        self.assertTrue(old.exists())

    def test_output_shows_folders(self):
        text, _ = compact(self.bancos, self.arquivos)
        for output in (text, report(self.bancos, self.arquivos)):
            self.assertIn(f'Bancos em: {self.bancos.resolve()}', output)
            self.assertIn(f'Anexos em: {self.arquivos.resolve()}', output)

    def test_report_counts_each_attachment_once(self):
        sha = hashlib.sha256(TEXTO).hexdigest()
        self.blobs.path(sha, '.xz').write_bytes(lzma.compress(TEXTO))  # Compactação interrompida.
        self.assertIn('  outros       1 arquivos', report(self.bancos, self.arquivos))

    def test_orphans_untouched_without_databases(self):
        old = self.orphan(3 * 24 * 3600)
        _, failures = compact(Path(self.tmp.name) / 'vazio', self.arquivos, apply=True, remove_orphans=True)
        self.assertEqual(len(failures), 1)
        self.assertTrue(old.exists())
        self.assertEqual({aid: self.store.attachment(aid)['payload'] for aid in self.ids}, self.payloads)

    def test_orphans_untouched_with_legacy_database(self):
        import sqlite3
        from contextlib import closing
        legacy = self.bancos / '2' / 'comunicacoes.db'
        legacy.parent.mkdir()
        with closing(sqlite3.connect(legacy)) as db:
            db.execute('CREATE TABLE attachments (id INTEGER PRIMARY KEY, payload BLOB)')
        old = self.orphan(3 * 24 * 3600)
        _, failures = compact(self.bancos, self.arquivos, apply=True, remove_orphans=True)
        self.assertEqual(len(failures), 1)
        self.assertTrue(old.exists())
        text = report(self.bancos, self.arquivos)
        self.assertIn('formato antigo', text)
        self.assertIn('Órfãos: não verificados', text)

    def test_report_shows_kinds_and_savings(self):
        self.orphan(3 * 24 * 3600)
        text = report(self.bancos, self.arquivos)
        self.assertIn('Bancos: 1  |  anexos: 3', text)
        self.assertIn('zip ', text)
        self.assertIn('Órfãos com mais de 24 h: 1', text)
        self.assertNotIn('ZIPs 0.0 MB', text)
        compact(self.bancos, self.arquivos, apply=True)
        self.assertNotIn('ATENÇÃO', report(self.bancos, self.arquivos))


if __name__ == '__main__':
    unittest.main()
