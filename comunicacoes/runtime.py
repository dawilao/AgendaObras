"""Armazenamento privado por usuário autenticado; nenhuma credencial global."""
import os
import sqlite3
from pathlib import Path
from .store import MailStore


def owner_id(value):
    if isinstance(value, bool) or not str(value).isdigit() or int(value) <= 0:
        raise PermissionError('Identificação de usuário inválida.')
    return str(int(value))


def mail_root():
    """Por padrão, ao lado do banco principal (mesma regra de db/connection.py)."""
    from db.connection import CAMINHO_DB
    return Path(os.getenv('AGENDA_MAIL_ROOT') or
                Path(CAMINHO_DB).resolve().parent / 'comunicacoes' / 'usuarios')


def get_store(user_id, root=None):
    uid = owner_id(user_id)
    directory = Path(root) if root else mail_root()
    return MailStore(directory / uid / 'comunicacoes.db')


def get_shared_store():
    return MailStore(mail_root() / 'compartilhado' / 'comunicacoes.db')


def available_works(user_id):
    authorize_user(user_id)
    from db.connection import CAMINHO_DB
    from db.auth_repo import AuthDatabase
    from db.contratos_repo import ContratosDatabase
    user = AuthDatabase().obter_usuario_por_id(user_id)
    path = Path(CAMINHO_DB).resolve()
    if not path.exists():
        return []
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        if user.get('is_admin'):
            rows = db.execute('SELECT id,nome_contrato FROM obras ORDER BY nome_contrato').fetchall()
        else:
            contracts = ContratosDatabase().listar_contratos_usuario(user_id)
            if not contracts:
                return []
            markers = ','.join('?' for _ in contracts)
            rows = db.execute(f'SELECT id,nome_contrato FROM obras WHERE TRIM(cliente) IN ({markers}) ORDER BY nome_contrato', contracts).fetchall()
        return [{'id': str(row[0]), 'name': row[1]} for row in rows]


def authorize_user(expected_id):
    from nicegui import app
    from services.auth_service import verificar_autenticacao
    from db.auth_repo import AuthDatabase
    uid = owner_id(expected_id)
    if not verificar_autenticacao() or str(app.storage.user.get('user_id')) != uid:
        raise PermissionError('A sessão mudou. Entre novamente no portal.')
    user = AuthDatabase().obter_usuario_por_id(uid)
    if not user:
        raise PermissionError('Usuário não encontrado.')
    return f"usuario:{uid}"
