from nicegui import ui, app
from agenda_obras import AgendaObras
from login_page import LoginPage
from auth_middleware import configurar_middleware, verificar_autenticacao, fazer_logout
import sys
import os
import json
from dotenv import load_dotenv

# Corrige paths quando executável
if getattr(sys, 'frozen', False):
    application_path = sys._MEIPASS
else:
    application_path = os.path.dirname(os.path.abspath(__file__))


def _carregar_storage_secret() -> str:
    """Carrega NICEGUI_STORAGE_SECRET do email_config.env (JSON/.env) com fallback para ambiente."""
    caminhos_env = [
        os.path.join(application_path, 'email_config.env'),
        os.path.join(os.getcwd(), 'email_config.env'),
    ]

    for caminho in caminhos_env:
        if os.path.exists(caminho):
            try:
                with open(caminho, 'r', encoding='utf-8') as arquivo:
                    conteudo = arquivo.read()

                # 1) Tenta formato JSON
                try:
                    data = json.loads(conteudo)
                    if isinstance(data, dict):
                        secret_json = data.get('NICEGUI_STORAGE_SECRET') or data.get('nicegui_storage_secret')
                        if secret_json:
                            return str(secret_json).strip().strip('"').strip("'")
                except json.JSONDecodeError:
                    pass
            except Exception:
                pass

            # 2) Tenta formato .env (CHAVE=VALOR)
            load_dotenv(caminho, override=False)
            secret_env_file = os.getenv('NICEGUI_STORAGE_SECRET', '')
            if secret_env_file:
                return secret_env_file.strip().strip('"').strip("'")

    return os.getenv('NICEGUI_STORAGE_SECRET', '').strip().strip('"').strip("'")


NICEGUI_STORAGE_SECRET = _carregar_storage_secret()

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
        host='0.0.0.0',
        port=8080,
        native=False,
        reload=False,
        language='pt-BR',
        favicon='🏗️',
        binding_refresh_interval=0.1,
        storage_secret=NICEGUI_STORAGE_SECRET,
    )
