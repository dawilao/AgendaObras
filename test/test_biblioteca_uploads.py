"""Uploads da Biblioteca: banco guarda só o nome do arquivo e arquivos ficam em uploads/biblioteca."""

import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db.biblioteca_repo as repo_mod
from db.biblioteca_repo import BibliotecaRepository, nome_arquivo


def _criar_arquivo(pasta, nome):
    os.makedirs(pasta, exist_ok=True)
    caminho = os.path.join(pasta, nome)
    with open(caminho, 'wb') as f:
        f.write(b'x')
    return caminho


class TestNomeArquivo(unittest.TestCase):

    def test_caminhos_windows_e_linux(self):
        self.assertEqual(nome_arquivo(r'C:\a\b\x.jpg'), 'x.jpg')
        self.assertEqual(nome_arquivo('/srv/app/uploads/biblioteca/x.jpg'), 'x.jpg')
        self.assertEqual(nome_arquivo(r'uploads\biblioteca\x.jpg'), 'x.jpg')
        self.assertEqual(nome_arquivo('x.jpg'), 'x.jpg')
        self.assertEqual(nome_arquivo(None), '')

    def test_pasta_padrao_na_raiz_do_projeto(self):
        raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with mock.patch.dict(os.environ, {'AGENDA_OBRAS_BIBLIOTECA_UPLOADS_PATH': ''}):
            self.assertEqual(repo_mod._resolver_pasta_uploads(), os.path.join(raiz, 'uploads', 'biblioteca'))


class TestRepositorioUploads(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pasta = os.path.join(self.tmp.name, 'uploads', 'biblioteca')
        os.makedirs(self.pasta)
        self.db_path = os.path.join(self.tmp.name, 'dados', 'biblioteca.db')
        os.makedirs(os.path.dirname(self.db_path))
        patcher = mock.patch.object(repo_mod, 'PASTA_UPLOADS', self.pasta)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.repo = BibliotecaRepository(self.db_path)

    def _linha(self, card_id):
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute('SELECT imagem_path, pdf_path FROM cards WHERE id = ?', (card_id,)).fetchone()
        finally:
            conn.close()

    def test_criar_card_grava_so_o_nome(self):
        img = _criar_arquivo(self.pasta, 'a.jpg')
        pdf = _criar_arquivo(self.pasta, 'pdf_a.pdf')
        cid = self.repo.criar_card('T', '', img, 'U', pdf_path=pdf, pdf_nome_original='orig.pdf')
        self.assertEqual(self._linha(cid), ('a.jpg', 'pdf_a.pdf'))

    def test_editar_troca_e_remove_arquivos(self):
        _criar_arquivo(self.pasta, 'velha.jpg')
        _criar_arquivo(self.pasta, 'velho.pdf')
        cid = self.repo.criar_card('T', '', 'velha.jpg', 'U', pdf_path='velho.pdf')
        nova = _criar_arquivo(self.pasta, 'nova.jpg')

        self.repo.editar_card(cid, imagem_path=nova, pdf_path='')

        self.assertEqual(self._linha(cid), ('nova.jpg', None))
        self.assertFalse(os.path.exists(os.path.join(self.pasta, 'velha.jpg')))
        self.assertFalse(os.path.exists(os.path.join(self.pasta, 'velho.pdf')))
        self.assertTrue(os.path.exists(nova))

    def test_editar_sem_trocar_mantem_arquivos(self):
        img = _criar_arquivo(self.pasta, 'a.jpg')
        cid = self.repo.criar_card('T', '', 'a.jpg', 'U')
        self.repo.editar_card(cid, titulo='Novo')
        self.assertEqual(self._linha(cid)[0], 'a.jpg')
        self.assertTrue(os.path.exists(img))

    def test_excluir_remove_arquivo_mesmo_com_caminho_completo(self):
        img = _criar_arquivo(self.pasta, 'b.jpg')
        cid = self.repo.criar_card('T', '', None, 'U')
        conn = sqlite3.connect(self.db_path)
        conn.execute('UPDATE cards SET imagem_path = ? WHERE id = ?', (r'C:\qualquer\uploads\biblioteca\b.jpg', cid))
        conn.commit()
        conn.close()

        self.repo.excluir_card(cid)
        self.assertFalse(os.path.exists(img))


if __name__ == '__main__':
    unittest.main()
