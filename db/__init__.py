"""
Facade de compatibilidade — Database agrega ObrasRepository e ChecklistRepository.
Código existente que faz `from database import Database` continua funcionando via
o shim no arquivo database.py da raiz.
"""

from db.obras_repo import ObrasRepository
from db.checklist_repo import ChecklistRepository
from db.connection import CAMINHO_DB, TAREFAS_COM_DIAS_UTEIS


class Database(ObrasRepository, ChecklistRepository):
    """Facade completa: todos os métodos de obras, checklist e medições num único objeto."""
    pass


__all__ = ['Database', 'CAMINHO_DB', 'TAREFAS_COM_DIAS_UTEIS']
