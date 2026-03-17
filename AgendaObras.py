from nicegui import ui, app
from agenda_obras import AgendaObras
from login_page import LoginPage
from auth_middleware import configurar_middleware, verificar_autenticacao, fazer_logout
import sys
import os

# Corrige paths quando executável
if getattr(sys, 'frozen', False):
    application_path = sys._MEIPASS
else:
    application_path = os.path.dirname(os.path.abspath(__file__))

# Registra middleware de autenticação
configurar_middleware()


@ui.page('/login')
def pagina_login():
    """Tela de login / primeiro acesso."""
    # Se já autenticado, vai direto para a home
    if verificar_autenticacao():
        ui.navigate.to('/')
        return
    LoginPage()


@ui.page('/')
def index():
    """Página principal — requer autenticação."""
    if not verificar_autenticacao():
        ui.navigate.to('/login')
        return
    AgendaObras()


@ui.page('/logout')
def logout():
    """Encerra a sessão e redireciona para login."""
    fazer_logout()
    ui.navigate.to('/login')


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        title='AgendaObras - Rastreador de Obras',
        port=8080,
        native=False,
        reload=False,
        language='pt-BR',
        favicon='🏗️',
        binding_refresh_interval=0.1,
        storage_secret='agendaobras-secret-key-2026',
    )
