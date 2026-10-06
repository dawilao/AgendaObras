"""Arquivos da obra (CCT, orçamento e aditivos): registro das versões no banco de obras.

O conteúdo fica no disco, endereçado pelo sha256 (services.obra_arquivos). Nada é apagado pela
tela: cada envio é uma versão nova, e o mesmo conteúdo não é registrado duas vezes na obra.
"""
from typing import Dict, List, Optional

from db.connection import BaseRepository
from db.omie_repo import _autor, agora, registrar_auditoria

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


class ObraArquivosRepository(BaseRepository):

    def registrar(self, obra_id: int, tipo: str, nome: str, sha256: str, tamanho: int, origem: str,
                  user, origem_ref: Optional[str] = None) -> int:
        if tipo not in TIPOS:
            raise ValueError('Tipo de documento inválido.')
        if origem not in ORIGENS:
            raise ValueError('Origem inválida.')
        uid, autor = _autor(user)
        conn = self.get_connection()
        try:
            if conn.execute('SELECT 1 FROM obra_arquivos WHERE obra_id=? AND sha256=?', (obra_id, sha256)).fetchone():
                raise ValueError('Este arquivo já foi enviado para esta obra.')
            cur = conn.execute('INSERT INTO obra_arquivos(obra_id,tipo,nome,sha256,bytes,origem,origem_ref,'
                               'enviado_por,enviado_por_nome,enviado_em) VALUES(?,?,?,?,?,?,?,?,?,?)',
                               (obra_id, tipo, nome, sha256, tamanho, origem, origem_ref, uid, autor, agora()))
            registrar_auditoria(conn, user, 'arquivo_anexado' if origem == 'comunicacoes' else 'arquivo_enviado',
                                obra_id, {'tipo': tipo, 'nome': nome})
            conn.commit()
            return cur.lastrowid
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def listar(self, obra_id: int, tipo: Optional[str] = None) -> List[Dict]:
        """Versões mais recentes primeiro."""
        conn = self.get_connection()
        try:
            if tipo:
                rows = conn.execute('SELECT * FROM obra_arquivos WHERE obra_id=? AND tipo=? ORDER BY id DESC',
                                    (obra_id, tipo))
            else:
                rows = conn.execute('SELECT * FROM obra_arquivos WHERE obra_id=? ORDER BY id DESC', (obra_id,))
            return [dict(r) for r in rows]
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
        conn = self.get_connection()
        try:
            row = conn.execute('SELECT * FROM obra_arquivos WHERE obra_id=? AND sha256=?', (obra_id, sha256)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
