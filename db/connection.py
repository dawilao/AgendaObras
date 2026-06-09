"""
Gerenciamento de conexão SQLite compartilhado entre os repositórios.
"""

import sqlite3
import datetime
import os
from typing import Optional

_CAMINHO_DRIVE = r'db'
_CAMINHO_LOCAL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TAREFAS_COM_DIAS_UTEIS = {'ANÁLISE', 'ANÁLISE - GESTOR'}


def _resolver_caminho_db() -> str:
    env_path = (os.getenv('AGENDA_OBRAS_DB_PATH') or '').strip()
    if env_path:
        return env_path
    if os.path.isdir(_CAMINHO_DRIVE):
        return os.path.join(_CAMINHO_DRIVE, 'agendaobras.db')
    return os.path.join(_CAMINHO_LOCAL, 'agendaobras.db')


CAMINHO_DB = _resolver_caminho_db()


class BaseRepository:
    """Fornece conexão WAL e utilitários de data para todos os repositórios."""

    def __init__(self, db_name: str = CAMINHO_DB):
        self.db_name = db_name

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_name, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=30000')
        return conn

    def _adicionar_dias_uteis(self, data_base: datetime.datetime, dias: int) -> datetime.datetime:
        if dias == 0:
            return data_base
        passo = 1 if dias > 0 else -1
        restantes = abs(dias)
        data_resultado = data_base
        while restantes > 0:
            data_resultado += datetime.timedelta(days=passo)
            if data_resultado.weekday() < 5:
                restantes -= 1
        return data_resultado

    def _calcular_data_limite(
        self,
        data_base: datetime.datetime,
        prazo_dias: int,
        descricao: Optional[str] = None,
    ) -> datetime.datetime:
        if descricao in TAREFAS_COM_DIAS_UTEIS:
            return self._adicionar_dias_uteis(data_base, prazo_dias)
        return data_base + datetime.timedelta(days=prazo_dias)
