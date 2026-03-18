"""
Módulo para gerenciamento do catálogo de contratos em banco SQLite separado.
Usado para alimentar o dropdown de contratos na interface.
"""

import os
import sqlite3
from typing import List

from error_logger import log_error


# Caminho padrão: mesmo diretório do banco principal (Google Drive)
_CAMINHO_DRIVE = r'G:\Meu Drive\17 - MODELOS\PROGRAMAS\AgendaObras\app\db'
# Caminho fallback: diretório local junto ao código
_CAMINHO_LOCAL = os.path.dirname(os.path.abspath(__file__))


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
    """Resolve o caminho do banco de contratos.
    Tenta usar o diretório do Google Drive; se não existir, usa local."""
    if os.path.isdir(_CAMINHO_DRIVE):
        return os.path.join(_CAMINHO_DRIVE, 'contratos.db')
    return os.path.join(_CAMINHO_LOCAL, 'contratos.db')


class ContratosDatabase:
    def __init__(self, db_name: str = None):
        self.db_name = db_name or _resolver_caminho_contratos_db()
        self.init_database()

    def get_connection(self):
        """Cria e retorna conexão com timeout e WAL."""
        conn = sqlite3.connect(self.db_name, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=30000')
        return conn

    def init_database(self):
        """Cria estrutura e aplica seed inicial sem duplicar registros."""
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS contratos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT NOT NULL UNIQUE
                )
            ''')

            cursor.executemany(
                'INSERT OR IGNORE INTO contratos (nome) VALUES (?)',
                [(nome,) for nome in CONTRATOS_SEED]
            )
            conn.commit()
        except Exception as e:
            log_error(e, "contratos_database", "Inicializar contratos.db")
        finally:
            if conn:
                conn.close()

    def listar_contratos(self) -> List[str]:
        """Retorna lista de contratos ordenada por nome."""
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
