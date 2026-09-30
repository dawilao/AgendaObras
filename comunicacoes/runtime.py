"""Armazenamento privado por usuário autenticado; nenhuma credencial global."""
import json
import os
import sqlite3
from contextlib import closing
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
    if root:
        return MailStore(Path(root) / uid / 'comunicacoes.db', Path(root) / 'arquivos')
    # Sem root, os anexos vão para a pasta comum (blobs.default_root): uma cópia para todos.
    return MailStore(mail_root() / uid / 'comunicacoes.db')


def get_shared_store():
    return MailStore(mail_root() / 'compartilhado' / 'comunicacoes.db')


def personal_stores():
    """Caixas pessoais de todos os usuários (a lixeira da equipe alcança as cópias de cada um)."""
    return [MailStore(path) for path in sorted(mail_root().glob('*/comunicacoes.db'))
            if path.parent.name != 'compartilhado']


def get_trash():
    from .lixeira import Lixeira
    return Lixeira(get_shared_store(), personal_stores)


def is_admin(user_id):
    """Consultado a cada operação: perder o perfil de admin vale na hora, sem recarregar a página."""
    authorize_user(user_id)
    from db.auth_repo import AuthDatabase
    return bool((AuthDatabase().obter_usuario_por_id(owner_id(user_id)) or {}).get('is_admin'))


def insurance_files():
    """sha256 dos anexos registrados como apólice ou boleto no controle de seguro."""
    from db.connection import CAMINHO_DB
    path = Path(CAMINHO_DB).resolve()
    if not path.exists():
        return set()
    found = set()
    def collect(value):
        if isinstance(value, dict):
            if isinstance(value.get('sha256'), str):
                found.add(value['sha256'])
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        try:
            rows = db.execute('SELECT vinculos FROM seguro_rodadas').fetchall()
        except sqlite3.OperationalError:
            return set()
    for (links,) in rows:
        try:
            collect(json.loads(links or '{}'))
        except ValueError:
            continue
    return found


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


def works_overview(user_id):
    """Obras autorizadas com o que as pastas de Comunicações mostram: IC, contrato, UF e a
    situação calculada como na aba Obras. Lido uma vez por montagem da lista, não a cada operação."""
    from db.connection import CAMINHO_DB
    from utils.obras_helper import ObrasHelper
    from .encaixe import uf_contrato
    allowed = {w['id'] for w in available_works(user_id)}
    path = Path(CAMINHO_DB).resolve()
    if not allowed or not path.exists():
        return {}
    # Uma leitura para todas as obras (a situação só usa concluído/prazo de cada tarefa):
    # no servidor, uma consulta por obra segurava a tela de todos os usuários.
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        obras = [dict(r) for r in db.execute('SELECT * FROM obras') if str(r['id']) in allowed]
        checklists = {}
        for item in db.execute('SELECT * FROM obra_checklist ORDER BY id'):
            if str(item['obra_id']) in allowed:
                checklists.setdefault(item['obra_id'], []).append(dict(item))
    overview = {}
    for obra in obras:
        try:
            _, _, status = ObrasHelper.obter_status_visual(obra, checklists.get(obra['id'], []))
        except Exception:
            status = None
        if status == 'Erro':  # Falha ao calcular: situação a conferir, nunca "Em Andamento" por padrão.
            status = None
        uf, contrato = uf_contrato(obra.get('cliente'))
        overview[str(obra['id'])] = {'ic': (obra.get('contrato_ic') or '').strip(), 'cliente': obra.get('cliente') or '',
                                     'uf': uf, 'contrato': contrato, 'status_texto': status,
                                     'bucket': ObrasHelper.obter_bucket_grade(status) if status else None}
    return overview


def confirmable_works(user_id):
    """Obras em que o usuário dá o OK do coordenador (confirma o vínculo), numa leitura só:
    admin: todas as autorizadas; demais: o responsável definido na obra ou, sem responsável
    definido, quem está vinculado ao contrato (mesma regra de ObrasHelper.resolver_coordenador)."""
    uid = owner_id(user_id)
    allowed = {w['id'] for w in available_works(uid)}
    if not allowed:
        return set()
    from db.auth_repo import AuthDatabase
    if (AuthDatabase().obter_usuario_por_id(uid) or {}).get('is_admin'):
        return allowed
    from db.connection import CAMINHO_DB
    from db.contratos_repo import ContratosDatabase
    path = Path(CAMINHO_DB).resolve()
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        rows = [r for r in db.execute('SELECT * FROM obras') if str(r['id']) in allowed]
    contracts = {(c or '').strip() for c in ContratosDatabase().listar_contratos_usuario(uid)}
    found = set()
    for row in rows:
        coordenador = row['coordenador_id'] if 'coordenador_id' in row.keys() else None
        if (str(coordenador) == uid) if coordenador else (row['cliente'] or '').strip() in contracts:
            found.add(str(row['id']))
    return found


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
