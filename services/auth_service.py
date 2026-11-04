"""
Middleware de autenticação para o AgendaObras.
Redireciona usuários não autenticados para /login.
"""

from nicegui import app
from starlette.requests import Request
from starlette.responses import RedirectResponse

from db.auth_repo import AuthDatabase

# Rotas que NÃO exigem autenticação
ROTAS_PUBLICAS = {'/login', '/login/', '/_nicegui', '/favicon.ico'}


def configurar_middleware():
    """Registra o middleware HTTP no app NiceGUI."""

    @app.middleware('http')
    async def auth_middleware(request: Request, call_next):
        # Rotas públicas e assets internos passam sem inspeção
        path = request.url.path
        if (path in ROTAS_PUBLICAS
                or path.startswith('/_nicegui')
                or path.startswith('/static')
                or path.startswith('/_event')):
            return await call_next(request)

        # Nota: a verificação de autenticação para páginas NiceGUI (/,
        # /biblioteca etc.) é feita nos decoradores @ui.page via
        # verificar_autenticacao(). Para rotas FastAPI protegidas (ex:
        # /uploads), a sessão HTTP (request.session) é verificada
        # diretamente no handler, pois o SessionMiddleware do NiceGUI
        # só popula request.session DEPOIS que este middleware executa.
        response = await call_next(request)

        # Headers de segurança adicionados a todas as respostas
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        return response


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
