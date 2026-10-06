"""Arquivos da obra (CCT, orçamento e aditivos): registro das versões no banco de obras.

O conteúdo fica no disco, endereçado pelo sha256 (services.obra_arquivos). Cada envio é uma versão
nova, e o mesmo conteúdo não é registrado duas vezes na obra. Excluir só tira o arquivo da lista
(o registro e o conteúdo ficam); enviar de novo o mesmo conteúdo o traz de volta.
"""
import sqlite3
from typing import Callable, Dict, List, Optional

from db.connection import BaseRepository
from db.omie_repo import agora, autor, registrar_auditoria

TIPOS = {'cct': 'CCT', 'orcamento': 'Orçamento', 'aditivo': 'Aditivos'}
ORIGENS = ('upload', 'comunicacoes')


def criar_schema(conn):
    conn.execute('SAVEPOINT obra_arquivos_schema')
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS obra_arquivos (
            id INTEGER PRIMARY KEY, obra_id INTEGER NOT NULL,
            tipo TEXT NOT NULL CHECK(tipo IN ('cct','orcamento','aditivo')),
            nome TEXT NOT NULL, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL,
            origem TEXT NOT NULL CHECK(origem IN ('upload','comunicacoes')), origem_ref TEXT,
            enviado_por INTEGER, enviado_por_nome TEXT, enviado_em TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'a_conferir' CHECK(status IN ('a_conferir')),
            UNIQUE(obra_id, sha256))""")
        conn.execute('CREATE INDEX IF NOT EXISTS idx_obra_arquivos_obra ON obra_arquivos(obra_id, tipo, id)')
        # Auditoria compartilhada com o financeiro Omie (criada aqui se esta migração vier antes).
        conn.execute("""CREATE TABLE IF NOT EXISTS financeiro_auditoria (
            id INTEGER PRIMARY KEY, quando TEXT NOT NULL, usuario_id INTEGER, usuario_nome TEXT,
            acao TEXT NOT NULL, obra_id INTEGER, detalhe_json TEXT)""")
        conn.execute('RELEASE SAVEPOINT obra_arquivos_schema')
    except Exception:
        conn.execute('ROLLBACK TO SAVEPOINT obra_arquivos_schema')
        conn.execute('RELEASE SAVEPOINT obra_arquivos_schema')
        raise


def criar_colunas_exclusao(conn):
    """Migração 21: exclusão pela tela (o registro fica, marcado como excluído)."""
    colunas = {r[1] for r in conn.execute('PRAGMA table_info(obra_arquivos)')}
    for coluna in ('excluido_por INTEGER', 'excluido_por_nome TEXT', 'excluido_em TEXT'):
        if coluna.split()[0] not in colunas:
            conn.execute(f'ALTER TABLE obra_arquivos ADD COLUMN {coluna}')


class ObraArquivosRepository(BaseRepository):

    def registrar(self, obra_id: int, tipo: str, nome: str, sha256: str, tamanho: int, origem: str,
                  user, origem_ref: Optional[str] = None, antes_do_commit: Optional[Callable] = None) -> int:
        """Registra a versão. antes_do_commit (gravar o conteúdo no disco) roda dentro da transação:
        se falhar, nada fica registrado. O mesmo conteúdo excluído antes volta como envio novo."""
        if tipo not in TIPOS:
            raise ValueError('Tipo de documento inválido.')
        if origem not in ORIGENS:
            raise ValueError('Origem inválida.')
        uid, nome_autor = autor(user)
        conn = self.get_connection()
        try:
            excluido = conn.execute('SELECT id FROM obra_arquivos WHERE obra_id=? AND sha256=? '
                                    'AND excluido_em IS NOT NULL', (obra_id, sha256)).fetchone()
            if excluido:
                conn.execute('UPDATE obra_arquivos SET tipo=?, nome=?, origem=?, origem_ref=?, enviado_por=?, '
                             "enviado_por_nome=?, enviado_em=?, status='a_conferir', excluido_por=NULL, "
                             'excluido_por_nome=NULL, excluido_em=NULL WHERE id=?',
                             (tipo, nome, origem, origem_ref, uid, nome_autor, agora(), excluido['id']))
                arquivo_id = excluido['id']
            else:
                try:
                    cur = conn.execute('INSERT INTO obra_arquivos(obra_id,tipo,nome,sha256,bytes,origem,origem_ref,'
                                       'enviado_por,enviado_por_nome,enviado_em) VALUES(?,?,?,?,?,?,?,?,?,?)',
                                       (obra_id, tipo, nome, sha256, tamanho, origem, origem_ref, uid, nome_autor,
                                        agora()))
                except sqlite3.IntegrityError:
                    raise ValueError('Este arquivo já foi enviado para esta obra.') from None
                arquivo_id = cur.lastrowid
            registrar_auditoria(conn, user, 'arquivo_anexado' if origem == 'comunicacoes' else 'arquivo_enviado',
                                obra_id, {'tipo': tipo, 'nome': nome, **({'reenviado': True} if excluido else {})})
            if antes_do_commit:
                antes_do_commit()
            conn.commit()
            return arquivo_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def listar(self, obra_id: int, tipo: Optional[str] = None) -> List[Dict]:
        """Versões ativas, mais recentes primeiro."""
        conn = self.get_connection()
        try:
            sql = 'SELECT * FROM obra_arquivos WHERE obra_id=? AND excluido_em IS NULL'
            parametros = [obra_id]
            if tipo:
                sql += ' AND tipo=?'
                parametros.append(tipo)
            rows = conn.execute(sql + ' ORDER BY enviado_em DESC, id DESC', parametros)
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def corrigir(self, arquivo_id: int, nome: str, tipo: str, user) -> bool:
        """Muda nome e/ou tipo de um arquivo ativo. False quando nada mudou."""
        if tipo not in TIPOS:
            raise ValueError('Tipo de documento inválido.')
        conn = self.get_connection()
        try:
            atual = conn.execute('SELECT * FROM obra_arquivos WHERE id=? AND excluido_em IS NULL',
                                 (arquivo_id,)).fetchone()
            if not atual:
                raise ValueError('Arquivo não encontrado.')
            if (atual['nome'], atual['tipo']) == (nome, tipo):
                return False
            conn.execute('UPDATE obra_arquivos SET nome=?, tipo=? WHERE id=?', (nome, tipo, arquivo_id))
            registrar_auditoria(conn, user, 'arquivo_corrigido', atual['obra_id'],
                                {'antes': {'nome': atual['nome'], 'tipo': atual['tipo']},
                                 'depois': {'nome': nome, 'tipo': tipo}})
            conn.commit()
            return True
        finally:
            conn.close()

    def excluir(self, arquivo_id: int, user) -> bool:
        """Tira o arquivo da lista; registro e conteúdo ficam (o mesmo conteúdo pode ser reenviado)."""
        uid, nome_autor = autor(user)
        conn = self.get_connection()
        try:
            atual = conn.execute('SELECT * FROM obra_arquivos WHERE id=? AND excluido_em IS NULL',
                                 (arquivo_id,)).fetchone()
            if not atual:
                return False
            conn.execute('UPDATE obra_arquivos SET excluido_por=?, excluido_por_nome=?, excluido_em=? WHERE id=?',
                         (uid, nome_autor, agora(), arquivo_id))
            registrar_auditoria(conn, user, 'arquivo_excluido', atual['obra_id'],
                                {'tipo': atual['tipo'], 'nome': atual['nome']})
            conn.commit()
            return True
        finally:
            conn.close()

    def obter(self, arquivo_id: int) -> Optional[Dict]:
        conn = self.get_connection()
        try:
            row = conn.execute('SELECT * FROM obra_arquivos WHERE id=?', (arquivo_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def existe_sha(self, obra_id: int, sha256: str) -> Optional[Dict]:
        """Arquivo ativo com este conteúdo na obra (excluído não conta)."""
        conn = self.get_connection()
        try:
            row = conn.execute('SELECT * FROM obra_arquivos WHERE obra_id=? AND sha256=? AND excluido_em IS NULL',
                               (obra_id, sha256)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
