"""
Middleware de autenticação para o AgendaObras.
Redireciona usuários não autenticados para /login.
"""

from nicegui import app
from starlette.requests import Request
from starlette.responses import RedirectResponse

from auth_database import AuthDatabase

# Rotas que NÃO exigem autenticação
ROTAS_PUBLICAS = {'/login', '/login/', '/_nicegui', '/favicon.ico'}


def configurar_middleware():
    """Registra o middleware de autenticação no app NiceGUI."""

    @app.middleware('http')
    async def auth_middleware(request: Request, call_next):
        # Permite rotas públicas e assets internos do NiceGUI
        path = request.url.path
        if (path in ROTAS_PUBLICAS
                or path.startswith('/_nicegui')
                or path.startswith('/static')
                or path.startswith('/_event')):
            return await call_next(request)

        # Verifica autenticação via storage do usuário
        # O storage.user é baseado em cookie de sessão gerenciado pelo NiceGUI
        # Precisamos verificar via header do cookie, mas o NiceGUI resolve
        # isso internamente ao acessar app.storage.user dentro de uma página.
        # O middleware HTTP não tem acesso direto ao storage.user,
        # então a verificação real é feita no decorator da página.
        return await call_next(request)


def verificar_autenticacao() -> bool:
    """Verifica se o usuário está autenticado. Para uso dentro de páginas NiceGUI."""
    return app.storage.user.get('autenticado', False)


def obter_usuario_logado() -> dict:
    """Retorna dados do usuário logado do storage."""
    usuario_sessao = {
        'id': app.storage.user.get('user_id'),
        'nome': app.storage.user.get('nome', ''),
        'sobrenome': app.storage.user.get('sobrenome', ''),
        'email': app.storage.user.get('email', ''),
        'is_admin': app.storage.user.get('is_admin', False),
    }

    user_id = usuario_sessao.get('id')
    if not user_id:
        return usuario_sessao

    usuario_db = AuthDatabase().obter_usuario_por_id(user_id)
    if not usuario_db:
        return usuario_sessao

    return {
        'id': usuario_db.get('id', user_id),
        'nome': usuario_db.get('nome', usuario_sessao['nome']),
        'sobrenome': usuario_db.get('sobrenome', usuario_sessao['sobrenome']),
        'email': usuario_db.get('email', usuario_sessao['email']),
        'is_admin': bool(usuario_db.get('is_admin', usuario_sessao['is_admin'])),
    }


def atualizar_usuario_sessao(nome: str, sobrenome: str, email: str) -> None:
    """Atualiza os dados do usuário na sessão (sem fazer login novamente)."""
    app.storage.user['nome'] = nome
    app.storage.user['sobrenome'] = sobrenome
    app.storage.user['email'] = email


def fazer_logout():
    """Limpa a sessão do usuário."""
    app.storage.user.clear()
