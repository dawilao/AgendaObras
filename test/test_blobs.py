"""Anexos das Comunicações em disco: uma cópia por conteúdo, com verificação na leitura."""

import hashlib
import io
import json
import lzma
import os
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from comunicacoes.blobs import BlobStore

# Conteúdo que o lzma encolhe bem, como XML de NF-e.
TEXTO = b''.join(b'<det nItem="%d"><prod><xProd>CIMENTO CP-II</xProd></prod></det>\n' % i for i in range(2000))


def make_zip(*members):
    """ZIP determinístico: (nome, conteúdo, método) com data fixa."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, data, method in members:
            archive.writestr(zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)), data, compress_type=method)
    return buffer.getvalue()


class BlobStoreTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.blobs = BlobStore(Path(self.tmp.name) / 'arquivos', compact=True)

    def files(self):
        return [p for p in self.blobs.root.rglob('*') if p.is_file()]

    def test_same_content_stored_once(self):
        first = self.blobs.put(b'apolice')
        second = self.blobs.put(b'apolice')
        self.assertEqual(first, second)
        self.assertEqual(first, (hashlib.sha256(b'apolice').hexdigest(), 7))
        self.assertEqual(len(self.files()), 1)
        self.assertEqual(self.blobs.get(first[0]), b'apolice')

    def test_path_uses_hash_prefix_and_no_temp_left(self):
        sha, _ = self.blobs.put(b'boleto')
        self.assertEqual(self.blobs.path(sha), self.blobs.root / sha[:2] / sha)
        self.assertEqual(self.files(), [self.blobs.path(sha)])

    def disk(self):
        return sum(p.stat().st_size for p in self.files())

    def test_missing_or_changed_file_rejected(self):
        sha, _ = self.blobs.put(b'original')
        self.blobs.path(sha).write_bytes(b'alterado')
        with self.assertRaises(ValueError):
            self.blobs.get(sha)
        self.blobs.path(sha).unlink()
        with self.assertRaises(ValueError):
            self.blobs.get(sha)

    def test_changed_compressed_file_rejected(self):
        sha, _ = self.blobs.put(TEXTO)
        self.blobs.path(sha, '.xz').write_bytes(lzma.compress(TEXTO + b'x'))
        with self.assertRaises(ValueError):
            self.blobs.get(sha)
        self.blobs.path(sha, '.xz').write_bytes(b'lixo')
        with self.assertRaises(ValueError):
            self.blobs.get(sha)

    def test_compressible_content_stored_as_xz(self):
        sha, size = self.blobs.put(TEXTO)
        self.assertEqual((sha, size), (hashlib.sha256(TEXTO).hexdigest(), len(TEXTO)))
        self.assertEqual(self.files(), [self.blobs.path(sha, '.xz')])
        self.assertLess(self.disk(), len(TEXTO) / 5)
        self.assertEqual(self.blobs.get(sha), TEXTO)
        self.assertEqual(self.blobs.put(TEXTO), (sha, size))
        self.assertEqual(len(self.files()), 1)

    def test_packed_or_random_content_kept_original(self):
        for data in (os.urandom(50_000), b'\xff\xd8\xff\xe0' + TEXTO, b'AC1032' + TEXTO):
            sha, _ = self.blobs.put(data)
            self.assertTrue(self.blobs.path(sha).exists())
            self.assertEqual(self.blobs.get(sha), data)

    def test_mostly_compressed_file_not_worth_xz(self):
        # Como um PDF do AutoCAD: cabeçalho em texto e o resto já comprimido.
        data = b'%PDF-1.7\n' + TEXTO + os.urandom(1_500_000)
        sha, _ = self.blobs.put(data)
        self.assertEqual(self.files(), [self.blobs.path(sha)])

    def test_reused_content_gets_fresh_date(self):
        sha, _ = self.blobs.put(TEXTO)
        old = time.time() - 3 * 24 * 3600
        os.utime(self.blobs.path(sha, '.xz'), (old, old))
        self.blobs.put(TEXTO)
        self.assertGreater(self.blobs.path(sha, '.xz').stat().st_mtime, old + 3600)

    def test_disabled_keeps_original(self):
        blobs = BlobStore(self.blobs.root, compact=False)
        sha, _ = blobs.put(TEXTO)
        self.assertEqual(self.files(), [blobs.path(sha)])

    def test_zip_revisions_share_unchanged_members(self):
        prancha1, prancha2, prancha2_r1 = os.urandom(300_000), os.urandom(100_000), os.urandom(100_000)
        r00 = make_zip(('P01.pdf', prancha1, zipfile.ZIP_DEFLATED), ('P02.pdf', prancha2, zipfile.ZIP_DEFLATED),
                       ('leia.txt', b'R00', zipfile.ZIP_DEFLATED))
        r01 = make_zip(('P01.pdf', prancha1, zipfile.ZIP_DEFLATED), ('P02.pdf', prancha2_r1, zipfile.ZIP_DEFLATED),
                       ('leia.txt', b'R01', zipfile.ZIP_DEFLATED))
        first, _ = self.blobs.put(r00)
        after_first = self.disk()
        second, _ = self.blobs.put(r01)
        self.assertTrue(self.blobs.path(first, '.zipm').exists())
        self.assertEqual(self.blobs.get(first), r00)
        self.assertEqual(self.blobs.get(second), r01)
        # A segunda revisão só acrescenta o manifesto e a prancha que mudou.
        self.assertLess(self.disk() - after_first, 110_000)
        self.assertEqual(len(self.files()), 5)

    def test_stored_member_shares_loose_file_and_nested_zip(self):
        loose = os.urandom(100_000)
        inner = make_zip(('P01.pdf', os.urandom(300_000), zipfile.ZIP_STORED))
        self.blobs.put(loose)
        self.blobs.put(inner)
        count = len(self.files())
        outer = make_zip(('solta.pdf', loose, zipfile.ZIP_STORED), ('interno.zip', inner, zipfile.ZIP_STORED),
                         ('novo.pdf', os.urandom(80_000), zipfile.ZIP_STORED))
        sha, _ = self.blobs.put(outer)
        self.assertEqual(len(self.files()), count + 2)  # manifesto novo + só novo.pdf
        self.assertEqual(self.blobs.get(sha), outer)

    def test_malformed_zip_kept_original(self):
        data = b'PK' + b'x' * 300_000
        sha, _ = self.blobs.put(data)
        self.assertEqual(self.files(), [self.blobs.path(sha)])
        self.assertEqual(self.blobs.get(sha), data)

    def test_changed_zip_member_or_forged_cycle_rejected(self):
        data = make_zip(('P01.pdf', os.urandom(300_000), zipfile.ZIP_DEFLATED))
        sha, _ = self.blobs.put(data)
        member = next(p for p in self.files() if p.name != sha + '.zipm')
        member.write_bytes(b'alterado')
        with self.assertRaises(ValueError):
            self.blobs.get(sha)
        cycle = {'v': 1, 'parts': [['b', sha, len(data)]]}
        self.blobs.path(sha, '.zipm').write_bytes(lzma.compress(json.dumps(cycle).encode()))
        with self.assertRaises(ValueError):
            self.blobs.get(sha)

    def test_compact_existing_replaces_original_after_check(self):
        blobs = BlobStore(self.blobs.root, compact=False)
        text, _ = blobs.put(TEXTO)
        zipped, _ = blobs.put(make_zip(('P01.pdf', os.urandom(300_000), zipfile.ZIP_DEFLATED)))
        random, _ = blobs.put(os.urandom(10_000))
        before = {sha: self.blobs.get(sha) for sha in (text, zipped, random)}
        self.assertEqual([self.blobs.compact_existing(sha) for sha in before], ['.xz', '.zipm', ''])
        self.assertFalse(self.blobs.path(text).exists())
        self.assertTrue(self.blobs.path(text, '.xz').exists())
        self.assertFalse(self.blobs.path(zipped).exists())
        self.assertTrue(self.blobs.path(random).exists())
        self.assertEqual({sha: self.blobs.get(sha) for sha in before}, before)

    def test_invalid_identifier_rejected(self):
        for bad in ('../../etc/passwd', 'ABC', 'g' * 64):
            with self.assertRaises(ValueError):
                self.blobs.path(bad)


if __name__ == '__main__':
    unittest.main()
