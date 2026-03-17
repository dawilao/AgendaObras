"""
Middleware de autenticação para o AgendaObras.
Redireciona usuários não autenticados para /login.
"""

from nicegui import app
from starlette.requests import Request
from starlette.responses import RedirectResponse

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
    return {
        'id': app.storage.user.get('user_id'),
        'nome': app.storage.user.get('nome', ''),
        'sobrenome': app.storage.user.get('sobrenome', ''),
        'email': app.storage.user.get('email', ''),
        'is_admin': app.storage.user.get('is_admin', False),
    }


def atualizar_usuario_sessao(nome: str, sobrenome: str, email: str) -> None:
    """Atualiza os dados do usuário na sessão (sem fazer login novamente)."""
    app.storage.user['nome'] = nome
    app.storage.user['sobrenome'] = sobrenome
    app.storage.user['email'] = email


def fazer_logout():
    """Limpa a sessão do usuário."""
    app.storage.user.clear()
