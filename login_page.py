"""
Módulo da tela de login do sistema AgendaObras.
Exibe formulário de login ou cadastro do primeiro usuário (admin).
"""

from nicegui import ui, app
from auth_database import AuthDatabase
from config import VERSION


class LoginPage:
    """Tela de login / cadastro inicial do AgendaObras."""

    def __init__(self):
        self.auth_db = AuthDatabase()

        # Configura fundo da página
        ui.query('body').style('background-color: #f5f5f5; margin: 0; min-height: 100vh; padding: 16px; box-sizing: border-box;')

        if not self.auth_db.tem_usuarios():
            self._tela_primeiro_acesso()
        else:
            self._tela_login()

    # ========== Tela de Login ========== #

    def _tela_login(self):
        """Monta formulário de login."""
        with ui.column().classes('absolute-center items-center w-full px-4'):
            with ui.card().style(
                'width: min(94vw, 450px); padding: 30px 22px; border-radius: 12px;'
            ):
                # Título
                with ui.column().classes('w-full items-center').style('margin-bottom: 25px;'):
                    ui.label('🏗️ AgendaObras').style(
                        'font-size: 32px; font-weight: bold; color: #1976d2;'
                    )
                    ui.label('Faça login para continuar').style(
                        'font-size: 14px; color: #666; margin-top: 5px;'
                    )

                # Campos
                email_input = ui.input('E-mail').props('outlined dense').classes('w-full').style('margin-bottom: 10px;')
                senha_input = ui.input('Senha').props('outlined dense type=password').classes('w-full').style('margin-bottom: 5px;')

                # Lembrar-me
                lembrar = ui.checkbox('Lembrar-me').style('margin-bottom: 15px; color: #666;')

                # Mensagem de erro (oculta inicialmente)
                erro_label = ui.label('').style(
                    'color: #f44336; font-size: 13px; display: none; margin-bottom: 10px;'
                )

                def fazer_login():
                    email = email_input.value.strip() if email_input.value else ''
                    senha = senha_input.value if senha_input.value else ''

                    if not email or not senha:
                        erro_label.set_text('Preencha todos os campos.')
                        erro_label.style('display: block;')
                        return

                    usuario = self.auth_db.autenticar(email, senha)
                    if usuario is None:
                        erro_label.set_text('E-mail ou senha incorretos.')
                        erro_label.style('display: block;')
                        return

                    # Salva sessão
                    app.storage.user['autenticado'] = True
                    app.storage.user['user_id'] = usuario['id']
                    app.storage.user['nome'] = usuario['nome']
                    app.storage.user['sobrenome'] = usuario['sobrenome']
                    app.storage.user['email'] = usuario['email']
                    app.storage.user['is_admin'] = usuario['is_admin']

                    # Lembrar-me: persiste via localStorage do navegador
                    if lembrar.value:
                        ui.run_javascript(f'localStorage.setItem("lembrar_email", "{email}")')
                    else:
                        ui.run_javascript('localStorage.removeItem("lembrar_email")')

                    ui.navigate.to('/')

                # Restaura e-mail salvo do localStorage ao carregar a página
                async def restaurar_email():
                    email_salvo = await ui.run_javascript('localStorage.getItem("lembrar_email")')
                    if email_salvo:
                        email_input.set_value(email_salvo)
                        lembrar.set_value(True)

                ui.timer(0.1, restaurar_email, once=True)

                # Botão entrar
                ui.button('Entrar', on_click=fazer_login).classes('w-full').style(
                    'background-color: #1976d2; color: white; font-weight: bold; '
                    'padding: 10px; font-size: 15px; border-radius: 6px;'
                )

                # Enter submete o form
                senha_input.on('keydown.enter', fazer_login)

            # Rodapé discreto
            ui.label(f'AgendaObras v{VERSION}').style(
                'color: #aaa; font-size: 11px; margin-top: 15px;'
            )

    # ========== Tela de Primeiro Acesso (Criar Admin) ========== #

    def _tela_primeiro_acesso(self):
        """Monta formulário de cadastro do primeiro usuário (admin)."""
        with ui.column().classes('absolute-center items-center w-full px-4'):
            with ui.card().style(
                'width: min(94vw, 500px); padding: 30px 22px; border-radius: 12px;'
            ):
                # Título
                with ui.column().classes('w-full items-center').style('margin-bottom: 20px;'):
                    ui.label('🏗️ AgendaObras').style(
                        'font-size: 32px; font-weight: bold; color: #1976d2;'
                    )
                    ui.label('Primeiro acesso — crie o administrador').style(
                        'font-size: 14px; color: #666; margin-top: 5px;'
                    )

                ui.separator().style('margin-bottom: 15px;')

                nome_input = ui.input('Nome').props('outlined dense').classes('w-full').style('margin-bottom: 10px;')
                sobrenome_input = ui.input('Sobrenome').props('outlined dense').classes('w-full').style('margin-bottom: 10px;')
                email_input = ui.input('E-mail').props('outlined dense').classes('w-full').style('margin-bottom: 10px;')
                senha_input = ui.input('Senha').props('outlined dense type=password').classes('w-full').style('margin-bottom: 10px;')
                confirma_input = ui.input('Confirmar senha').props('outlined dense type=password').classes('w-full').style('margin-bottom: 10px;')

                erro_label = ui.label('').style(
                    'color: #f44336; font-size: 13px; display: none; margin-bottom: 10px;'
                )

                def criar_admin():
                    nome = nome_input.value.strip() if nome_input.value else ''
                    sobrenome = sobrenome_input.value.strip() if sobrenome_input.value else ''
                    email = email_input.value.strip() if email_input.value else ''
                    senha = senha_input.value if senha_input.value else ''
                    confirma = confirma_input.value if confirma_input.value else ''

                    # Validações
                    if not all([nome, sobrenome, email, senha, confirma]):
                        erro_label.set_text('Preencha todos os campos.')
                        erro_label.style('display: block;')
                        return

                    if '@' not in email or '.' not in email:
                        erro_label.set_text('Informe um e-mail válido.')
                        erro_label.style('display: block;')
                        return

                    if len(senha) < 4:
                        erro_label.set_text('A senha deve ter pelo menos 4 caracteres.')
                        erro_label.style('display: block;')
                        return

                    if senha != confirma:
                        erro_label.set_text('As senhas não coincidem.')
                        erro_label.style('display: block;')
                        return

                    ok = self.auth_db.criar_usuario(nome, sobrenome, email, senha, is_admin=True)
                    if not ok:
                        erro_label.set_text('Erro ao criar usuário. E-mail já cadastrado?')
                        erro_label.style('display: block;')
                        return

                    ui.notification('Administrador criado com sucesso!', type='positive', timeout=3)
                    ui.navigate.to('/login')

                ui.button('Criar Administrador', on_click=criar_admin).classes('w-full').style(
                    'background-color: #1976d2; color: white; font-weight: bold; '
                    'padding: 10px; font-size: 15px; border-radius: 6px;'
                )

            ui.label(f'AgendaObras v{VERSION}').style(
                'color: #aaa; font-size: 11px; margin-top: 15px;'
            )
