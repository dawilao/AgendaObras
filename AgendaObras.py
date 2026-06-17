"""
AgendaObras — Entry Point
Substitui AgendaObras.py com imports da nova estrutura modular.
"""

import sys
import os
import json
import warnings
from dotenv import load_dotenv
from nicegui import ui, app
from starlette.requests import Request
from starlette.responses import FileResponse, RedirectResponse, Response as StarletteResponse

# Corrige paths quando executável (PyInstaller)
if getattr(sys, 'frozen', False):
    application_path = sys._MEIPASS
else:
    application_path = os.path.dirname(os.path.abspath(__file__))

# Services
from services.auth_service import configurar_middleware, verificar_autenticacao, fazer_logout

# UI Pages
from ui.pages.login import LoginPage
from ui.pages.main import MainPage
from ui.pages.biblioteca import BibliotecaPage
from ui.pages.cotacoes import CotacoesPage


def _carregar_storage_secret() -> str:
    """Carrega NICEGUI_STORAGE_SECRET do email_config.env com fallback para variável de ambiente."""
    caminhos_env = [
        os.path.join(application_path, 'email_config.env'),
        os.path.join(os.getcwd(), 'email_config.env'),
    ]

    for caminho in caminhos_env:
        if os.path.exists(caminho):
            try:
                with open(caminho, 'r', encoding='utf-8') as arquivo:
                    conteudo = arquivo.read()
                try:
                    data = json.loads(conteudo)
                    if isinstance(data, dict):
                        secret = data.get('NICEGUI_STORAGE_SECRET') or data.get('nicegui_storage_secret')
                        if secret:
                            return str(secret).strip().strip('"').strip("'")
                except json.JSONDecodeError:
                    pass
            except Exception:
                pass

            load_dotenv(caminho, override=False)
            secret_env = os.getenv('NICEGUI_STORAGE_SECRET', '')
            if secret_env:
                return secret_env.strip().strip('"').strip("'")

    return os.getenv('NICEGUI_STORAGE_SECRET', '').strip().strip('"').strip("'")


# Pasta de uploads (usada pela rota autenticada abaixo)
from db.biblioteca_repo import PASTA_UPLOADS

# Registra middleware de autenticação
configurar_middleware()


def _validar_storage_secret(secret: str) -> None:
    """Aborta a inicialização se o secret estiver ausente ou fraco em produção."""
    if not secret:
        warnings.warn(
            "\n\n*** SEGURANÇA *** NICEGUI_STORAGE_SECRET não está configurado.\n"
            "Cookies de sessão ficam sem assinatura — sessões podem ser forjadas.\n"
            "Configure a chave em email_config.env antes de publicar o sistema.\n",
            RuntimeWarning,
            stacklevel=2,
        )
    elif len(secret) < 16:
        warnings.warn(
            "\n\n*** SEGURANÇA *** NICEGUI_STORAGE_SECRET tem menos de 16 caracteres.\n"
            "Use uma chave aleatória forte (ex: python -c \"import secrets; print(secrets.token_hex(32))\").\n",
            RuntimeWarning,
            stacklevel=2,
        )


@app.get('/uploads/{filename}')
async def serve_upload(request: Request, filename: str):
    """Serve arquivos de upload apenas para sessões autenticadas."""
    # SessionMiddleware já processou a requisição aqui; request.session['id']
    # é a chave do storage do NiceGUI (PersistentDict em app.storage._users).
    session_id = request.session.get('id')
    if not session_id:
        return RedirectResponse('/login', status_code=302)

    user_storage = app.storage._users.get(session_id, {})
    if not user_storage.get('autenticado'):
        return RedirectResponse('/login', status_code=302)

    # Previne path traversal: aceita somente o nome base do arquivo
    safe_name = os.path.basename(filename)
    if not safe_name or safe_name != filename:
        return StarletteResponse(status_code=400)

    file_path = os.path.join(PASTA_UPLOADS, safe_name)
    if not os.path.isfile(file_path):
        return StarletteResponse(status_code=404)

    return FileResponse(file_path)


@ui.page('/login')
def pagina_login():
    if verificar_autenticacao():
        ui.navigate.to('/')
        return
    LoginPage()


@ui.page('/')
def index():
    if not verificar_autenticacao():
        ui.navigate.to('/login')
        return
    MainPage()


@ui.page('/logout')
def logout():
    fazer_logout()
    ui.navigate.to('/login')


@ui.page('/biblioteca')
def pagina_biblioteca():
    if not verificar_autenticacao():
        ui.navigate.to('/login')
        return
    BibliotecaPage()


@ui.page('/cotacoes')
def pagina_cotacoes():
    if not verificar_autenticacao():
        ui.navigate.to('/login')
        return
    CotacoesPage()


if __name__ in {"__main__", "__mp_main__"}:
    _secret = _carregar_storage_secret()
    _validar_storage_secret(_secret)
    ui.run(
        title='AgendaObras - Rastreador de Obras',
        host='0.0.0.0',
        port=8080,
        native=False,
        reload=False,
        language='pt-BR',
        favicon='🏗️',
        binding_refresh_interval=0.1,
        storage_secret=_secret,
    )
