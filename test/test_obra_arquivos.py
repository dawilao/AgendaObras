import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import contextlib
import io
import sqlite3
import tempfile
import unittest
from email.message import EmailMessage
from unittest import mock
from pathlib import Path

from comunicacoes.blobs import BlobStore
from comunicacoes.store import MailStore
from core.migrations import run_migrations
from db import Database
from db.obra_arquivos_repo import ObraArquivosRepository
from db.omie_repo import OmieRepository
from services import obra_arquivos as arquivos

FIN = {'id': 1, 'nome': 'Fin', 'sobrenome': 'Teste', 'financeiro': 1}
ADMIN = {'id': 2, 'nome': 'Adm', 'is_admin': True, 'financeiro': 0}
COORDENADOR = {'id': 7, 'nome': 'Coord', 'financeiro': 0}
OUTRO = {'id': 8, 'nome': 'Outro', 'financeiro': 0}
PDF = b'%PDF-1.7\n' + b'conteudo de teste ' * 400
XLSX = b'PK\x03\x04' + b'\x00' * 200


class ValidacaoTest(unittest.TestCase):
    def test_formatos_por_tipo(self):
        self.assertEqual(arquivos.validar_arquivo('cct', 'CCT 2026.pdf', PDF), 'CCT 2026.pdf')
        with self.assertRaises(ValueError):
            arquivos.validar_arquivo('cct', 'cct.xlsx', XLSX)          # CCT só PDF
        self.assertEqual(arquivos.validar_arquivo('orcamento', 'orc.XLSX', XLSX), 'orc.XLSX')
        self.assertEqual(arquivos.validar_arquivo('aditivo', 'a.csv', b'item;valor\n1;2\n'), 'a.csv')
        for tipo, nome, conteudo in (('orcamento', 'orc.docx', XLSX), ('outro', 'a.pdf', PDF),
                                     ('orcamento', 'falso.pdf', XLSX), ('orcamento', 'falso.xlsx', PDF),
                                     ('orcamento', 'vazio.pdf', b'')):
            with self.assertRaises(ValueError):
                arquivos.validar_arquivo(tipo, nome, conteudo)

    def test_limite_e_nome(self):
        with self.assertRaises(ValueError):
            arquivos.validar_arquivo('orcamento', 'grande.pdf', b'%PDF-' + b'0' * arquivos.LIMITE_BYTES)
        self.assertEqual(arquivos.validar_arquivo('cct', '..\\pasta/../cct.pdf', PDF), 'cct.pdf')
        self.assertTrue(arquivos.validar_arquivo('cct', 'x' * 300 + '.pdf', PDF).endswith('.pdf'))


class ArquivosObraTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        raiz = Path(self.tmp.name)
        self.path = str(raiz / 'obras.db')
        with contextlib.redirect_stdout(io.StringIO()):
            self.db = Database(self.path)
        with sqlite3.connect(self.path) as conn:
            for i, nome in ((1, 'ALMENARA'), (2, 'MEDINA')):
                conn.execute('INSERT INTO obras(id,nome_contrato,cliente,valor_contrato,coordenador_id) '
                             'VALUES(?,?,?,?,?)', (i, nome, 'CAIXA', 1000, 7))
        conn.close()
        self.repo = ObraArquivosRepository(self.path)
        self.store = BlobStore(raiz / 'uploads' / 'obras')
        self.obra = self.db.obter_obra(1)

    def enviar(self, tipo='orcamento', nome='orc.pdf', conteudo=PDF, user=FIN, obra=None):
        return arquivos.enviar(self.repo, obra or self.obra, tipo, nome, conteudo, user, store=self.store)

    def test_migracao_20_aplicada_e_idempotente(self):
        with contextlib.redirect_stdout(io.StringIO()):
            run_migrations(self.path)
        with sqlite3.connect(self.path) as conn:
            versoes = {r[0] for r in conn.execute('SELECT version FROM schema_migrations')}
        conn.close()
        self.assertIn(20, versoes)

    def test_versoes_e_sem_duplicar(self):
        primeiro = self.enviar(nome='orc v1.pdf')
        segundo = self.enviar(nome='orc v2.pdf', conteudo=PDF + b'revisao')
        self.assertEqual((primeiro['status'], primeiro['origem']), ('a_conferir', 'upload'))
        with self.assertRaises(ValueError):
            self.enviar(tipo='aditivo', nome='copia.pdf')          # mesmo conteúdo, mesmo na outra categoria
        grupos = arquivos.listar(self.repo, self.obra, COORDENADOR)
        self.assertEqual([a['id'] for a in grupos['orcamento']], [segundo['id'], primeiro['id']])
        self.assertEqual(grupos['aditivo'], [])
        self.assertEqual(sum(1 for _ in self.store.files()), 2)
        # O mesmo conteúdo pode ir para outra obra (um único arquivo no disco).
        self.enviar(obra=self.db.obter_obra(2))
        self.assertEqual(sum(1 for _ in self.store.files()), 2)
        acoes = [a['acao'] for a in OmieRepository(self.path).auditoria(1)]
        self.assertEqual(acoes, ['arquivo_enviado', 'arquivo_enviado'])

    def test_falha_no_disco_nao_deixa_registro(self):
        class DiscoCheio(BlobStore):
            def put(self, data, nested=False):
                raise OSError('disco cheio')
        with self.assertRaises(OSError):
            arquivos.enviar(self.repo, self.obra, 'orcamento', 'orc.pdf', PDF, FIN, store=DiscoCheio(self.store.root))
        self.assertEqual(self.repo.listar(1), [])
        self.assertEqual(OmieRepository(self.path).auditoria(1), [])
        self.assertEqual(self.enviar()['nome'], 'orc.pdf')       # depois, o mesmo arquivo entra normalmente

    def test_registro_repetido_nao_grava_no_disco(self):
        self.enviar()
        outro = BlobStore(Path(self.tmp.name) / 'outro')
        # Duas abas enviando o mesmo arquivo ao mesmo tempo: o banco recusa antes de gravar no disco.
        with mock.patch.object(self.repo, 'existe_sha', return_value=None), self.assertRaises(ValueError):
            arquivos.enviar(self.repo, self.obra, 'orcamento', 'copia.pdf', PDF, FIN, store=outro)
        self.assertEqual(list(outro.files()), [])

    def test_financeiro_e_coordenador_enviam(self):
        for user in (ADMIN, OUTRO, None):
            with self.assertRaises(PermissionError):
                self.enviar(user=user)
        self.assertEqual(self.repo.listar(1), [])
        self.assertEqual(self.enviar(user=COORDENADOR)['enviado_por_nome'], 'Coord')
        with self.assertRaises(PermissionError):     # coordenador de outra obra
            self.enviar(user=COORDENADOR, obra=dict(self.db.obter_obra(2), coordenador_id=99), conteudo=PDF + b'x')

    def test_baixar_confere_permissao_e_obra(self):
        arquivo = self.enviar()
        for user in (ADMIN, COORDENADOR, FIN):
            self.assertEqual(arquivos.baixar(self.repo, self.obra, arquivo['id'], user, self.store), ('orc.pdf', PDF))
        for user in (OUTRO, None):
            with self.assertRaises(PermissionError):
                arquivos.baixar(self.repo, self.obra, arquivo['id'], user, self.store)
            with self.assertRaises(PermissionError):
                arquivos.listar(self.repo, self.obra, user)
        with self.assertRaises(ValueError):          # arquivo da obra 1 pedido pela obra 2
            arquivos.baixar(self.repo, self.db.obter_obra(2), arquivo['id'], ADMIN, self.store)

    def test_excluir_obra_remove_registros(self):
        self.enviar()
        self.db.deletar_obra(1)
        self.assertEqual(self.repo.listar(1), [])

    # ----- anexar das Comunicações
    def historico(self):
        raiz = Path(self.tmp.name)
        shared = MailStore(raiz / 'mail' / 'compartilhado' / 'comunicacoes.db', raiz / 'mail_arquivos')
        for wid, nome in (('1', 'ALMENARA'), ('2', 'MEDINA')):
            shared.save_work(wid, nome, '', [nome], False, 'teste')
        ids = {}
        for n, (obra, nome, conteudo) in enumerate((('1', 'orcamento.pdf', PDF), ('1', 'foto.jpg', b'\xff\xd8\xff' + b'1' * 50),
                                                    ('2', 'outra.pdf', PDF + b'medina')), 1):
            msg = EmailMessage()
            msg['Subject'], msg['From'], msg['To'] = f'Assunto {n}', 'a@x.com', 'b@x.com'
            msg['Message-ID'] = f'<m{n}@x.com>'
            msg.set_content('corpo')
            maintype, subtype = ('application', 'pdf') if nome.endswith('.pdf') else ('image', 'jpeg')
            msg.add_attachment(conteudo, maintype=maintype, subtype=subtype, filename=nome)
            mid, _ = shared.import_message(msg.as_bytes(), ('caixa', 'INBOX', '1', str(n)))
            shared.review(mid, obra, 'teste', 'vínculo de teste')
            ids[nome] = shared.detail(mid)[1][0]['id']
        return shared, ids

    def test_anexar_das_comunicacoes(self):
        shared, ids = self.historico()
        anexos = arquivos.anexos_comunicacoes(self.repo, self.obra, FIN, shared=shared)
        self.assertEqual([a['nome'] for a in anexos], ['orcamento.pdf'])          # só desta obra e formatos aceitos
        self.assertFalse(anexos[0]['ja_na_obra'])
        arquivo = arquivos.anexar_de_comunicacoes(self.repo, self.obra, 'orcamento', ids['orcamento.pdf'], FIN,
                                                  shared=shared, store=self.store)
        self.assertEqual((arquivo['origem'], arquivo['origem_ref']), ('comunicacoes', str(ids['orcamento.pdf'])))
        self.assertEqual(arquivos.baixar(self.repo, self.obra, arquivo['id'], COORDENADOR, self.store)[1], PDF)
        self.assertTrue(arquivos.anexos_comunicacoes(self.repo, self.obra, FIN, shared=shared)[0]['ja_na_obra'])
        with self.assertRaises(ValueError):          # mesmo conteúdo de novo
            arquivos.anexar_de_comunicacoes(self.repo, self.obra, 'aditivo', ids['orcamento.pdf'], FIN,
                                            shared=shared, store=self.store)
        with self.assertRaises(ValueError):          # anexo de e-mail de outra obra
            arquivos.anexar_de_comunicacoes(self.repo, self.obra, 'orcamento', ids['outra.pdf'], FIN,
                                            shared=shared, store=self.store)
        self.assertIn('arquivo_anexado', [a['acao'] for a in OmieRepository(self.path).auditoria(1)])

    def test_anexar_pelo_financeiro_e_coordenador(self):
        shared, ids = self.historico()
        for user in (ADMIN, OUTRO):
            with self.assertRaises(PermissionError):
                arquivos.anexos_comunicacoes(self.repo, self.obra, user, shared=shared)
            with self.assertRaises(PermissionError):
                arquivos.anexar_de_comunicacoes(self.repo, self.obra, 'orcamento', ids['orcamento.pdf'], user,
                                                shared=shared, store=self.store)
        self.assertEqual(len(arquivos.anexos_comunicacoes(self.repo, self.obra, COORDENADOR, shared=shared)), 1)
        arquivo = arquivos.anexar_de_comunicacoes(self.repo, self.obra, 'orcamento', ids['orcamento.pdf'], COORDENADOR,
                                                  shared=shared, store=self.store)
        self.assertEqual(arquivo['enviado_por'], COORDENADOR['id'])

    # ----- corrigir e excluir
    def test_corrigir_nome_e_tipo(self):
        arquivo = self.enviar(nome='orcamento.pdf')
        self.assertTrue(arquivos.corrigir(self.repo, self.obra, arquivo['id'], 'Aditivo 01', 'aditivo', COORDENADOR))
        corrigido = self.repo.obter(arquivo['id'])
        self.assertEqual((corrigido['nome'], corrigido['tipo']), ('Aditivo 01.pdf', 'aditivo'))   # extensão mantida
        self.assertTrue(arquivos.corrigir(self.repo, self.obra, arquivo['id'], 'CCT 2026.PDF', 'cct', FIN))
        self.assertEqual(self.repo.obter(arquivo['id'])['nome'], 'CCT 2026.pdf')
        self.assertFalse(arquivos.corrigir(self.repo, self.obra, arquivo['id'], 'CCT 2026', 'cct', FIN))  # nada mudou
        self.assertEqual(arquivos.baixar(self.repo, self.obra, arquivo['id'], ADMIN, self.store), ('CCT 2026.pdf', PDF))
        planilha = self.enviar(nome='orc.xlsx', conteudo=XLSX)
        with self.assertRaises(ValueError):          # CCT só aceita PDF
            arquivos.corrigir(self.repo, self.obra, planilha['id'], 'orc', 'cct', FIN)
        with self.assertRaises(ValueError):          # nome vazio
            arquivos.corrigir(self.repo, self.obra, planilha['id'], '  .xlsx', 'orcamento', FIN)
        correcoes = [a for a in OmieRepository(self.path).auditoria(1) if a['acao'] == 'arquivo_corrigido']
        self.assertEqual(len(correcoes), 2)                  # tentativas recusadas não registram
        self.assertEqual(correcoes[0]['detalhe']['antes']['tipo'], 'aditivo')
        self.assertEqual(correcoes[0]['detalhe']['depois'], {'nome': 'CCT 2026.pdf', 'tipo': 'cct'})

    def test_excluir_e_reenviar(self):
        arquivo = self.enviar()
        self.assertTrue(arquivos.excluir(self.repo, self.obra, arquivo['id'], COORDENADOR))
        self.assertEqual(arquivos.listar(self.repo, self.obra, FIN)['orcamento'], [])
        with self.assertRaises(ValueError):
            arquivos.baixar(self.repo, self.obra, arquivo['id'], FIN, self.store)
        with self.assertRaises(ValueError):
            arquivos.corrigir(self.repo, self.obra, arquivo['id'], 'x', 'orcamento', FIN)
        with self.assertRaises(ValueError):
            arquivos.excluir(self.repo, self.obra, arquivo['id'], FIN)
        # O mesmo conteúdo enviado de novo volta, com o novo tipo e nome.
        de_volta = self.enviar(tipo='aditivo', nome='aditivo.pdf', user=FIN)
        self.assertEqual((de_volta['id'], de_volta['tipo'], de_volta['nome']), (arquivo['id'], 'aditivo', 'aditivo.pdf'))
        self.assertIsNone(de_volta['excluido_em'])
        acoes = [a['acao'] for a in OmieRepository(self.path).auditoria(1)]
        self.assertEqual(acoes, ['arquivo_enviado', 'arquivo_excluido', 'arquivo_enviado'])

    def test_corrigir_e_excluir_conferem_permissao_e_obra(self):
        arquivo = self.enviar()
        for user in (ADMIN, OUTRO, None):
            with self.assertRaises(PermissionError):
                arquivos.corrigir(self.repo, self.obra, arquivo['id'], 'x', 'orcamento', user)
            with self.assertRaises(PermissionError):
                arquivos.excluir(self.repo, self.obra, arquivo['id'], user)
        outra_obra = self.db.obter_obra(2)
        with self.assertRaises(ValueError):          # arquivo da obra 1 pela obra 2
            arquivos.excluir(self.repo, outra_obra, arquivo['id'], FIN)
        self.assertEqual(len(self.repo.listar(1)), 1)

    def test_migracao_21_idempotente(self):
        with contextlib.redirect_stdout(io.StringIO()):
            run_migrations(self.path)
        with sqlite3.connect(self.path) as conn:
            colunas = {r[1] for r in conn.execute('PRAGMA table_info(obra_arquivos)')}
            versoes = {r[0] for r in conn.execute('SELECT version FROM schema_migrations')}
        conn.close()
        self.assertIn(21, versoes)
        self.assertTrue({'excluido_por', 'excluido_por_nome', 'excluido_em'} <= colunas)

    def test_raiz_separada_das_comunicacoes(self):
        from comunicacoes.blobs import default_root
        self.assertNotEqual(arquivos.raiz_arquivos().resolve(), default_root().resolve())
        self.assertEqual(arquivos.raiz_arquivos().name, 'obras')


if __name__ == '__main__':
    unittest.main()
