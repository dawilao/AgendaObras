"""Anexos das Comunicações em disco: uma cópia por conteúdo, com verificação na leitura."""

import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from comunicacoes.blobs import BlobStore


class BlobStoreTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.blobs = BlobStore(Path(self.tmp.name) / 'arquivos')

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

    def test_missing_or_changed_file_rejected(self):
        sha, _ = self.blobs.put(b'original')
        self.blobs.path(sha).write_bytes(b'alterado')
        with self.assertRaises(ValueError):
            self.blobs.get(sha)
        self.blobs.path(sha).unlink()
        with self.assertRaises(ValueError):
            self.blobs.get(sha)

    def test_invalid_identifier_rejected(self):
        for bad in ('../../etc/passwd', 'ABC', 'g' * 64):
            with self.assertRaises(ValueError):
                self.blobs.path(bad)


if __name__ == '__main__':
    unittest.main()
