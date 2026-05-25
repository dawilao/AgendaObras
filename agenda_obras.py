"""
Módulo da interface principal do sistema AgendaObras.
AgendaObras herda de três Mixins que isolam os componentes de UI:
  - ObraCardMixin      → ui/components/obra_card.py
  - ObraDialogsMixin   → ui/components/obra_dialogs.py
  - AdminDialogsMixin  → ui/components/admin_dialogs.py
"""

from nicegui import ui, app
import datetime
import os
import sqlite3
from secrets import randbelow
from typing import Dict, Optional, Tuple
from db import Database, TAREFAS_COM_DIAS_UTEIS
from services.email_service import EmailService
from utils.obras_helper import ObrasHelper
from services.notificador import NotificadorPrazos
from core.version_checker import VersionChecker
from core.config import VERSION
from core.error_logger import log_error
from services.auth_service import obter_usuario_logado, atualizar_usuario_sessao
from db.auth_repo import AuthDatabase
from db.contratos_repo import ContratosDatabase
from ui.components.obra_card import ObraCardMixin
from ui.components.obra_dialogs import ObraDialogsMixin
from ui.components.admin_dialogs import AdminDialogsMixin


class AgendaObras(ObraCardMixin, ObraDialogsMixin, AdminDialogsMixin):
    def __init__(self):
        self.title = "AgendaObras"
        self.description = "Rastreador de Demandas de Engenharia"
        self.timeout_padrao = 3

        # Inicializa banco de dados
        self.db = Database()
        self.contratos_db = ContratosDatabase()
        self.helper = ObrasHelper()

        # Inicializa serviços
        self.email_service = EmailService(self.db)

        # Inicializa notificador de prazos
        self.notificador = NotificadorPrazos(self.db, self.email_service)
        self.notificador.iniciar_verificacao()

        # Container do body (para atualização dinâmica)
        self.body_container = None
        self.filtro_pesquisa = ""

        # Verifica atualização antes de construir UI
        self.verificar_atualizacao()

        # Ajustes globais de responsividade
        self.configurar_layout_responsivo()

        # Construção da UI
        self.header()
        self.body()
        self.footer()

    def configurar_layout_responsivo(self):
        """Injeta ajustes CSS para melhorar a experiência em celular e notebook."""
        ui.add_head_html('''
        <style>
            .responsive-dialog {
                width: min(96vw, 900px) !important;
                max-width: 96vw !important;
            }

            .responsive-dialog-sm {
                width: min(96vw, 560px) !important;
                max-width: 96vw !important;
            }

            .responsive-dialog-lg {
                width: min(96vw, 980px) !important;
                max-width: 96vw !important;
            }

            @media (max-width: 768px) {
                .agenda-header {
                    padding: 10px !important;
                }

                .agenda-title {
                    margin-right: 8px !important;
                    font-size: 22px !important;
                }
            }

            /* Grid de obras responsivo */
            .obras-grid {
                display: grid;
                gap: 1rem;
                grid-template-columns: repeat(3, minmax(0, 1fr));
            }

            @media (max-width: 1100px) {
                .obras-grid {
                    grid-template-columns: repeat(2, minmax(0, 1fr));
                }
            }

            @media (max-width: 640px) {
                .obras-grid {
                    grid-template-columns: 1fr;
                }
            }
        </style>
        ''')

    # ========== Métodos Auxiliares ========== #
    def notificar(self, mensagem: str, tipo: str = 'info', timeout: int = None):
        """Exibe notificação na aplicação"""
        if timeout is None:
            timeout = self.timeout_padrao
        try:
            ui.notification(mensagem, type=tipo, timeout=timeout)
        except RuntimeError:
            pass

    def calcular_dias_restantes_exibicao(self, item: Dict) -> int:
        """Calcula dias restantes/atraso para exibição, respeitando tarefas em dias úteis."""
        data_limite = item.get('data_limite')
        if not data_limite:
            return 0

        if item.get('descricao') in TAREFAS_COM_DIAS_UTEIS:
            return self.helper.calcular_dias_uteis_restantes(data_limite)

        return self.helper.calcular_dias_restantes(data_limite)

    def usa_dias_uteis_exibicao(self, item: Dict) -> bool:
        """Indica se a tarefa deve exibir contagem em dias úteis."""
        return item.get('descricao') in TAREFAS_COM_DIAS_UTEIS

    def formatar_info_reiteracao(self, item: Dict) -> str:
        """Formata informações de reiteração para exibição"""
        tentativas = item.get('tentativas_reiteracao', 0)
        ultima_notif = item.get('ultima_notificacao')

        if not tentativas or tentativas == 0 or not ultima_notif:
            return ''

        try:
            if ' ' in ultima_notif:
                dt = datetime.datetime.strptime(ultima_notif, '%Y-%m-%d %H:%M:%S')
                data_notif_formatada = dt.strftime('%d/%m/%Y às %H:%M')
            else:
                dt = datetime.datetime.strptime(ultima_notif, '%Y-%m-%d')
                data_notif_formatada = dt.strftime('%d/%m/%Y')
        except Exception as e:
            log_error(e, "agenda_obras", "Parse de data em formatar_info_reiteracao")
            data_notif_formatada = ultima_notif

        if tentativas == 1:
            return f'📧 1ª reiteração enviada em {data_notif_formatada}'
        elif tentativas == 2:
            return f'📧 2ª reiteração enviada em {data_notif_formatada}'
        else:
            return f'🆘 Alertas críticos diários (última em {data_notif_formatada})'

    def _obter_permissoes_usuario(self) -> Dict:
        """Obtém permissões de visualização de contratos para o usuário logado."""
        usuario = obter_usuario_logado()
        is_admin = bool(usuario.get('is_admin'))
        user_id = usuario.get('id')

        contratos_vinculados = []
        if not is_admin and user_id:
            contratos_vinculados = self.contratos_db.listar_contratos_usuario(user_id)

        return {
            'usuario': usuario,
            'is_admin': is_admin,
            'user_id': user_id,
            'contratos_vinculados': contratos_vinculados,
        }

    def _usuario_pode_acessar_contrato(self, contrato_nome: str) -> bool:
        """Valida se o usuário logado pode acessar um contrato específico."""
        permissoes = self._obter_permissoes_usuario()
        if permissoes['is_admin']:
            return True

        contrato_normalizado = (contrato_nome or '').strip()
        return contrato_normalizado in set(permissoes['contratos_vinculados'])

    def _normalizar_nome_contrato(self, nome: str) -> str:
        return (nome or '').strip()

    def _conexao_obras_contratos(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db.db_name, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=30000')
        return conn

    def _contrato_existe_catalogo(self, nome: str) -> bool:
        nome = self._normalizar_nome_contrato(nome)
        if not nome:
            return False
        return nome in set(self.contratos_db.listar_contratos())

    def _contar_uso_contrato_catalogo(self, contrato_nome: str) -> Dict[str, int]:
        contrato_nome = self._normalizar_nome_contrato(contrato_nome)

        conn_contratos = None
        conn_obras = None
        try:
            conn_contratos = self.contratos_db.get_connection()
            cursor_contratos = conn_contratos.cursor()
            cursor_contratos.execute(
                'SELECT COUNT(*) AS total FROM contrato_usuarios WHERE contrato_nome = ?',
                (contrato_nome,),
            )
            vinculos_usuarios = int(cursor_contratos.fetchone()['total'])

            obras_cliente = 0
            if os.path.exists(self.db.db_name):
                conn_obras = self._conexao_obras_contratos()
                cursor_obras = conn_obras.cursor()
                cursor_obras.execute(
                    'SELECT COUNT(*) AS total FROM obras WHERE cliente = ?',
                    (contrato_nome,),
                )
                obras_cliente = int(cursor_obras.fetchone()['total'])

            return {
                'vinculos_usuarios': vinculos_usuarios,
                'obras_cliente': obras_cliente,
                'total': vinculos_usuarios + obras_cliente,
            }
        finally:
            if conn_contratos:
                conn_contratos.close()
            if conn_obras:
                conn_obras.close()

    def _adicionar_contrato_catalogo(self, nome: str) -> Tuple[bool, str]:
        nome = self._normalizar_nome_contrato(nome)
        if not nome:
            return False, 'Nome do contrato é obrigatório.'

        if self._contrato_existe_catalogo(nome):
            return False, f'Contrato já existe: "{nome}"'

        conn = None
        try:
            conn = self.contratos_db.get_connection()
            cursor = conn.cursor()
            cursor.execute('INSERT INTO contratos (nome) VALUES (?)', (nome,))
            conn.commit()
            return True, f'Contrato "{nome}" adicionado com sucesso.'
        except sqlite3.IntegrityError:
            return False, f'Contrato já existe: "{nome}"'
        except Exception as e:
            if conn:
                conn.rollback()
            log_error(e, 'agenda_obras', f'Adicionar contrato via UI: {nome}')
            return False, f'Erro ao adicionar contrato: {e}'
        finally:
            if conn:
                conn.close()

    def _editar_contrato_catalogo(self, old_nome: str, new_nome: str) -> Tuple[bool, str]:
        old_nome = self._normalizar_nome_contrato(old_nome)
        new_nome = self._normalizar_nome_contrato(new_nome)

        if not old_nome or not new_nome:
            return False, 'Informe nomes válidos para edição do contrato.'

        if old_nome == new_nome:
            return True, 'Nome antigo e novo são iguais. Nenhuma alteração necessária.'

        if not self._contrato_existe_catalogo(old_nome):
            return False, f'Contrato não encontrado: "{old_nome}"'

        if self._contrato_existe_catalogo(new_nome):
            return False, f'Já existe outro contrato com o nome de destino: "{new_nome}"'

        conn_contratos = None
        conn_obras = None
        try:
            conn_contratos = self.contratos_db.get_connection()
            cursor_contratos = conn_contratos.cursor()

            cursor_contratos.execute(
                'UPDATE contratos SET nome = ? WHERE nome = ?',
                (new_nome, old_nome),
            )
            cursor_contratos.execute(
                'UPDATE contrato_usuarios SET contrato_nome = ? WHERE contrato_nome = ?',
                (new_nome, old_nome),
            )

            obras_alteradas = 0
            if os.path.exists(self.db.db_name):
                conn_obras = self._conexao_obras_contratos()
                cursor_obras = conn_obras.cursor()
                cursor_obras.execute(
                    'UPDATE obras SET cliente = ? WHERE cliente = ?',
                    (new_nome, old_nome),
                )
                obras_alteradas = cursor_obras.rowcount

            conn_contratos.commit()
            if conn_obras:
                conn_obras.commit()

            return True, f'Contrato renomeado para "{new_nome}". Obras atualizadas: {obras_alteradas}.'
        except sqlite3.IntegrityError as e:
            if conn_contratos:
                conn_contratos.rollback()
            if conn_obras:
                conn_obras.rollback()
            log_error(e, 'agenda_obras', f'Editar contrato via UI (integridade): {old_nome} -> {new_nome}')
            return False, 'Falha de integridade ao renomear contrato. Verifique duplicidade de vínculos.'
        except Exception as e:
            if conn_contratos:
                conn_contratos.rollback()
            if conn_obras:
                conn_obras.rollback()
            log_error(e, 'agenda_obras', f'Editar contrato via UI: {old_nome} -> {new_nome}')
            return False, f'Erro ao editar contrato: {e}'
        finally:
            if conn_contratos:
                conn_contratos.close()
            if conn_obras:
                conn_obras.close()

    def _remover_contrato_catalogo(self, nome: str, replace_with: Optional[str] = None) -> Tuple[bool, str]:
        nome = self._normalizar_nome_contrato(nome)
        replace_with = self._normalizar_nome_contrato(replace_with) if replace_with else ''

        if not nome:
            return False, 'Nome do contrato é obrigatório para remoção.'

        if not self._contrato_existe_catalogo(nome):
            return False, f'Contrato não encontrado: "{nome}"'

        if replace_with:
            if replace_with == nome:
                return False, '--replace-with deve ser diferente do contrato removido.'
            if not self._contrato_existe_catalogo(replace_with):
                return False, f'Contrato de substituição não existe: "{replace_with}"'

        uso = self._contar_uso_contrato_catalogo(nome)
        if uso['total'] > 0 and not replace_with:
            return (
                False,
                f'Contrato em uso: {uso["vinculos_usuarios"]} vínculos de usuários e {uso["obras_cliente"]} obras. '
                'Selecione um contrato substituto para remover.',
            )

        conn_contratos = None
        conn_obras = None
        try:
            conn_contratos = self.contratos_db.get_connection()
            cursor_contratos = conn_contratos.cursor()

            if replace_with:
                cursor_contratos.execute(
                    '''
                    DELETE FROM contrato_usuarios
                    WHERE contrato_nome = ?
                      AND usuario_id IN (
                          SELECT usuario_id FROM contrato_usuarios WHERE contrato_nome = ?
                      )
                    ''',
                    (replace_with, nome),
                )
                cursor_contratos.execute(
                    'UPDATE contrato_usuarios SET contrato_nome = ? WHERE contrato_nome = ?',
                    (replace_with, nome),
                )

            obras_alteradas = 0
            if os.path.exists(self.db.db_name):
                conn_obras = self._conexao_obras_contratos()
                cursor_obras = conn_obras.cursor()
                if replace_with:
                    cursor_obras.execute(
                        'UPDATE obras SET cliente = ? WHERE cliente = ?',
                        (replace_with, nome),
                    )
                    obras_alteradas = cursor_obras.rowcount

            cursor_contratos.execute('DELETE FROM contratos WHERE nome = ?', (nome,))

            conn_contratos.commit()
            if conn_obras:
                conn_obras.commit()

            if replace_with:
                return (
                    True,
                    f'Contrato "{nome}" removido com migração para "{replace_with}". '
                    f'Obras migradas: {obras_alteradas}.',
                )

            return True, f'Contrato "{nome}" removido com sucesso.'
        except sqlite3.IntegrityError as e:
            if conn_contratos:
                conn_contratos.rollback()
            if conn_obras:
                conn_obras.rollback()
            log_error(e, 'agenda_obras', f'Remover contrato via UI (integridade): {nome} -> {replace_with}')
            return False, 'Falha de integridade ao remover contrato. Verifique vínculos existentes.'
        except Exception as e:
            if conn_contratos:
                conn_contratos.rollback()
            if conn_obras:
                conn_obras.rollback()
            log_error(e, 'agenda_obras', f'Remover contrato via UI: {nome} -> {replace_with}')
            return False, f'Erro ao remover contrato: {e}'
        finally:
            if conn_contratos:
                conn_contratos.close()
            if conn_obras:
                conn_obras.close()

    def verificar_atualizacao(self):
        """Verifica se há atualização disponível e exige atualização se necessário"""
        try:
            checker = VersionChecker()
            info = checker.get_version_info()

            if info['needs_update']:
                self.mostrar_dialogo_atualizacao(info)
        except Exception as e:
            log_error(e, "agenda_obras", "Verificação de atualização ao iniciar")

    def mostrar_dialogo_atualizacao(self, info: Dict):
        """Mostra diálogo de atualização (obrigatório ou opcional)"""
        force_update = info.get('force_update', False)
        online_version = info.get('online_version', 'desconhecida')
        current_version = info.get('current_version', VERSION)
        download_url = info.get('download_url', '')
        release_notes = info.get('release_notes', '')
        changelog = info.get('changelog', [])

        with ui.dialog().props('persistent' if force_update else '') as dialog, ui.card().classes('responsive-dialog-sm').style('padding: 20px;'):
            with ui.row().classes('w-full items-center'):
                if force_update:
                    ui.icon('warning', size='48px').style('color: #f44336;')
                    ui.label('⚠️ ATUALIZAÇÃO OBRIGATÓRIA').style('font-size: 22px; font-weight: bold; color: #f44336; margin-left: 10px;')
                else:
                    ui.icon('info', size='48px').style('color: #2196f3;')
                    ui.label('ℹ️ Atualização Disponível').style('font-size: 22px; font-weight: bold; color: #2196f3; margin-left: 10px;')

            ui.separator()

            with ui.column().classes('w-full').style('padding: 15px 0;'):
                ui.label(f'Versão atual: {current_version}').style('font-size: 16px;')
                ui.label(f'Nova versão: {online_version}').style('font-size: 16px; font-weight: bold; color: #4caf50;')

                if force_update:
                    ui.label('⚠️ Esta atualização é obrigatória para continuar usando o sistema.').style(
                        'font-size: 14px; color: #f44336; margin-top: 10px; padding: 10px; background-color: #ffebee; border-radius: 4px;'
                    )

                if release_notes:
                    ui.separator().style('margin: 15px 0;')
                    ui.label('📝 Notas de Lançamento:').style('font-size: 16px; font-weight: bold; margin-bottom: 10px;')
                    ui.label(release_notes).style('font-size: 14px; line-height: 1.6;')

                if changelog:
                    ui.separator().style('margin: 15px 0;')
                    ui.label('📋 Novidades:').style('font-size: 16px; font-weight: bold; margin-bottom: 10px;')
                    with ui.column().classes('w-full'):
                        for item in changelog:
                            with ui.row().classes('items-start'):
                                ui.label('•').style('margin-right: 8px; font-size: 14px;')
                                ui.label(item).style('font-size: 14px; line-height: 1.6;')

            ui.separator()

            with ui.row().classes('w-full justify-end').style('margin-top: 15px;'):
                if not force_update:
                    ui.button('Lembrar Depois', on_click=lambda: dialog.close()).props('flat').style('color: #666;')

                if download_url:
                    ui.button(
                        '⬇️ Baixar Atualização' if force_update else 'Baixar Atualização',
                        on_click=lambda: ui.navigate.to(download_url, new_tab=True)
                    ).props('color=primary' if force_update else 'color=positive')
                else:
                    ui.button('OK', on_click=lambda: dialog.close()).props('color=primary')

        dialog.open()

        if force_update:
            ui.notification(
                f'⚠️ Atualização obrigatória disponível! Versão {online_version}',
                type='negative',
                timeout=0,
                position='top'
            )

    # ========== UI ========== #
    def header(self):
        """Cabeçalho da aplicação"""
        usuario = obter_usuario_logado()

        with ui.header().classes('items-center agenda-header').style('background-color: #1976d2; padding: 15px; gap: 8px; flex-wrap: nowrap;'):
            ui.label('🏗️ AgendaObras').classes('agenda-title').style(
                'font-size: clamp(22px, 2.4vw, 28px); color: white; font-weight: bold; margin-right: 10px;'
            )

            # Menu mobile (hamburger)
            with ui.dialog() as mobile_menu_dialog, ui.card().classes('responsive-dialog-sm').style('padding: 16px; max-height: 85vh; overflow-y: auto;'):
                ui.label('Menu').style('font-size: 18px; font-weight: bold; color: #1976d2; margin-bottom: 10px;')

                mobile_search_input = ui.input(placeholder='🔍 Pesquisar obras...').classes('w-full').props('outlined dense')
                mobile_search_input.on(
                    'keydown.enter',
                    lambda: [self.pesquisa(mobile_search_input.value), mobile_menu_dialog.close()]
                )

                with ui.row().classes('w-full gap-2').style('margin-top: 8px;'):
                    ui.button(
                        'Pesquisar',
                        on_click=lambda: [self.pesquisa(mobile_search_input.value), mobile_menu_dialog.close()]
                    ).classes('w-full').props('outline color=primary')

                ui.separator().style('margin: 10px 0;')

                ui.button('➕ Nova Obra', on_click=lambda: [mobile_menu_dialog.close(), self.nova_entrada()]).classes('w-full').props('flat').style('justify-content: flex-start;')
                ui.button('🔄 Atualizar', on_click=lambda: [mobile_menu_dialog.close(), self.atualizar_dados()]).classes('w-full').props('flat').style('justify-content: flex-start;')

                if usuario.get('is_admin'):
                    ui.button('👥 Usuários', on_click=lambda: [mobile_menu_dialog.close(), self.abrir_gerenciar_usuarios()]).classes('w-full').props('flat').style('justify-content: flex-start;')
                    ui.button('📄 Contratos', on_click=lambda: [mobile_menu_dialog.close(), self.abrir_gerenciar_contratos()]).classes('w-full').props('flat').style('justify-content: flex-start;')

                ui.separator().style('margin: 10px 0;')
                ui.button(
                    f'👤 {usuario.get("nome", "")} {usuario.get("sobrenome", "")}',
                    on_click=lambda: [mobile_menu_dialog.close(), self.abrir_perfil_usuario()]
                ).classes('w-full').props('flat').style('justify-content: flex-start;')
                ui.button('Sair', on_click=lambda: [mobile_menu_dialog.close(), ui.navigate.to('/logout')]).classes('w-full').props('flat').style('justify-content: flex-start; color: #d32f2f;')

            ui.button(icon='menu', on_click=mobile_menu_dialog.open).classes('sm:hidden ml-auto').props('flat round text-color=white').tooltip('Abrir menu')

            # Ações desktop
            with ui.row().classes('items-center gap-2 max-sm:hidden ml-4 flex-1 min-w-0').style('flex-wrap: nowrap;'):
                ui.button('➕ Nova Obra', on_click=self.nova_entrada).props('flat text-color=white').style(
                    'font-weight: bold; margin-right: 10px; font-size: 14px;'
                )

                self.input_pesquisa = ui.input(placeholder='🔍 Pesquisar obras...').classes('w-80').props('outlined dense').style(
                    'background-color: white; border-radius: 4px; margin-right: 10px;'
                )
                self.input_pesquisa.on('input', lambda: self.pesquisa(self.input_pesquisa.value))
                self.input_pesquisa.on('keydown.enter', lambda: self.pesquisa(self.input_pesquisa.value))

                ui.space()

                ui.button('🔄 Atualizar', on_click=self.atualizar_dados).props('flat text-color=white').style(
                    'font-weight: bold; font-size: 14px;'
                )

                if usuario.get('is_admin'):
                    with ui.button('⚙️ Administração').props('flat text-color=white').style(
                        'font-weight: bold; margin-left: 5px; font-size: 14px;'
                    ):
                        with ui.menu():
                            ui.menu_item('👥 Usuários', on_click=self.abrir_gerenciar_usuarios)
                            ui.menu_item('📄 Contratos', on_click=self.abrir_gerenciar_contratos)

                with ui.row().classes('items-center gap-2').style('margin-left: 10px;'):
                    self.user_button = ui.button(
                        f'👤 {usuario.get("nome", "")} {usuario.get("sobrenome", "")}',
                        on_click=self.abrir_perfil_usuario
                    ).props('flat text-color=white').style(
                        'font-size: 14px; font-weight: 500;'
                    )
                    ui.button('Sair', on_click=lambda: ui.navigate.to('/logout')).props('flat dense text-color=white').style(
                        'font-size: 13px; font-weight: bold;'
                    )

    def abrir_perfil_usuario(self):
        """Abre diálogo de perfil do usuário logado com opções para editar dados pessoais e senha."""
        usuario = obter_usuario_logado()
        user_id = usuario.get('id')

        if not user_id:
            ui.notification('Sessão inválida. Faça login novamente.', type='negative', timeout=3)
            return

        auth_db = AuthDatabase()

        with ui.dialog() as dialog, ui.card().classes('responsive-dialog-sm').style('padding: 20px; max-height: 90vh; overflow-y: auto;'):
            ui.label('👤 Meu Perfil').style(
                'font-size: 24px; font-weight: bold; color: #1976d2; margin-bottom: 5px;'
            )
            ui.label(f'Gerencie suas informações pessoais').style(
                'font-size: 13px; color: #999; margin-bottom: 20px;'
            )

            ui.separator()

            ui.label('📋 Informações Pessoais').style(
                'font-size: 16px; font-weight: bold; margin-top: 15px; color: #1976d2;'
            )

            nome_input = ui.input('Nome *', value=usuario.get('nome', '')).props('outlined dense').classes('w-full').style('margin-bottom: 8px;')
            sobrenome_input = ui.input('Sobrenome *', value=usuario.get('sobrenome', '')).props('outlined dense').classes('w-full').style('margin-bottom: 8px;')
            email_input = ui.input('E-mail *', value=usuario.get('email', '')).props('outlined dense').classes('w-full').style('margin-bottom: 12px;')

            ui.separator().style('margin: 15px 0;')

            ui.label('🔒 Segurança').style(
                'font-size: 16px; font-weight: bold; color: #1976d2;'
            )

            senha_atual_input = ui.input('Senha atual *', value='').props('outlined dense type=password').classes('w-full').style('margin-bottom: 8px;')
            nova_senha_input = ui.input('Nova senha', value='', placeholder='Deixe em branco para não alterar').props('outlined dense type=password').classes('w-full').style('margin-bottom: 8px;')
            confirma_senha_input = ui.input('Confirmar nova senha', value='').props('outlined dense type=password').classes('w-full').style('margin-bottom: 12px;')

            ui.label('💡 A senha atual é obrigatória para salvar qualquer alteração.').style(
                'font-size: 12px; color: #1976d2; font-style: italic; margin-bottom: 12px;'
            )

            erro_label = ui.label('').style('color: #f44336; font-size: 13px; display: none; margin-bottom: 12px; padding: 8px; background-color: #ffebee; border-radius: 4px;')
            sucesso_label = ui.label('').style('color: #4caf50; font-size: 13px; display: none; margin-bottom: 12px; padding: 8px; background-color: #e8f5e9; border-radius: 4px;')

            def salvar_alteracoes():
                """Valida e salva as alterações do perfil."""
                nome = nome_input.value.strip() if nome_input.value else ''
                sobrenome = sobrenome_input.value.strip() if sobrenome_input.value else ''
                email = email_input.value.strip() if email_input.value else ''
                senha_atual = senha_atual_input.value if senha_atual_input.value else ''
                nova_senha = nova_senha_input.value if nova_senha_input.value else ''
                confirma_senha = confirma_senha_input.value if confirma_senha_input.value else ''

                erro_label.style('display: none;')
                sucesso_label.style('display: none;')

                if not all([nome, sobrenome, email]):
                    erro_label.set_text('⚠️ Nome, sobrenome e e-mail são obrigatórios.')
                    erro_label.style('display: block;')
                    return

                if not senha_atual:
                    erro_label.set_text('⚠️ Você deve informar a senha atual para salvar alterações.')
                    erro_label.style('display: block;')
                    return

                if not auth_db.verificar_senha_atual(user_id, senha_atual):
                    erro_label.set_text('❌ Senha atual incorreta.')
                    erro_label.style('display: block;')
                    return

                if nova_senha or confirma_senha:
                    if not nova_senha:
                        erro_label.set_text('⚠️ Informe a nova senha.')
                        erro_label.style('display: block;')
                        return

                    if len(nova_senha) < 4:
                        erro_label.set_text('⚠️ A nova senha deve ter pelo menos 4 caracteres.')
                        erro_label.style('display: block;')
                        return

                    if nova_senha != confirma_senha:
                        erro_label.set_text('❌ A confirmação da nova senha não confere.')
                        erro_label.style('display: block;')
                        return

                try:
                    auth_db.atualizar_usuario(user_id, nome, sobrenome, email)

                    atualizar_usuario_sessao(nome, sobrenome, email)

                    if hasattr(self, 'user_button'):
                        self.user_button.text = f'👤 {nome} {sobrenome}'

                    if nova_senha:
                        auth_db.redefinir_senha(user_id, nova_senha)
                        sucesso_label.set_text('✅ Perfil e senha atualizados com sucesso!')
                    else:
                        sucesso_label.set_text('✅ Perfil atualizado com sucesso!')

                    sucesso_label.style('display: block;')

                    async def fechar_apos_delay():
                        import asyncio
                        await asyncio.sleep(1.5)
                        dialog.close()

                    import asyncio
                    try:
                        asyncio.create_task(fechar_apos_delay())
                    except:
                        ui.timer(1.5, lambda: dialog.close(), once=True)

                except Exception as e:
                    log_error(e, "agenda_obras", "Atualizar perfil do usuário")
                    erro_label.set_text(f'❌ Erro ao salvar: {str(e)}')
                    erro_label.style('display: block;')

            ui.separator()

            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('Cancelar', on_click=dialog.close).props('flat').style('color: #666;')
                ui.button('💾 Salvar Alterações', on_click=salvar_alteracoes).style(
                    'background-color: #1976d2; color: white; font-weight: bold;'
                )

        dialog.open()

    def footer(self):
        """Rodapé da aplicação"""
        with ui.footer().style('background-color: #f5f5f5; padding: 15px; text-align: center;'):
            ui.label(f'AgendaObras v{VERSION} | © {datetime.datetime.now().year}').style(
                'color: #666; font-size: 12px;'
            )

    def body(self):
        """Corpo principal com grid de obras"""
        with ui.column().classes('w-full p-0'):
            with ui.card().classes('w-full').style('background-color: #fafafa;'):
                ui.label(f'{len(self.db.listar_obras())} Obras Cadastradas').style('font-size: 20px; font-weight: bold; margin-bottom: 10px;')

                self.body_container = ui.column().classes('w-full')

                self.renderizar_obras()

    def renderizar_obras(self):
        """Renderiza o grid de cards das obras"""
        self.body_container.clear()

        with self.body_container:
            if self.filtro_pesquisa:
                with ui.card().classes('w-full').style('background-color: #e3f2fd; padding: 10px; margin-bottom: 10px;'):
                    with ui.row().classes('w-full items-center justify-between'):
                        with ui.row().classes('items-center gap-2'):
                            ui.icon('search').style('color: #1976d2; font-size: 20px;')
                            ui.label(f'Pesquisando por: "{self.filtro_pesquisa}"').style('color: #1976d2; font-weight: bold;')
                        ui.button('✕ Limpar pesquisa', on_click=self.atualizar_dados).props('flat').style('color: #1976d2;')

            permissoes = self._obter_permissoes_usuario()

            if permissoes['is_admin']:
                obras = self.db.listar_obras(self.filtro_pesquisa if self.filtro_pesquisa else None)
            else:
                obras = self.db.listar_obras_por_contratos(
                    permissoes['contratos_vinculados'],
                    self.filtro_pesquisa if self.filtro_pesquisa else None,
                )

            if not obras:
                with ui.card().classes('w-full').style('padding: 40px; text-align: center;'):
                    if self.filtro_pesquisa:
                        ui.icon('search_off').style('font-size: 48px; color: #bbb; margin-bottom: 10px;')
                        ui.label('Nenhuma obra encontrada').style('font-size: 18px; color: #999;')
                        ui.label(f'Não há obras que correspondam a "{self.filtro_pesquisa}"').style('font-size: 14px; color: #bbb;')
                        ui.button('Limpar pesquisa', on_click=self.atualizar_dados).props('outlined').style('margin-top: 15px;')
                    else:
                        if not permissoes['is_admin'] and not permissoes['contratos_vinculados']:
                            ui.label('Nenhum contrato vinculado ao seu usuário').style('font-size: 18px; color: #999;')
                            ui.label('Solicite a um administrador o vínculo com um contrato.').style('font-size: 14px; color: #bbb;')
                        else:
                            ui.label('Nenhuma obra cadastrada').style('font-size: 18px; color: #999;')
                            ui.label('Clique em "Nova Obra" para começar').style('font-size: 14px; color: #bbb;')
            else:
                total = len(obras)
                if self.filtro_pesquisa:
                    ui.label(f'{total} obra{"s" if total != 1 else ""} encontrada{"s" if total != 1 else ""}').style(
                        'font-size: 14px; color: #666; margin-bottom: 10px; font-weight: 500;'
                    )

                with ui.grid(columns='repeat(auto-fit, minmax(min(100%, 380px), 1fr))').classes('w-full gap-4'):
                    for obra in obras:
                        self.criar_card_obra(obra)

    # ========== Funções dos botões ========== #
    def pesquisa(self, texto: str):
        """Função de pesquisa com filtro em tempo real"""
        self.filtro_pesquisa = texto.strip()
        self.renderizar_obras()

    def atualizar_dados(self):
        """Atualiza a lista de obras"""
        self.filtro_pesquisa = ""
        if hasattr(self, 'input_pesquisa'):
            self.input_pesquisa.value = ""
        self.notificar('🔄 Dados atualizados!', tipo='info')
        self.renderizar_obras()
