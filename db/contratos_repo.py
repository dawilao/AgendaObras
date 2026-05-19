"""
Repositório do catálogo de contratos em banco SQLite separado.
"""

import os
import sqlite3
from typing import List
from core.error_logger import log_error

_CAMINHO_DRIVE = r'G:\Meu Drive\17 - MODELOS\PROGRAMAS\AgendaObras\app\db'
# Raiz do projeto (um nível acima de db/)
_CAMINHO_LOCAL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONTRATOS_SEED = [
    'C.E.F BAHIA - 4922.2024',
    'C.E.F MANAUS - 4569.2024',
    'C.E.F CURITIBA - 534.2025',
    'C.E.F MINAS GERAIS - 8756.2025',
    'C.E.F PIAUI - 9218.2025',
    'C.E.F SERGIPE ALAGOAS - 111.2026',
    'C.E.F NITERÓI - 9852.2025',
    'C. E. MANAUS - 2025.7421.1593',
    'ATA CURITIBA - 2025.7421.0232',
]


def _resolver_caminho_contratos_db() -> str:
    env_path = (os.getenv('AGENDA_OBRAS_CONTRATOS_DB_PATH') or '').strip()
    if env_path:
        return env_path
    if os.path.isdir(_CAMINHO_DRIVE):
        return os.path.join(_CAMINHO_DRIVE, 'contratos.db')
    return os.path.join(_CAMINHO_LOCAL, 'contratos.db')


class ContratosDatabase:
    def __init__(self, db_name: str = None):
        self.db_name = db_name or _resolver_caminho_contratos_db()
        self.init_database()

    def get_connection(self):
        conn = sqlite3.connect(self.db_name, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=30000')
        return conn

    def init_database(self):
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''CREATE TABLE IF NOT EXISTS contratos (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL UNIQUE)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS contrato_usuarios (id INTEGER PRIMARY KEY AUTOINCREMENT, contrato_nome TEXT NOT NULL, usuario_id INTEGER NOT NULL, data_vinculacao TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(contrato_nome, usuario_id))''')
            cursor.execute('''CREATE INDEX IF NOT EXISTS idx_contrato_usuarios_usuario ON contrato_usuarios(usuario_id)''')
            cursor.execute('''CREATE INDEX IF NOT EXISTS idx_contrato_usuarios_contrato ON contrato_usuarios(contrato_nome)''')
            cursor.executemany('INSERT OR IGNORE INTO contratos (nome) VALUES (?)', [(nome,) for nome in CONTRATOS_SEED])
            conn.commit()
        except Exception as e:
            log_error(e, "contratos_database", "Inicializar contratos.db")
        finally:
            if conn:
                conn.close()

    def listar_contratos(self) -> List[str]:
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT nome FROM contratos ORDER BY nome ASC')
            return [row['nome'] for row in cursor.fetchall()]
        except Exception as e:
            log_error(e, "contratos_database", "Listar contratos")
            return []
        finally:
            if conn:
                conn.close()

    def listar_contratos_usuario(self, usuario_id: int) -> List[str]:
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT contrato_nome FROM contrato_usuarios WHERE usuario_id = ? ORDER BY contrato_nome ASC', (usuario_id,))
            return [row['contrato_nome'] for row in cursor.fetchall()]
        except Exception as e:
            log_error(e, "contratos_database", f"Listar contratos do usuário {usuario_id}")
            return []
        finally:
            if conn:
                conn.close()

    def vincular_usuario_contrato(self, usuario_id: int, contrato_nome: str) -> bool:
        conn = None
        try:
            contrato_nome = (contrato_nome or '').strip()
            if not contrato_nome:
                return False
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('INSERT OR IGNORE INTO contrato_usuarios (contrato_nome, usuario_id) VALUES (?, ?)', (contrato_nome, usuario_id))
            conn.commit()
            return True
        except Exception as e:
            log_error(e, "contratos_database", f"Vincular usuário {usuario_id} ao contrato {contrato_nome}")
            return False
        finally:
            if conn:
                conn.close()

    def desvincular_usuario_contrato(self, usuario_id: int, contrato_nome: str) -> bool:
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('DELETE FROM contrato_usuarios WHERE usuario_id = ? AND contrato_nome = ?', (usuario_id, (contrato_nome or '').strip()))
            conn.commit()
            return True
        except Exception as e:
            log_error(e, "contratos_database", f"Desvincular usuário {usuario_id} do contrato {contrato_nome}")
            return False
        finally:
            if conn:
                conn.close()

    def substituir_vinculos_usuario(self, usuario_id: int, contratos: List[str]) -> bool:
        conn = None
        try:
            contratos_limpos = sorted({(c or '').strip() for c in (contratos or []) if (c or '').strip()})
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('DELETE FROM contrato_usuarios WHERE usuario_id = ?', (usuario_id,))
            if contratos_limpos:
                cursor.executemany('INSERT OR IGNORE INTO contrato_usuarios (contrato_nome, usuario_id) VALUES (?, ?)', [(c, usuario_id) for c in contratos_limpos])
            conn.commit()
            return True
        except Exception as e:
            if conn:
                conn.rollback()
            log_error(e, "contratos_database", f"Substituir vínculos do usuário {usuario_id}")
            return False
        finally:
            if conn:
                conn.close()

    def remover_todos_vinculos_usuario(self, usuario_id: int) -> bool:
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('DELETE FROM contrato_usuarios WHERE usuario_id = ?', (usuario_id,))
            conn.commit()
            return True
        except Exception as e:
            log_error(e, "contratos_database", f"Remover vínculos do usuário {usuario_id}")
            return False
        finally:
            if conn:
                conn.close()

    def contar_contratos_por_usuario(self) -> dict:
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT usuario_id, COUNT(*) AS total FROM contrato_usuarios GROUP BY usuario_id')
            return {row['usuario_id']: row['total'] for row in cursor.fetchall()}
        except Exception as e:
            log_error(e, "contratos_database", "Contar contratos por usuário")
            return {}
        finally:
            if conn:
                conn.close()
