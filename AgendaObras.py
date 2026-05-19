"""
AgendaObras — Entry Point
Substitui AgendaObras.py com imports da nova estrutura modular.
"""

import sys
import os
import json
from dotenv import load_dotenv
from nicegui import ui

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


# Registra middleware de autenticação
configurar_middleware()


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


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        title='AgendaObras - Rastreador de Obras',
        host='0.0.0.0',
        port=8083,
        native=False,
        reload=False,
        language='pt-BR',
        favicon='🏗️',
        binding_refresh_interval=0.1,
        storage_secret=_carregar_storage_secret(),
    )
