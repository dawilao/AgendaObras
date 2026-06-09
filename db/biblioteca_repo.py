"""
Repositório SQLite isolado para a Biblioteca de cards.
Segue o mesmo padrão de auth_repo.py e contratos_repo.py.
"""

import os
import datetime
import sqlite3
from typing import Dict, List, Optional

from db.connection import BaseRepository
from core.error_logger import log_error

_CAMINHO_DRIVE = r'db'
_CAMINHO_LOCAL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolver_caminho_biblioteca_db() -> str:
    env_path = (os.getenv('AGENDA_OBRAS_BIBLIOTECA_DB_PATH') or '').strip()
    if env_path:
        return env_path
    if os.path.isdir(_CAMINHO_DRIVE):
        return os.path.join(_CAMINHO_DRIVE, 'biblioteca.db')
    return os.path.join(_CAMINHO_LOCAL, 'biblioteca.db')


def _resolver_pasta_uploads() -> str:
    env_path = (os.getenv('AGENDA_OBRAS_BIBLIOTECA_UPLOADS_PATH') or '').strip()
    if env_path:
        os.makedirs(env_path, exist_ok=True)
        return env_path
    pasta_db = os.path.dirname(os.path.abspath(_resolver_caminho_biblioteca_db()))
    pasta = os.path.join(pasta_db, 'uploads', 'biblioteca')
    os.makedirs(pasta, exist_ok=True)
    return pasta


CAMINHO_BIBLIOTECA_DB = _resolver_caminho_biblioteca_db()
PASTA_UPLOADS = _resolver_pasta_uploads()


class BibliotecaRepository(BaseRepository):
    def __init__(self, db_name: str = CAMINHO_BIBLIOTECA_DB):
        super().__init__(db_name)
        self.init_database()

    def init_database(self) -> None:
        conn = self.get_connection()
        try:
            conn.execute('PRAGMA foreign_keys = ON')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS cards (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    titulo      TEXT NOT NULL,
                    conteudo    TEXT,
                    imagem      BLOB,
                    imagem_tipo TEXT,
                    criado_por  TEXT NOT NULL,
                    criado_em   DATETIME NOT NULL,
                    editado_em  DATETIME
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS tags (
                    id   INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT NOT NULL UNIQUE
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS card_tags (
                    card_id INTEGER NOT NULL,
                    tag_id  INTEGER NOT NULL,
                    PRIMARY KEY (card_id, tag_id),
                    FOREIGN KEY (card_id) REFERENCES cards(id) ON DELETE CASCADE,
                    FOREIGN KEY (tag_id)  REFERENCES tags(id)  ON DELETE CASCADE
                )
            ''')
            # Migração: adiciona coluna imagem_path se ainda não existir
            try:
                conn.execute('ALTER TABLE cards ADD COLUMN imagem_path TEXT')
                conn.commit()
            except sqlite3.OperationalError:
                pass
            conn.commit()
        finally:
            conn.close()

    # ── Tags ──────────────────────────────────────────────────────────────────

    def listar_tags(self) -> List[Dict]:
        conn = self.get_connection()
        try:
            rows = conn.execute(
                'SELECT id, nome FROM tags ORDER BY nome COLLATE NOCASE'
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def criar_tag(self, nome: str) -> int:
        conn = self.get_connection()
        try:
            cur = conn.execute('INSERT INTO tags (nome) VALUES (?)', (nome.strip(),))
            conn.commit()
            return cur.lastrowid
        except Exception as e:
            log_error(e, 'db.biblioteca_repo', f'criar_tag: {nome}')
            raise
        finally:
            conn.close()

    def renomear_tag(self, tag_id: int, novo_nome: str) -> bool:
        conn = self.get_connection()
        try:
            conn.execute('UPDATE tags SET nome = ? WHERE id = ?', (novo_nome.strip(), tag_id))
            conn.commit()
            return True
        except Exception as e:
            log_error(e, 'db.biblioteca_repo', f'renomear_tag id={tag_id}')
            raise
        finally:
            conn.close()

    def excluir_tag(self, tag_id: int) -> bool:
        conn = self.get_connection()
        try:
            conn.execute('PRAGMA foreign_keys = ON')
            conn.execute('DELETE FROM tags WHERE id = ?', (tag_id,))
            conn.commit()
            return True
        except Exception as e:
            log_error(e, 'db.biblioteca_repo', f'excluir_tag id={tag_id}')
            raise
        finally:
            conn.close()

    # ── Cards ─────────────────────────────────────────────────────────────────

    def listar_cards(self, tag_ids: Optional[List[int]] = None) -> List[Dict]:
        conn = self.get_connection()
        try:
            if tag_ids:
                placeholders = ','.join('?' * len(tag_ids))
                rows = conn.execute(f'''
                    SELECT DISTINCT c.id, c.titulo, c.conteudo, c.imagem_path,
                                    c.criado_por, c.criado_em, c.editado_em
                    FROM cards c
                    JOIN card_tags ct ON ct.card_id = c.id
                    WHERE ct.tag_id IN ({placeholders})
                    ORDER BY c.criado_em DESC
                ''', tag_ids).fetchall()
            else:
                rows = conn.execute(
                    '''SELECT id, titulo, conteudo, imagem_path,
                              criado_por, criado_em, editado_em
                       FROM cards ORDER BY criado_em DESC'''
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def obter_card(self, card_id: int) -> Optional[Dict]:
        conn = self.get_connection()
        try:
            row = conn.execute('SELECT * FROM cards WHERE id = ?', (card_id,)).fetchone()
            if not row:
                return None
            card = dict(row)

            # Migração lazy: BLOB legado → arquivo em disco
            if not card.get('imagem_path') and card.get('imagem'):
                try:
                    from utils.image_utils import processar_e_salvar_imagem
                    caminho = processar_e_salvar_imagem(card['imagem'], PASTA_UPLOADS)
                    path_relativo = os.path.relpath(caminho, start=os.path.dirname(os.path.abspath(CAMINHO_BIBLIOTECA_DB)))
                    conn.execute(
                        'UPDATE cards SET imagem_path = ?, imagem = NULL, imagem_tipo = NULL WHERE id = ?',
                        (path_relativo, card_id)
                    )
                    conn.commit()
                    card['imagem_path'] = path_relativo
                    card['imagem'] = None
                except Exception as e:
                    log_error(e, 'db.biblioteca_repo', f'migração lazy BLOB card id={card_id}')

            return card
        finally:
            conn.close()

    def obter_tags_card(self, card_id: int) -> List[Dict]:
        conn = self.get_connection()
        try:
            rows = conn.execute('''
                SELECT t.id, t.nome
                FROM tags t
                JOIN card_tags ct ON ct.tag_id = t.id
                WHERE ct.card_id = ?
                ORDER BY t.nome COLLATE NOCASE
            ''', (card_id,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def criar_card(
        self,
        titulo: str,
        conteudo: str,
        imagem_path: Optional[str],
        criado_por: str,
    ) -> int:
        agora = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn = self.get_connection()
        try:
            cur = conn.execute(
                '''INSERT INTO cards (titulo, conteudo, imagem_path, criado_por, criado_em)
                   VALUES (?, ?, ?, ?, ?)''',
                (titulo.strip(), conteudo, imagem_path, criado_por, agora),
            )
            conn.commit()
            return cur.lastrowid
        except Exception as e:
            log_error(e, 'db.biblioteca_repo', f'criar_card: {titulo}')
            raise
        finally:
            conn.close()

    def editar_card(
        self,
        card_id: int,
        titulo: str,
        conteudo: str,
        imagem_path: Optional[str] = None,
    ) -> bool:
        agora = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn = self.get_connection()
        try:
            if imagem_path is not None:
                # Remove arquivo anterior se existir
                row = conn.execute(
                    'SELECT imagem_path FROM cards WHERE id = ?', (card_id,)
                ).fetchone()
                if row and row['imagem_path']:
                    _remover_arquivo(row['imagem_path'], CAMINHO_BIBLIOTECA_DB)

                conn.execute(
                    '''UPDATE cards
                       SET titulo = ?, conteudo = ?, imagem_path = ?, editado_em = ?
                       WHERE id = ?''',
                    (titulo.strip(), conteudo, imagem_path, agora, card_id),
                )
            else:
                conn.execute(
                    '''UPDATE cards
                       SET titulo = ?, conteudo = ?, editado_em = ?
                       WHERE id = ?''',
                    (titulo.strip(), conteudo, agora, card_id),
                )
            conn.commit()
            return True
        except Exception as e:
            log_error(e, 'db.biblioteca_repo', f'editar_card id={card_id}')
            raise
        finally:
            conn.close()

    def excluir_card(self, card_id: int) -> bool:
        conn = self.get_connection()
        try:
            conn.execute('PRAGMA foreign_keys = ON')
            row = conn.execute(
                'SELECT imagem_path FROM cards WHERE id = ?', (card_id,)
            ).fetchone()
            if row and row['imagem_path']:
                _remover_arquivo(row['imagem_path'], CAMINHO_BIBLIOTECA_DB)

            conn.execute('DELETE FROM cards WHERE id = ?', (card_id,))
            conn.commit()
            return True
        except Exception as e:
            log_error(e, 'db.biblioteca_repo', f'excluir_card id={card_id}')
            raise
        finally:
            conn.close()

    def vincular_tags_card(self, card_id: int, tag_ids: List[int]) -> bool:
        conn = self.get_connection()
        try:
            conn.execute('DELETE FROM card_tags WHERE card_id = ?', (card_id,))
            for tag_id in tag_ids:
                conn.execute(
                    'INSERT OR IGNORE INTO card_tags (card_id, tag_id) VALUES (?, ?)',
                    (card_id, tag_id),
                )
            conn.commit()
            return True
        except Exception as e:
            log_error(e, 'db.biblioteca_repo', f'vincular_tags_card card={card_id}')
            raise
        finally:
            conn.close()


def _remover_arquivo(imagem_path: str, caminho_db: str) -> None:
    """Remove arquivo de imagem do disco, silenciosamente se não encontrado."""
    try:
        if os.path.isabs(imagem_path):
            caminho_abs = imagem_path
        else:
            pasta_db = os.path.dirname(os.path.abspath(caminho_db))
            caminho_abs = os.path.join(pasta_db, imagem_path)
        if os.path.isfile(caminho_abs):
            os.remove(caminho_abs)
    except Exception as e:
        log_error(e, 'db.biblioteca_repo', f'remover_arquivo: {imagem_path}')
