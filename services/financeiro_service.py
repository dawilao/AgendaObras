"""Permissões do financeiro Omie (consulta e alterações), sempre conferidas no servidor.

Ver: administrador, Financeiro ou coordenador da própria obra (obras.coordenador_id).
Alterar: só quem tem a permissão Financeiro. Estar vinculado ao contrato não dá acesso.
Exceção: validar os parceiros da obra também cabe ao coordenador da própria obra.
"""
from db.auth_repo import AuthDatabase


def usuario_atual():
    """Usuário lido do banco pela sessão; a permissão nunca vem do navegador."""
    from nicegui import app
    from services.auth_service import verificar_autenticacao
    if not verificar_autenticacao():
        raise PermissionError('Entre no portal para consultar o financeiro.')
    user = AuthDatabase().obter_usuario_por_id(app.storage.user.get('user_id'))
    if not user:
        raise PermissionError('Sessão inválida.')
    return user


def eh_financeiro(user) -> bool:
    return bool(user and user.get('financeiro'))


def eh_coordenador_da_obra(user, obra) -> bool:
    coordenador = (obra or {}).get('coordenador_id')
    return bool(user and user.get('id') is not None and coordenador is not None
                and str(user['id']) == str(coordenador))


def pode_ver_financeiro(user, obra) -> bool:
    if not user or not user.get('id'):
        return False
    return bool(user.get('is_admin')) or eh_financeiro(user) or eh_coordenador_da_obra(user, obra)


def pode_editar_financeiro(user) -> bool:
    return eh_financeiro(user)


def pode_validar_parceiros(user, obra) -> bool:
    """Financeiro ou coordenador da própria obra; administrador sem a permissão Financeiro, não."""
    if not user or not user.get('id'):
        return False
    return eh_financeiro(user) or eh_coordenador_da_obra(user, obra)


def exigir_ver(obra, usuario_provider=usuario_atual):
    user = usuario_provider()
    if not pode_ver_financeiro(user, obra):
        raise PermissionError('Financeiro restrito ao administrador, ao Financeiro e ao coordenador desta obra.')
    return user


def exigir_editar(usuario_provider=usuario_atual):
    user = usuario_provider()
    if not pode_editar_financeiro(user):
        raise PermissionError('Somente o Financeiro pode fazer esta alteração.')
    return user


def nome_usuario(user) -> str:
    return f"{user.get('nome') or ''} {user.get('sobrenome') or ''}".strip() or (user.get('email') or '')


def definir_permissao_financeiro(user_id, valor, usuario_provider=usuario_atual, auth_db=None):
    user = usuario_provider()
    if not user.get('is_admin'):
        raise PermissionError('Somente administrador pode definir o Financeiro.')
    if type(valor) is not bool:
        raise ValueError('Permissão inválida.')
    db = auth_db or AuthDatabase()
    conn = db.get_connection()
    try:
        conn.execute('UPDATE usuarios SET financeiro=? WHERE id=?', (int(valor), user_id))
        conn.commit()
    finally:
        conn.close()
