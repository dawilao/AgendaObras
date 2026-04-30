"""
Módulo da interface principal do sistema AgendaObras.
Contém a classe AgendaObras com toda a lógica da interface gráfica usando NiceGUI.
"""

from nicegui import ui, app
import datetime
import os
import sqlite3
from secrets import randbelow
from typing import Dict, List, Optional, Tuple
from database import Database, TAREFAS_COM_DIAS_UTEIS
from email_service import EmailService
from obras_helper import ObrasHelper
from gerador_tarefas_recorrentes import GeradorTarefasRecorrentes
from notificador_prazos import NotificadorPrazos
from version_checker import VersionChecker
from config import VERSION
from error_logger import log_error
from auth_middleware import obter_usuario_logado, atualizar_usuario_sessao
from auth_database import AuthDatabase
from contratos_database import ContratosDatabase

# Valores de status padrão (usado tanto no banco quanto na interface)
STATUS_OPTIONS = ['Não Iniciada', 'Em Andamento', 'Atrasada', 'Concluída']


class AgendaObras:
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
        self.gerador_recorrentes = GeradorTarefasRecorrentes(self.db)
        
        # Inicializa notificador de prazos
        self.notificador = NotificadorPrazos(self.db, self.email_service, self.gerador_recorrentes)
        self.notificador.iniciar_verificacao()
        
        # Container do body (para atualização dinâmica)
        self.body_container = None
        self.filtro_pesquisa = ""
        
        # Verifica atualização antes de construir UI
        self.verificar_atualizacao()
        
        # Construção da UI
        self.header()
        self.body()
        self.footer()
    
    # ========== Métodos Auxiliares ========== #
    def notificar(self, mensagem: str, tipo: str = 'info', timeout: int = None):
        """Exibe notificação na aplicação"""
        if timeout is None:
            timeout = self.timeout_padrao
        try:
            ui.notification(mensagem, type=tipo, timeout=timeout)
        except RuntimeError:
            # Ignora erro de contexto deletado
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
        
        # Verifica se há dados de reiteração
        if not tentativas or tentativas == 0 or not ultima_notif:
            return ''
        
        try:
            # Verifica se tem horário (formato: YYYY-MM-DD HH:MM:SS)
            if ' ' in ultima_notif:
                # Tem horário - formata data e hora
                dt = datetime.datetime.strptime(ultima_notif, '%Y-%m-%d %H:%M:%S')
                data_notif_formatada = dt.strftime('%d/%m/%Y às %H:%M')
            else:
                # Só tem data - formata apenas data
                dt = datetime.datetime.strptime(ultima_notif, '%Y-%m-%d')
                data_notif_formatada = dt.strftime('%d/%m/%Y')
        except Exception as e:
            # Fallback se houver erro no parse
            log_error(e, "agenda_obras", "Parse de data em formatar_info_reiteracao")
            data_notif_formatada = ultima_notif
        
        # Monta mensagem baseada no número de tentativas
        if tentativas == 1:
            return f'📧 1ª reiteração enviada em {data_notif_formatada}'
        elif tentativas == 2:
            return f'📧 2ª reiteração enviada em {data_notif_formatada}'
        else:
            # A partir da 3ª tentativa = alertas críticos diários
            return f'🆘 Alertas críticos diários (última em {data_notif_formatada})'

    def _normalizar_valor_data(self, valor) -> str:
        """Normaliza valor de data para string (suporta tipos retornados pelo NiceGUI)."""
        if valor is None:
            return ''

        if isinstance(valor, datetime.datetime):
            return valor.strftime('%Y-%m-%d')

        if isinstance(valor, datetime.date):
            return valor.strftime('%Y-%m-%d')

        if isinstance(valor, (list, tuple)):
            if not valor:
                return ''
            # Em componentes que retornam múltiplos valores (ex.: range), usa o primeiro
            valor = valor[0]

        if isinstance(valor, dict):
            valor = valor.get('from') or valor.get('to') or ''

        if not isinstance(valor, str):
            valor = str(valor)

        return valor.strip()
    
    def converter_data_para_iso(self, data_str: str) -> str:
        """Converte data de dd/mm/aaaa para aaaa-mm-dd (formato ISO)
        Retorna string vazia se data_str for vazio
        Retorna a data original se já estiver no formato correto
        """
        data_str = self._normalizar_valor_data(data_str)

        if not data_str:
            return ''
        
        # Verifica se já está no formato ISO (aaaa-mm-dd)
        if '-' in data_str:
            try:
                datetime.datetime.strptime(data_str, '%Y-%m-%d')
                return data_str  # Já está correto
            except ValueError:
                pass
        
        # Tenta converter do formato brasileiro (dd/mm/aaaa)
        if '/' in data_str:
            try:
                dt = datetime.datetime.strptime(data_str, '%d/%m/%Y')
                return dt.strftime('%Y-%m-%d')
            except ValueError:
                pass
        
        # Se não conseguiu converter, retorna original
        return data_str
    
    def formatar_data_exibicao(self, data_str: str) -> str:
        """Converte data do banco (qualquer formato) para dd/mm/aaaa para exibição
        Retorna string vazia se data_str for vazio
        Aceita tanto formato ISO quanto brasileiro
        """
        data_str = self._normalizar_valor_data(data_str)

        if not data_str:
            return ''
        
        # Tenta formato ISO (aaaa-mm-dd)
        if '-' in data_str:
            try:
                dt = datetime.datetime.strptime(data_str, '%Y-%m-%d')
                return dt.strftime('%d/%m/%Y')
            except ValueError:
                pass
        
        # Tenta formato brasileiro (dd/mm/aaaa) - já está correto
        if '/' in data_str:
            try:
                dt = datetime.datetime.strptime(data_str, '%d/%m/%Y')
                return dt.strftime('%d/%m/%Y')  # Valida e retorna
            except ValueError:
                pass
        
        # Se não conseguiu converter, retorna original
        return data_str

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
            
            # Se precisa atualizar
            if info['needs_update']:
                # Mostra modal de atualização
                self.mostrar_dialogo_atualizacao(info)
        except Exception as e:
            # Se falhar a verificação, apenas loga o erro mas não bloqueia
            log_error(e, "agenda_obras", "Verificação de atualização ao iniciar")
    
    def mostrar_dialogo_atualizacao(self, info: Dict):
        """Mostra diálogo de atualização (obrigatório ou opcional)"""
        force_update = info.get('force_update', False)
        online_version = info.get('online_version', 'desconhecida')
        current_version = info.get('current_version', VERSION)
        download_url = info.get('download_url', '')
        release_notes = info.get('release_notes', '')
        changelog = info.get('changelog', [])
        
        with ui.dialog().props('persistent' if force_update else '') as dialog, ui.card().style('min-width: 500px; max-width: 600px;'):
            # Cabeçalho
            with ui.row().classes('w-full items-center'):
                if force_update:
                    ui.icon('warning', size='48px').style('color: #f44336;')
                    ui.label('⚠️ ATUALIZAÇÃO OBRIGATÓRIA').style('font-size: 22px; font-weight: bold; color: #f44336; margin-left: 10px;')
                else:
                    ui.icon('info', size='48px').style('color: #2196f3;')
                    ui.label('ℹ️ Atualização Disponível').style('font-size: 22px; font-weight: bold; color: #2196f3; margin-left: 10px;')
            
            ui.separator()
            
            # Informações de versão
            with ui.column().classes('w-full').style('padding: 15px 0;'):
                ui.label(f'Versão atual: {current_version}').style('font-size: 16px;')
                ui.label(f'Nova versão: {online_version}').style('font-size: 16px; font-weight: bold; color: #4caf50;')
                
                if force_update:
                    ui.label('⚠️ Esta atualização é obrigatória para continuar usando o sistema.').style(
                        'font-size: 14px; color: #f44336; margin-top: 10px; padding: 10px; background-color: #ffebee; border-radius: 4px;'
                    )
                
                # Notas de lançamento
                if release_notes:
                    ui.separator().style('margin: 15px 0;')
                    ui.label('📝 Notas de Lançamento:').style('font-size: 16px; font-weight: bold; margin-bottom: 10px;')
                    ui.label(release_notes).style('font-size: 14px; line-height: 1.6;')
                
                # Changelog
                if changelog:
                    ui.separator().style('margin: 15px 0;')
                    ui.label('📋 Novidades:').style('font-size: 16px; font-weight: bold; margin-bottom: 10px;')
                    with ui.column().classes('w-full'):
                        for item in changelog:
                            with ui.row().classes('items-start'):
                                ui.label('•').style('margin-right: 8px; font-size: 14px;')
                                ui.label(item).style('font-size: 14px; line-height: 1.6;')
            
            ui.separator()
            
            # Botões de ação
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
        
        # Se é atualização obrigatória, também mostra notificação
        if force_update:
            ui.notification(
                f'⚠️ Atualização obrigatória disponível! Versão {online_version}',
                type='negative',
                timeout=0,  # Não fecha automaticamente
                position='top'
            )
    
    # ========== UI ========== #
    def header(self):
        """Cabeçalho da aplicação"""
        usuario = obter_usuario_logado()

        with ui.header().classes('items-center').style('background-color: #1976d2; padding: 15px;'):
            ui.label('🏗️ AgendaObras').style(
                'font-size: 28px; color: white; font-weight: bold; margin-right: 30px;'
            )
            
            ui.button('➕ Nova Obra', on_click=self.nova_entrada).props('flat text-color=white').style(
                'font-weight: bold; margin-right: 10px; font-size: 14px;'
            )
            
            # Campo de pesquisa
            self.input_pesquisa = ui.input(placeholder='🔍 Pesquisar obras...').props('outlined dense').style(
                'background-color: white; border-radius: 4px; margin-right: 10px; width: 300px;'
            )
            self.input_pesquisa.on('input', lambda: self.pesquisa(self.input_pesquisa.value))
            self.input_pesquisa.on('keydown.enter', lambda: self.pesquisa(self.input_pesquisa.value))
            
            ui.space()
            
            ui.button('🔄 Atualizar', on_click=self.atualizar_dados).props('flat text-color=white').style(
                'font-weight: bold; font-size: 14px;'
            )

            # Gerenciar usuários (apenas admin)
            if usuario.get('is_admin'):
                ui.button('👥 Usuários', on_click=self.abrir_gerenciar_usuarios).props('flat text-color=white').style(
                    'font-weight: bold; margin-left: 5px; font-size: 14px;'
                )
                ui.button('📄 Contratos', on_click=self.abrir_gerenciar_contratos).props('flat text-color=white').style(
                    'font-weight: bold; margin-left: 5px; font-size: 14px;'
                )

            # Info do usuário logado (clicável) + ações
            with ui.row().classes('items-center gap-2').style('margin-left: 10px;'):
                # Armazena referência ao botão do usuário para atualização dinâmica
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

        with ui.dialog() as dialog, ui.card().style('min-width: 500px; max-width: 600px; padding: 25px;'):
            # Cabeçalho
            ui.label('👤 Meu Perfil').style(
                'font-size: 24px; font-weight: bold; color: #1976d2; margin-bottom: 5px;'
            )
            ui.label(f'Gerencie suas informações pessoais').style(
                'font-size: 13px; color: #999; margin-bottom: 20px;'
            )

            ui.separator()

            # ===== SEÇÃO 1: Informações Pessoais =====
            ui.label('📋 Informações Pessoais').style(
                'font-size: 16px; font-weight: bold; margin-top: 15px; color: #1976d2;'
            )

            nome_input = ui.input('Nome *', value=usuario.get('nome', '')).props('outlined dense').classes('w-full').style('margin-bottom: 8px;')
            sobrenome_input = ui.input('Sobrenome *', value=usuario.get('sobrenome', '')).props('outlined dense').classes('w-full').style('margin-bottom: 8px;')
            email_input = ui.input('E-mail *', value=usuario.get('email', '')).props('outlined dense').classes('w-full').style('margin-bottom: 12px;')

            ui.separator().style('margin: 15px 0;')

            # ===== SEÇÃO 2: Segurança =====
            ui.label('🔒 Segurança').style(
                'font-size: 16px; font-weight: bold; color: #1976d2;'
            )

            senha_atual_input = ui.input('Senha atual *', value='').props('outlined dense type=password').classes('w-full').style('margin-bottom: 8px;')
            nova_senha_input = ui.input('Nova senha', value='', placeholder='Deixe em branco para não alterar').props('outlined dense type=password').classes('w-full').style('margin-bottom: 8px;')
            confirma_senha_input = ui.input('Confirmar nova senha', value='').props('outlined dense type=password').classes('w-full').style('margin-bottom: 12px;')

            ui.label('💡 A senha atual é obrigatória para salvar qualquer alteração.').style(
                'font-size: 12px; color: #1976d2; font-style: italic; margin-bottom: 12px;'
            )

            # Mensagem de erro
            erro_label = ui.label('').style('color: #f44336; font-size: 13px; display: none; margin-bottom: 12px; padding: 8px; background-color: #ffebee; border-radius: 4px;')

            # Mensagem de sucesso
            sucesso_label = ui.label('').style('color: #4caf50; font-size: 13px; display: none; margin-bottom: 12px; padding: 8px; background-color: #e8f5e9; border-radius: 4px;')

            def salvar_alteracoes():
                """Valida e salva as alterações do perfil."""
                nome = nome_input.value.strip() if nome_input.value else ''
                sobrenome = sobrenome_input.value.strip() if sobrenome_input.value else ''
                email = email_input.value.strip() if email_input.value else ''
                senha_atual = senha_atual_input.value if senha_atual_input.value else ''
                nova_senha = nova_senha_input.value if nova_senha_input.value else ''
                confirma_senha = confirma_senha_input.value if confirma_senha_input.value else ''

                # Limpa mensagens anteriores
                erro_label.style('display: none;')
                sucesso_label.style('display: none;')

                # Validações básicas
                if not all([nome, sobrenome, email]):
                    erro_label.set_text('⚠️ Nome, sobrenome e e-mail são obrigatórios.')
                    erro_label.style('display: block;')
                    return

                if not senha_atual:
                    erro_label.set_text('⚠️ Você deve informar a senha atual para salvar alterações.')
                    erro_label.style('display: block;')
                    return

                # Verifica senha atual
                if not auth_db.verificar_senha_atual(user_id, senha_atual):
                    erro_label.set_text('❌ Senha atual incorreta.')
                    erro_label.style('display: block;')
                    return

                # Se quer alterar senha
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

                # Atualiza dados
                try:
                    auth_db.atualizar_usuario(user_id, nome, sobrenome, email)
                    
                    # Atualiza a sessão do usuário (sem fazer login novamente)
                    atualizar_usuario_sessao(nome, sobrenome, email)
                    
                    # Atualiza o botão do usuário no header com os novos dados
                    if hasattr(self, 'user_button'):
                        self.user_button.text = f'👤 {nome} {sobrenome}'

                    # Se alterou senha, salva
                    if nova_senha:
                        auth_db.redefinir_senha(user_id, nova_senha)
                        sucesso_label.set_text('✅ Perfil e senha atualizados com sucesso!')
                    else:
                        sucesso_label.set_text('✅ Perfil atualizado com sucesso!')

                    sucesso_label.style('display: block;')

                    # Inicia o timer para fechar o diálogo
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

            # Botões de ação
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

    # ========== Gerenciamento de Usuários (Admin) ========== #

    def abrir_gerenciar_usuarios(self):
        """Abre diálogo de gerenciamento de usuários."""
        usuario_logado = obter_usuario_logado()
        if not usuario_logado.get('is_admin'):
            self.notificar('⛔ Apenas administradores podem gerenciar usuários.', tipo='negative')
            return

        auth_db = AuthDatabase()

        with ui.dialog() as dialog, ui.card().style(
            'min-width: 650px; max-width: 800px; padding: 25px;'
        ):
            # Cabeçalho
            with ui.row().classes('w-full items-center justify-between'):
                ui.label('👥 Gerenciar Usuários').style(
                    'font-size: 22px; font-weight: bold; color: #1976d2;'
                )
                ui.button('✕', on_click=dialog.close).props('flat dense round').style('color: #666;')

            ui.separator().style('margin: 10px 0;')

            # Container da lista de usuários
            lista_container = ui.column().classes('w-full')

            def abrir_vinculos_usuario(user_id: int, user_nome: str, is_admin_usuario: bool = False):
                contratos_disponiveis = self.contratos_db.listar_contratos()
                vinculados = set(contratos_disponiveis) if is_admin_usuario else set(self.contratos_db.listar_contratos_usuario(user_id))

                with ui.dialog() as vinculo_dialog, ui.card().style('min-width: 500px; max-width: 700px; padding: 20px;'):
                    ui.label(f'🔗 Contratos de {user_nome}').style('font-size: 20px; font-weight: bold; color: #1976d2;')
                    ui.label('Selecione os contratos que este usuário poderá visualizar.').style('font-size: 13px; color: #666; margin-bottom: 10px;')
                    if is_admin_usuario:
                        ui.label('Este usuário é administrador e vê todos os contratos automaticamente.').style('font-size: 12px; color: #999; margin-bottom: 10px;')

                    if not contratos_disponiveis:
                        ui.label('⚠️ Nenhum contrato cadastrado em contratos.db').style('color: #f44336; font-size: 13px;')
                    else:
                        checkboxes = {}
                        with ui.column().classes('w-full').style('max-height: 350px; overflow-y: auto; border: 1px solid #e0e0e0; padding: 10px; border-radius: 6px;'):
                            for contrato_nome in contratos_disponiveis:
                                checkboxes[contrato_nome] = ui.checkbox(
                                    contrato_nome,
                                    value=contrato_nome in vinculados,
                                )

                        def salvar_vinculos():
                            selecionados = contratos_disponiveis if is_admin_usuario else [nome for nome, cb in checkboxes.items() if cb.value]
                            ok = self.contratos_db.substituir_vinculos_usuario(user_id, selecionados)
                            if not ok:
                                ui.notification('Erro ao salvar vínculos de contrato.', type='negative', timeout=3)
                                return

                            ui.notification('Vínculos de contratos atualizados.', type='positive', timeout=3)
                            vinculo_dialog.close()
                            renderizar_lista()

                        with ui.row().classes('w-full justify-end gap-2').style('margin-top: 12px;'):
                            ui.button('Cancelar', on_click=vinculo_dialog.close).props('flat').style('color: #666;')
                            ui.button('Salvar Vínculos', on_click=salvar_vinculos).style(
                                'background-color: #1976d2; color: white; font-weight: bold;'
                            )

                vinculo_dialog.open()

            def renderizar_lista():
                lista_container.clear()
                lista_atualizada = auth_db.listar_usuarios()
                contagem_vinculos = self.contratos_db.contar_contratos_por_usuario()
                usuario_logado = obter_usuario_logado()
                total_admins = auth_db.contar_admins()

                with lista_container:
                    if not lista_atualizada:
                        ui.label('Nenhum usuário cadastrado.').style('color: #999;')
                        return

                    for u in lista_atualizada:
                        with ui.card().classes('w-full').style(
                            'padding: 12px 15px; margin-bottom: 8px; background-color: #fafafa;'
                        ):
                            with ui.row().classes('w-full items-center justify-between'):
                                with ui.column().style('gap: 2px;'):
                                    with ui.row().classes('items-center gap-2'):
                                        ui.label(f'{u["nome"]} {u["sobrenome"]}').style(
                                            'font-weight: bold; font-size: 15px;'
                                        )
                                        if u['is_admin']:
                                            ui.badge('Admin', color='blue').style('font-size: 10px;')
                                    ui.label(u['email']).style('color: #666; font-size: 13px;')
                                    if u['is_admin']:
                                        ui.label('Acesso: todos os contratos').style('color: #999; font-size: 12px;')
                                    else:
                                        total_contratos = contagem_vinculos.get(u['id'], 0)
                                        ui.label(f'Contratos vinculados: {total_contratos}').style('color: #999; font-size: 12px;')

                                    recebe_alerta_critico = bool(u.get('receber_alerta_critico', 1))
                                    with ui.row().classes('items-center gap-2'):
                                        ui.label('Alertas críticos:').style('color: #999; font-size: 12px;')
                                        ui.switch(
                                            value=recebe_alerta_critico,
                                            on_change=lambda e, uid=u['id'], nome=f'{u["nome"]} {u["sobrenome"]}': alternar_alerta_critico(uid, nome, e.value),
                                        ).props('dense').style('transform: scale(0.9);')
                                        ui.label('Recebe' if recebe_alerta_critico else 'Não recebe').style(
                                            'color: #999; font-size: 12px;'
                                        )

                                # Não permite excluir a si mesmo nem o último admin
                                pode_excluir = (
                                    u['id'] != usuario_logado.get('id')
                                    and not (u['is_admin'] and total_admins <= 1)
                                )

                                user_id = u['id']
                                user_nome = f'{u["nome"]} {u["sobrenome"]}'
                                user_email = u['email']

                                with ui.row().classes('items-center gap-1'):
                                    ui.button(
                                        '🔗',
                                            on_click=lambda uid=user_id, un=user_nome, admin=u['is_admin']: abrir_vinculos_usuario(uid, un, admin)
                                    ).props('flat dense round').style('color: #1976d2;').tooltip('Vincular contratos ao usuário')

                                    if not u['is_admin']:
                                        ui.button(
                                            '⭐',
                                            on_click=lambda uid=user_id, un=user_nome: promover_usuario_admin(uid, un)
                                        ).props('flat dense round').style('color: #ff9800;').tooltip('Promover usuário para administrador')

                                    ui.button(
                                        '🔑',
                                        on_click=lambda uid=user_id, un=user_nome, ue=user_email: redefinir_senha_usuario(uid, un, ue)
                                    ).props('flat dense round').style('color: #1976d2;').tooltip('Redefinir senha do usuário')

                                    if pode_excluir:
                                        ui.button(
                                            '🗑️',
                                            on_click=lambda uid=user_id, un=user_nome: confirmar_exclusao(uid, un)
                                        ).props('flat dense round').style('color: #f44336;').tooltip('Excluir usuário')

            def alternar_alerta_critico(user_id: int, user_nome: str, receber_alerta_critico: bool):
                usuario_logado = obter_usuario_logado()
                if not usuario_logado.get('is_admin'):
                    ui.notification('Apenas administradores podem alterar essa preferência.', type='negative', timeout=3)
                    return

                try:
                    ok = auth_db.atualizar_receber_alerta_critico(user_id, receber_alerta_critico)
                    if ok:
                        renderizar_lista()
                        texto = 'passará a receber' if receber_alerta_critico else 'não receberá mais'
                        ui.notification(f'Usuário "{user_nome}" {texto} alertas críticos.', type='positive', timeout=3)
                    else:
                        ui.notification('Não foi possível atualizar a preferência.', type='negative', timeout=3)
                except Exception:
                    ui.notification('Erro ao atualizar preferência de alertas críticos.', type='negative', timeout=3)

            def promover_usuario_admin(user_id: int, user_nome: str):
                usuario_logado = obter_usuario_logado()
                if not usuario_logado.get('is_admin'):
                    ui.notification('Apenas administradores podem promover usuários.', type='negative', timeout=3)
                    return

                try:
                    promovido = auth_db.promover_para_admin(user_id)
                    if promovido:
                        renderizar_lista()
                        ui.notification(f'Usuário "{user_nome}" promovido para administrador.', type='positive', timeout=3)
                    else:
                        ui.notification(f'"{user_nome}" já é administrador.', type='info', timeout=3)
                except Exception:
                    ui.notification('Erro ao promover usuário.', type='negative', timeout=3)

            def redefinir_senha_usuario(user_id: int, user_nome: str, user_email: str):
                nova_senha = f'{randbelow(1_000_000):06d}'
                ok = auth_db.redefinir_senha(user_id, nova_senha)

                if not ok:
                    ui.notification('Erro ao redefinir senha.', type='negative', timeout=3)
                    return

                with ui.dialog() as senha_dialog, ui.card().style('min-width: 420px; padding: 25px;'):
                    ui.label('🔑 Senha redefinida com sucesso').style(
                        'font-size: 20px; font-weight: bold; color: #1976d2; margin-bottom: 10px;'
                    )
                    ui.label(f'Usuário: {user_nome}').style('font-size: 14px; color: #666;')
                    ui.label(f'E-mail: {user_email}').style('font-size: 14px; color: #666; margin-bottom: 10px;')

                    ui.label('Nova senha para envio:').style('font-size: 14px; color: #333;')
                    senha_label = ui.input(value=nova_senha).props('readonly outlined dense').classes('w-full')
                    senha_label.style('font-size: 22px; font-weight: bold; color: #1976d2; margin: 8px 0 12px 0;')

                    with ui.row().classes('w-full justify-end gap-2'):
                        ui.button(
                            'Copiar senha',
                            on_click=lambda: ui.run_javascript(f'navigator.clipboard.writeText("{nova_senha}")')
                        ).props('flat').style('color: #1976d2;')
                        ui.button('Fechar', on_click=senha_dialog.close).style(
                            'background-color: #1976d2; color: white;'
                        )

                senha_dialog.open()
                ui.notification(f'Senha de "{user_nome}" redefinida.', type='positive', timeout=3)

            def confirmar_exclusao(user_id: int, user_nome: str):
                with ui.dialog() as confirm_dialog, ui.card().style('padding: 25px;'):
                    ui.label(f'Deseja excluir o usuário "{user_nome}"?').style(
                        'font-size: 16px; margin-bottom: 15px;'
                    )
                    with ui.row().classes('w-full justify-end gap-2'):
                        ui.button('Cancelar', on_click=confirm_dialog.close).props('flat').style('color: #666;')

                        def executar_exclusao():
                            self.contratos_db.remover_todos_vinculos_usuario(user_id)
                            excluido = auth_db.excluir_usuario(user_id)

                            if not excluido:
                                ui.notification('Erro ao excluir usuário.', type='negative', timeout=3)
                                return

                            # Notifica antes de fechar o diálogo para evitar contexto de slot já removido.
                            ui.notification(f'Usuário "{user_nome}" excluído.', type='warning', timeout=3)
                            confirm_dialog.close()
                            renderizar_lista()

                        ui.button('Excluir', on_click=executar_exclusao).style(
                            'background-color: #f44336; color: white;'
                        )
                confirm_dialog.open()

            # Formulário para novo usuário
            def abrir_form_novo_usuario():
                with ui.dialog() as form_dialog, ui.card().style(
                    'min-width: 400px; max-width: 450px; padding: 25px;'
                ):
                    ui.label('Novo Usuário').style(
                        'font-size: 20px; font-weight: bold; color: #1976d2; margin-bottom: 15px;'
                    )
                    nome_input = ui.input('Nome').props('outlined dense').classes('w-full').style('margin-bottom: 8px;')
                    sobrenome_input = ui.input('Sobrenome').props('outlined dense').classes('w-full').style('margin-bottom: 8px;')
                    email_input = ui.input('E-mail').props('outlined dense').classes('w-full').style('margin-bottom: 8px;')
                    senha_input = ui.input('Senha').props('outlined dense type=password').classes('w-full').style('margin-bottom: 8px;')
                    admin_check = ui.checkbox('Administrador').style('margin-bottom: 10px;')
                    receber_criticos_check = ui.checkbox('Receber alertas críticos').style('margin-bottom: 10px;')
                    receber_criticos_check.value = True
                    erro_label = ui.label('').style('color: #f44336; font-size: 13px; display: none; margin-bottom: 8px;')

                    def salvar_usuario():
                        nome = nome_input.value.strip() if nome_input.value else ''
                        sobrenome = sobrenome_input.value.strip() if sobrenome_input.value else ''
                        email = email_input.value.strip() if email_input.value else ''
                        senha = senha_input.value if senha_input.value else ''

                        if not all([nome, sobrenome, email, senha]):
                            erro_label.set_text('Preencha todos os campos.')
                            erro_label.style('display: block;')
                            return

                        if len(senha) < 4:
                            erro_label.set_text('Senha deve ter pelo menos 4 caracteres.')
                            erro_label.style('display: block;')
                            return

                        ok = auth_db.criar_usuario(
                            nome,
                            sobrenome,
                            email,
                            senha,
                            is_admin=admin_check.value,
                            receber_alerta_critico=receber_criticos_check.value,
                        )
                        if not ok:
                            erro_label.set_text('E-mail já cadastrado.')
                            erro_label.style('display: block;')
                            return

                        form_dialog.close()
                        renderizar_lista()
                        ui.notification(f'Usuário "{nome}" criado!', type='positive', timeout=3)

                    with ui.row().classes('w-full justify-end gap-2'):
                        ui.button('Cancelar', on_click=form_dialog.close).props('flat').style('color: #666;')
                        ui.button('Salvar', on_click=salvar_usuario).style(
                            'background-color: #1976d2; color: white;'
                        )
                form_dialog.open()

            renderizar_lista()

            ui.separator().style('margin: 10px 0;')

            ui.button('➕ Novo Usuário', on_click=abrir_form_novo_usuario).style(
                'background-color: #1976d2; color: white; font-weight: bold;'
            )

        dialog.open()

    # ========== Gerenciamento de Contratos (Admin) ========== #

    def abrir_gerenciar_contratos(self):
        """Abre diálogo de gerenciamento de contratos."""
        usuario_logado = obter_usuario_logado()
        if not usuario_logado.get('is_admin'):
            self.notificar('⛔ Apenas administradores podem gerenciar contratos.', tipo='negative')
            return

        with ui.dialog() as dialog, ui.card().style(
            'min-width: 650px; max-width: 800px; padding: 25px;'
        ):
            with ui.row().classes('w-full items-center justify-between'):
                ui.label('📄 Gerenciar Contratos').style(
                    'font-size: 22px; font-weight: bold; color: #1976d2;'
                )
                ui.button('✕', on_click=dialog.close).props('flat dense round').style('color: #666;')

            ui.separator().style('margin: 10px 0;')
            lista_container = ui.column().classes('w-full')

            def renderizar_lista():
                lista_container.clear()
                contratos = self.contratos_db.listar_contratos()

                with lista_container:
                    if not contratos:
                        ui.label('Nenhum contrato cadastrado.').style('color: #999;')
                        return

                    for contrato_nome in contratos:
                        uso = self._contar_uso_contrato_catalogo(contrato_nome)

                        with ui.card().classes('w-full').style(
                            'padding: 12px 15px; margin-bottom: 8px; background-color: #fafafa;'
                        ):
                            with ui.row().classes('w-full items-center justify-between'):
                                with ui.column().style('gap: 2px;'):
                                    ui.label(contrato_nome).style('font-weight: bold; font-size: 15px;')
                                    ui.label(
                                        f'Vínculos de usuários: {uso["vinculos_usuarios"]} • Obras vinculadas: {uso["obras_cliente"]}'
                                    ).style('color: #999; font-size: 12px;')

                                with ui.row().classes('items-center gap-1'):
                                    ui.button(
                                        '✏️',
                                        on_click=lambda nome=contrato_nome: abrir_form_editar_contrato(nome)
                                    ).props('flat dense round').style('color: #1976d2;').tooltip('Renomear contrato')

                                    ui.button(
                                        '🗑️',
                                        on_click=lambda nome=contrato_nome: confirmar_exclusao_contrato(nome)
                                    ).props('flat dense round').style('color: #f44336;').tooltip('Excluir contrato')

            def abrir_form_novo_contrato():
                with ui.dialog() as form_dialog, ui.card().style(
                    'min-width: 420px; max-width: 500px; padding: 25px;'
                ):
                    ui.label('Novo Contrato').style(
                        'font-size: 20px; font-weight: bold; color: #1976d2; margin-bottom: 15px;'
                    )

                    nome_input = ui.input('Nome do Contrato').props('outlined dense').classes('w-full')
                    erro_label = ui.label('').style(
                        'color: #f44336; font-size: 13px; display: none; margin-top: 8px;'
                    )

                    def salvar_contrato():
                        ok, mensagem = self._adicionar_contrato_catalogo(nome_input.value)
                        if not ok:
                            erro_label.set_text(f'❌ {mensagem}')
                            erro_label.style('display: block;')
                            return

                        form_dialog.close()
                        renderizar_lista()
                        self.renderizar_obras()
                        ui.notification(f'✅ {mensagem}', type='positive', timeout=3)

                    with ui.row().classes('w-full justify-end gap-2').style('margin-top: 12px;'):
                        ui.button('Cancelar', on_click=form_dialog.close).props('flat').style('color: #666;')
                        ui.button('Salvar', on_click=salvar_contrato).style(
                            'background-color: #1976d2; color: white;'
                        )

                form_dialog.open()

            def abrir_form_editar_contrato(nome_atual: str):
                with ui.dialog() as form_dialog, ui.card().style(
                    'min-width: 420px; max-width: 520px; padding: 25px;'
                ):
                    ui.label('Renomear Contrato').style(
                        'font-size: 20px; font-weight: bold; color: #1976d2; margin-bottom: 10px;'
                    )
                    ui.label(f'Atual: {nome_atual}').style('font-size: 13px; color: #666; margin-bottom: 10px;')

                    novo_nome_input = ui.input('Novo Nome').props('outlined dense').classes('w-full')
                    novo_nome_input.value = nome_atual
                    erro_label = ui.label('').style(
                        'color: #f44336; font-size: 13px; display: none; margin-top: 8px;'
                    )

                    def salvar_edicao():
                        ok, mensagem = self._editar_contrato_catalogo(nome_atual, novo_nome_input.value)
                        if not ok:
                            erro_label.set_text(f'❌ {mensagem}')
                            erro_label.style('display: block;')
                            return

                        form_dialog.close()
                        renderizar_lista()
                        self.renderizar_obras()
                        ui.notification(f'✅ {mensagem}', type='positive', timeout=3)

                    with ui.row().classes('w-full justify-end gap-2').style('margin-top: 12px;'):
                        ui.button('Cancelar', on_click=form_dialog.close).props('flat').style('color: #666;')
                        ui.button('Salvar', on_click=salvar_edicao).style(
                            'background-color: #1976d2; color: white;'
                        )

                form_dialog.open()

            def confirmar_exclusao_contrato(nome_contrato: str):
                uso = self._contar_uso_contrato_catalogo(nome_contrato)
                contratos_disponiveis = [
                    nome for nome in self.contratos_db.listar_contratos()
                    if nome != nome_contrato
                ]

                with ui.dialog() as confirm_dialog, ui.card().style('padding: 25px; min-width: 500px; max-width: 650px;'):
                    ui.label(f'Deseja excluir o contrato "{nome_contrato}"?').style(
                        'font-size: 16px; margin-bottom: 8px;'
                    )

                    ui.label(
                        f'Vínculos de usuários: {uso["vinculos_usuarios"]} • Obras vinculadas: {uso["obras_cliente"]}'
                    ).style('font-size: 13px; color: #666; margin-bottom: 10px;')

                    substituto_select = None
                    erro_label = ui.label('').style(
                        'color: #f44336; font-size: 13px; display: none; margin-bottom: 8px;'
                    )

                    if uso['total'] > 0:
                        ui.label(
                            'Este contrato está em uso. Selecione um contrato substituto para migrar referências antes de excluir.'
                        ).style('font-size: 12px; color: #f44336; margin-bottom: 8px;')

                        substituto_select = ui.select(
                            contratos_disponiveis,
                            label='Contrato substituto *',
                        ).classes('w-full').props('outlined dense')

                        if not contratos_disponiveis:
                            ui.label(
                                'Não há outro contrato disponível para substituição. Cadastre outro contrato antes de excluir este.'
                            ).style('font-size: 12px; color: #f44336; margin-top: 8px;')

                    def executar_exclusao():
                        replace_with = ''
                        if uso['total'] > 0:
                            if not contratos_disponiveis:
                                erro_label.set_text('❌ Não há contrato substituto disponível para migração.')
                                erro_label.style('display: block;')
                                return
                            replace_with = (substituto_select.value or '').strip() if substituto_select else ''
                            if not replace_with:
                                erro_label.set_text('❌ Selecione um contrato substituto para prosseguir.')
                                erro_label.style('display: block;')
                                return

                        ok, mensagem = self._remover_contrato_catalogo(nome_contrato, replace_with)
                        if not ok:
                            erro_label.set_text(f'❌ {mensagem}')
                            erro_label.style('display: block;')
                            return

                        confirm_dialog.close()
                        renderizar_lista()
                        self.renderizar_obras()
                        ui.notification(f'✅ {mensagem}', type='positive', timeout=3)

                    with ui.row().classes('w-full justify-end gap-2').style('margin-top: 12px;'):
                        ui.button('Cancelar', on_click=confirm_dialog.close).props('flat').style('color: #666;')
                        ui.button('Excluir', on_click=executar_exclusao).style(
                            'background-color: #f44336; color: white;'
                        )

                confirm_dialog.open()

            renderizar_lista()

            ui.separator().style('margin: 10px 0;')
            ui.button('➕ Novo Contrato', on_click=abrir_form_novo_contrato).style(
                'background-color: #1976d2; color: white; font-weight: bold;'
            )

        dialog.open()
    
    def body(self):
        """Corpo principal com grid de obras"""
        with ui.column().classes('w-full p-0'):
            with ui.card().classes('w-full').style('background-color: #fafafa;'):
                ui.label('Obras Cadastradas').style('font-size: 20px; font-weight: bold; margin-bottom: 10px;')
                
                # Container que será atualizado dinamicamente
                self.body_container = ui.column().classes('w-full')
                
                self.renderizar_obras()
    
    def renderizar_obras(self):
        """Renderiza o grid de cards das obras"""
        self.body_container.clear()
        
        with self.body_container:
            # Indicador de pesquisa ativa
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
                # Contador de resultados
                total = len(obras)
                if self.filtro_pesquisa:
                    ui.label(f'{total} obra{"s" if total != 1 else ""} encontrada{"s" if total != 1 else ""}').style(
                        'font-size: 14px; color: #666; margin-bottom: 10px; font-weight: 500;'
                    )
                
                # Grid responsivo de 4 colunas (ajustado para cards mais compactos)
                with ui.grid(columns='repeat(auto-fit, minmax(330px, 1fr))').classes('w-full gap-4'):
                    for obra in obras:
                        self.criar_card_obra(obra)
    
    def criar_card_obra(self, obra: Dict):
        """Cria um card individual de obra"""
        # Obtém checklist e calcula status
        checklist = self.db.obter_checklist(obra['id'])
        progresso = self.helper.calcular_progresso(checklist)
        cor, icone, status_texto = self.helper.obter_status_visual(obra, checklist)
        
        # Encontra próxima tarefa pendente
        proxima_tarefa = next((item for item in checklist if not item['concluido'] and not item['bloqueado']), None)
        
        # Card da obra
        with ui.card().classes('hover:shadow-lg transition-shadow').style(
            f'border-left: 5px solid {cor}; min-height: 250px; max-height: 400px;'
        ):
            
            # Cabeçalho do card (clicável)
            with ui.row().classes('w-full items-center justify-between cursor-pointer').on('click', lambda o=obra: self.abrir_detalhes_obra(o['id'])):
                ui.label(obra['nome_contrato']).style('font-size: 18px; font-weight: bold;')
                ui.icon(icone).style(f'color: {cor}; font-size: 24px;')
            
            ui.separator()
            
            # Abas
            with ui.tabs().classes('w-full') as tabs:
                tab_info = ui.tab('Informações', icon='info')
                tab_checklist = ui.tab('Checklist', icon='checklist')
            
            with ui.tab_panels(tabs, value=tab_info).classes('w-full'):
                # Aba de Informações Gerais
                with ui.tab_panel(tab_info):
                    with ui.column().classes('w-full gap-2'):
                        with ui.row().classes('items-center'):
                            ui.icon('business').style('color: #666; font-size: 16px;')
                            ui.label(f'Contrato: {obra["cliente"]}').style('color: #666; font-size: 13px;')
                        
                        with ui.row().classes('items-center'):
                            ui.icon('attach_money').style('color: #666; font-size: 16px;')
                            ui.label(self.helper.formatar_valor(obra['valor_contrato'])).style(
                                'color: #2e7d32; font-weight: bold; font-size: 14px;'
                            )
                        
                        with ui.row().classes('items-center'):
                            ui.icon('event').style('color: #666; font-size: 16px;')
                            
                            if obra.get('data_inicio') and obra.get('data_inicio').strip():
                                data_formatada = self.formatar_data_exibicao(obra['data_inicio'])
                                if data_formatada:
                                    ui.label(f'Início: {data_formatada}').style('color: #666; font-size: 13px;')
                                else:
                                    ui.label(f'Data de início não definida').style('color: #999; font-style: italic; font-size: 13px;')
                            else:
                                ui.label(f'Data de início não definida').style('color: #999; font-style: italic; font-size: 13px;')
                        
                        # Data de criação da obra
                        if obra.get('data_criacao'):
                            with ui.row().classes('items-center'):
                                ui.icon('add_circle').style('color: #666; font-size: 16px;')
                                try:
                                    data_criacao_formatada = datetime.datetime.strptime(
                                        obra['data_criacao'], '%Y-%m-%d %H:%M:%S'
                                    ).strftime('%d/%m/%Y %H:%M')
                                except Exception as e1:
                                    try:
                                        data_criacao_formatada = datetime.datetime.strptime(
                                            obra['data_criacao'], '%Y-%m-%d'
                                        ).strftime('%d/%m/%Y')
                                    except Exception as e2:
                                        log_error(e2, "agenda_obras", "Parse de data_criacao em renderizar_obras")
                                        data_criacao_formatada = obra['data_criacao']
                                ui.label(f'Criado em: {data_criacao_formatada}').style('color: #666; font-size: 13px;')
                        
                        with ui.row().classes('items-center'):
                            ui.icon('flag').style(f'color: {cor}; font-size: 16px;')
                            ui.label(f'Status: {status_texto}').style(f'color: {cor}; font-weight: bold; font-size: 13px;')
                        
                        # Barra de progresso
                        ui.separator()
                        ui.label(f'Progresso: {progresso}%').style('font-size: 12px; font-weight: bold; color: #666;')
                        ui.linear_progress(progresso / 100, show_value=False).style('height: 8px;')
                        
                        # Próxima tarefa pendente
                        if proxima_tarefa:
                            ui.separator()
                            ui.label('🎯 Próxima Tarefa:').style('font-size: 12px; font-weight: bold; color: #1976d2; margin-top: 5px;')
                            with ui.row().classes('items-center gap-2'):
                                ui.icon('arrow_forward').style('color: #1976d2; font-size: 14px;')
                                ui.label(proxima_tarefa['descricao']).style('font-size: 12px; color: #333; font-weight: 500;')
                            
                            if proxima_tarefa['data_limite']:
                                dias_restantes = self.calcular_dias_restantes_exibicao(proxima_tarefa)
                                sufixo_dias = ' dias úteis' if self.usa_dias_uteis_exibicao(proxima_tarefa) else ' dias'
                                data_formatada_prazo = self.formatar_data_exibicao(proxima_tarefa['data_limite'])
                                cor_prazo = 'red' if dias_restantes < 0 else 'orange' if dias_restantes <= 3 else 'green'
                                
                                if dias_restantes == 0:
                                    ui.label(f'⏰ Prazo: {data_formatada_prazo} (HOJE!)').style(
                                        f'font-size: 11px; color: {cor_prazo}; margin-left: 20px;'
                                    )
                                else:
                                    ui.label(f'⏰ Prazo: {data_formatada_prazo} ({abs(dias_restantes)}{sufixo_dias} {"atrasado" if dias_restantes < 0 else "restante" if dias_restantes > 0 else "hoje"})').style(
                                    f'font-size: 11px; color: {cor_prazo}; margin-left: 20px;'
                                )
                
                # Aba de Checklist
                with ui.tab_panel(tab_checklist).style('max-height: 250px; overflow-y: auto;'):
                    with ui.column().classes('w-full gap-1'):
                        tarefas_concluidas = sum(1 for item in checklist if item['concluido'])
                        ui.label(f'Total: {tarefas_concluidas}/{len(checklist)} tarefas concluídas').style(
                            'font-size: 11px; color: #666; font-weight: bold; margin-bottom: 5px;'
                        )
                        
                        for item in checklist:
                            # Determina tooltip baseado no estado
                            if item['concluido']:
                                data_conclusao = item.get('data_conclusao')
                                data_conclusao_fmt = self.formatar_data_exibicao(data_conclusao) if data_conclusao else ''
                                tooltip_text = f"✅ Concluída" + (f" em {data_conclusao_fmt}" if data_conclusao_fmt else "")
                            elif item.get('bloqueado'):
                                base_calculo = item.get('base_calculo', '')
                                if base_calculo == 'assinatura':
                                    tooltip_text = '🔒 Aguardando data de assinatura do contrato'
                                elif base_calculo == 'aio':
                                    tooltip_text = '🔒 Aguardando data da AIO'
                                elif base_calculo == 'fim_tarefa':
                                    tooltip_text = '🔒 Aguardando conclusão de tarefa anterior'
                                else:
                                    tooltip_text = '🔒 Tarefa bloqueada'
                            elif item.get('data_limite'):
                                dias_restantes = self.calcular_dias_restantes_exibicao(item)
                                sufixo_dias = ' dias úteis' if self.usa_dias_uteis_exibicao(item) else ' dias'
                                data_formatada = self.formatar_data_exibicao(item['data_limite'])
                                if dias_restantes < 0:
                                    tooltip_text = f"⚠️ Atrasada: {abs(dias_restantes)}{sufixo_dias} - Prazo: {data_formatada}"
                                    # Adiciona info de reiteração se houver
                                    info_reiteracao = self.formatar_info_reiteracao(item)
                                    if info_reiteracao:
                                        tooltip_text += f"\n{info_reiteracao}"
                                elif dias_restantes == 0:
                                    tooltip_text = f"Prazo: {data_formatada} (HOJE!)"
                                else:
                                    tooltip_text = f"Prazo: {data_formatada} ({dias_restantes}{sufixo_dias} restantes)"
                            else:
                                tooltip_text = "Tarefa pendente"
                            
                            # Estilo com hover suave usando CSS puro
                            with ui.row().classes('items-center gap-2').style(
                                'padding: 4px 8px; border-radius: 4px; cursor: default;'
                            ).tooltip(tooltip_text):
                                if item['concluido']:
                                    ui.icon('check_circle').style('color: green; font-size: 14px;')
                                    with ui.column().classes('gap-0'):
                                        ui.label(item['descricao']).style('font-size: 11px; color: #999; text-decoration: line-through;')
                                        if item.get('data_conclusao'):
                                            data_concl_fmt = self.formatar_data_exibicao(item['data_conclusao'])
                                            if data_concl_fmt:
                                                ui.label(f'✓ Concluída em {data_concl_fmt}').style('font-size: 9px; color: #999; font-style: italic;')
                                elif item['bloqueado']:
                                    ui.icon('lock').style('color: #ccc; font-size: 14px;')
                                    ui.label(item['descricao']).style('font-size: 11px; color: #ccc;')
                                else:
                                    ui.icon('radio_button_unchecked').style('color: #ff9800; font-size: 14px;')
                                    with ui.column().classes('gap-0'):
                                        ui.label(item['descricao']).style('font-size: 11px; color: #666;')
                                        # Mostra info de reiteração se tarefa atrasada
                                        if item.get('data_limite'):
                                            dias_restantes = self.calcular_dias_restantes_exibicao(item)
                                            if dias_restantes < 0:
                                                info_reiteracao = self.formatar_info_reiteracao(item)
                                                if info_reiteracao:
                                                    ui.label(info_reiteracao).style('font-size: 9px; color: #ff5722; font-style: italic;')
    
    # ========== Dialogs ========== #
    def nova_entrada(self):
        """Dialog para adicionar nova obra"""
        permissoes = self._obter_permissoes_usuario()

        with ui.dialog() as dialog, ui.card().style('min-width: 700px; max-width: 900px; padding: 20px; max-height: 90vh; overflow-y: auto;'):
            ui.label('➕ Nova Obra').style('font-size: 22px; font-weight: bold; margin-bottom: 15px;')
            
            # ===== SEÇÃO 1: Informações Básicas =====
            ui.label('📋 Informações Básicas').style('font-size: 16px; font-weight: bold; margin-top: 10px; color: #1976d2;')
            
            # Campos básicos
            nome_input = ui.input(label='Nome do Contrato *').classes('w-full').props('outlined')
            contratos_disponiveis = self.contratos_db.listar_contratos()
            if not permissoes['is_admin']:
                contratos_disponiveis = [
                    contrato for contrato in contratos_disponiveis
                    if contrato in set(permissoes['contratos_vinculados'])
                ]
            contrato_input = ui.select(contratos_disponiveis, label='Contrato *').classes('w-full').props('outlined')

            if not contratos_disponiveis:
                if permissoes['is_admin']:
                    ui.label('⚠️ Nenhum contrato disponível em contratos.db').style('color: #f44336; font-size: 12px;')
                else:
                    ui.label('⚠️ Seu usuário não possui contratos vinculados.').style('color: #f44336; font-size: 12px;')
            
            with ui.row().classes('w-full gap-2'):
                contrato_ic_input = ui.input(label='Contrato (IC)').classes('w-full').props('outlined')
                pedido_sap_input = ui.input(label='Pedido SAP').classes('w-full').props('outlined')
                prefixo_agencia_input = ui.input(label='Prefixo Agência').classes('w-full').props('outlined')
            
            # Date picker - Data de Acionamento
            with ui.input('Data de Acionamento', value='', placeholder='dd/mm/aaaa').classes('w-full').props('outlined').tooltip('📅 Data usada como base para calcular prazos iniciais (ex: RETORNO PROJETO E ORÇAMENTO). Se não informada, será usada a data de criação do card.') as data_acionamento_input:
                with ui.menu().props('no-parent-event') as menu_acionamento:
                    with ui.date(value='') as date_picker_acionamento:
                        date_picker_acionamento.on('update:model-value', lambda e: data_acionamento_input.set_value(self.formatar_data_exibicao(e.args) if e.args else ''))
                        with ui.row().classes('justify-end'):
                            ui.button('Fechar', on_click=menu_acionamento.close).props('flat')
                with data_acionamento_input.add_slot('append'):
                    ui.icon('edit_calendar').on('click', menu_acionamento.open).classes('cursor-pointer')

            servico_input = ui.input(label='Serviço').classes('w-full').props('outlined')
            
            ui.separator().classes('my-4')
            
            # ===== SEÇÃO 2: Valores Financeiros =====
            ui.label('💰 Valores Financeiros').style('font-size: 16px; font-weight: bold; color: #1976d2;')
            
            with ui.row().classes('w-full gap-2'):
                valor_input = ui.number(label='Valor do Contrato (R$) *', min=0, step=0.01, format='%.2f').classes('w-1/3').props('outlined')
                valor_parceiro_input = ui.number(label='Valor Parceiro (R$)', min=0, step=0.01, format='%.2f').classes('w-1/3').props('outlined')
                valor_percentual_input = ui.number(label='Valor % (%)', min=0, max=100, step=0.01, format='%.2f').classes('w-1/3').props('outlined')
            
            total_obra_input = ui.number(label='Total da Obra (R$)', min=0, step=0.01, format='%.2f').classes('w-full').props('outlined')
            
            ui.separator().classes('my-4')
            
            # ===== SEÇÃO 3: Prazos e Datas =====
            ui.label('📅 Prazos e Datas').style('font-size: 16px; font-weight: bold; color: #1976d2;')
            
            with ui.row().classes('w-full gap-2'):
                meses = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 
                        'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro']
                mes_execucao_input = ui.select(meses, label='Mês de Execução').classes('w-1/2').props('outlined')
                ano_execucao_input = ui.number(label='Ano', value=datetime.date.today().year, min=2020, max=2050, step=1).classes('w-1/2').props('outlined')
            
            # Date picker - Data de início da obra
            with ui.input('Data de início da obra', value='', placeholder='dd/mm/aaaa').classes('w-full').props('outlined').tooltip('📅 Data em que a obra deve começar. Este campo será preenchido pelo coordenador.') as data_input:
                with ui.menu().props('no-parent-event') as menu:
                    with ui.date(value='') as date_picker:
                        date_picker.on('update:model-value', lambda e: data_input.set_value(self.formatar_data_exibicao(e.args) if e.args else ''))
                        with ui.row().classes('justify-end'):
                            ui.button('Fechar', on_click=menu.close).props('flat')
                with data_input.add_slot('append'):
                    ui.icon('edit_calendar').on('click', menu.open).classes('cursor-pointer')
            
            # Datas críticas (desabilitadas inicialmente)
            with ui.input('Data de Assinatura do Contrato', value='', placeholder='dd/mm/aaaa').classes('w-full').props('outlined disable').tooltip('🔒 Será desbloqueado quando a tarefa "CONTRATO ASSINADO" for concluída') as data_assinatura_input:
                with ui.menu().props('no-parent-event') as menu_assinatura:
                    with ui.date() as date_picker_assinatura:
                        date_picker_assinatura.on('update:model-value', lambda e: data_assinatura_input.set_value(self.formatar_data_exibicao(e.args) if e.args else ''))
                        with ui.row().classes('justify-end'):
                            ui.button('Fechar', on_click=menu_assinatura.close).props('flat')
                with data_assinatura_input.add_slot('append'):
                    ui.icon('lock').classes('cursor-not-allowed')
            
            with ui.input('Data da AIO', value='', placeholder='dd/mm/aaaa').classes('w-full').props('outlined disable').tooltip('🔒 Será desbloqueado quando a tarefa "SOLICITAR A DATA DA AIO" for concluída') as data_aio_input:
                with ui.menu().props('no-parent-event') as menu_aio:
                    with ui.date() as date_picker_aio:
                        date_picker_aio.on('update:model-value', lambda e: data_aio_input.set_value(self.formatar_data_exibicao(e.args) if e.args else ''))
                        with ui.row().classes('justify-end'):
                            ui.button('Fechar', on_click=menu_aio.close).props('flat')
                with data_aio_input.add_slot('append'):
                    ui.icon('lock').classes('cursor-not-allowed')
            
            status_input = ui.select(
                STATUS_OPTIONS,
                label='Status',
                value='Não Iniciada'
            ).classes('w-full').props('outlined')
            
            ui.separator()
            
            # Botões de ação
            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('Cancelar', on_click=dialog.close).props('flat')
                ui.button('💾 Salvar Obra', on_click=lambda: self.salvar_obra(
                    dialog, nome_input.value, contrato_input.value,
                    valor_input.value, data_input.value, status_input.value,
                    contrato_ic=contrato_ic_input.value or None,
                    pedido_sap=pedido_sap_input.value or None,
                    prefixo_agencia=prefixo_agencia_input.value or None,
                    servico=servico_input.value or None,
                    valor_parceiro=valor_parceiro_input.value or None,
                    valor_percentual=valor_percentual_input.value or None,
                    total_obra=total_obra_input.value or None,
                    mes_execucao=mes_execucao_input.value or None,
                    ano_execucao=int(ano_execucao_input.value) if ano_execucao_input.value else None,
                    data_assinatura=data_assinatura_input.value or None,
                    data_aio=data_aio_input.value or None,
                    data_acionamento=data_acionamento_input.value or None
                )).props('color=primary')
            
        dialog.open()
    
    def salvar_obra(self, dialog, nome: str, cliente: str, valor: float, 
                    data_inicio: str, status: str, **kwargs):
        """Salva nova obra no banco de dados"""
        # Validações
        if not nome or not cliente:
            self.notificar('⚠️ Nome do contrato e Contrato são obrigatórios!', tipo='warning')
            return

        if not self._usuario_pode_acessar_contrato(cliente):
            self.notificar('⛔ Você não possui permissão para criar obra neste contrato.', tipo='negative')
            return
        
        if not valor or valor <= 0:
            self.notificar('⚠️ Valor do contrato deve ser maior que zero!', tipo='warning')
            return
        
        try:
            # Converte datas para formato ISO
            data_inicio = self.converter_data_para_iso(data_inicio)
            if 'data_assinatura' in kwargs:
                kwargs['data_assinatura'] = self.converter_data_para_iso(kwargs['data_assinatura'])
            if 'data_aio' in kwargs:
                kwargs['data_aio'] = self.converter_data_para_iso(kwargs['data_aio'])
            if 'data_conclusao' in kwargs:
                kwargs['data_conclusao'] = self.converter_data_para_iso(kwargs['data_conclusao'])
            if 'data_acionamento' in kwargs:
                kwargs['data_acionamento'] = self.converter_data_para_iso(kwargs['data_acionamento'])
            
            # Cria obra com todos os campos
            obra_id = self.db.criar_obra(nome, cliente, valor, data_inicio, status, **kwargs)
            
            # Fecha dialog e atualiza interface
            dialog.close()
            self.renderizar_obras()
            self.notificar(f'✅ Obra "{nome}" criada com sucesso!', tipo='positive')
            
        except Exception as e:
            log_error(e, "agenda_obras", f"Criar obra: {nome}")
            self.notificar(f'❌ Erro ao criar obra: {str(e)}', tipo='negative')
    
    def abrir_detalhes_obra(self, obra_id: int):
        """Dialog para visualizar e editar obra com checklist"""
        obra = self.db.obter_obra(obra_id)
        if not obra:
            self.notificar('⚠️ Obra não encontrada.', tipo='warning')
            return

        if not self._usuario_pode_acessar_contrato(obra.get('cliente')):
            self.notificar('⛔ Você não tem acesso a este contrato.', tipo='negative')
            return

        checklist = self.db.obter_checklist(obra_id)

        # Verificar se tarefas críticas estão concluídas para habilitar campos
        contrato_assinado_concluido = any(
            item['descricao'] == 'CONTRATO ASSINADO' and item['concluido'] 
            for item in checklist
        )
        aio_concluido = any(
            item['descricao'] == 'SOLICITAR A DATA DA AIO' and item['concluido'] 
            for item in checklist
        )

        with ui.dialog() as dialog, ui.card().style('min-width: 700px; max-width: 900px; padding: 20px; max-height: 90vh; overflow-y: auto;'):
            # Cabeçalho
            with ui.row().classes('w-full items-center justify-between'):
                ui.label(f'🏗️ {obra["nome_contrato"]}').style('font-size: 22px; font-weight: bold;')
                ui.button(icon='close', on_click=lambda: [dialog.close(), self.renderizar_obras()]).props('flat round')
            
            ui.separator()
            
            # ===== SEÇÃO 1: Informações Básicas =====
            ui.label('📋 Informações Básicas').style('font-size: 16px; font-weight: bold; margin-top: 10px; color: #1976d2;')

            permissoes = self._obter_permissoes_usuario()
            contratos_disponiveis = self.contratos_db.listar_contratos()
            if not permissoes['is_admin']:
                contratos_disponiveis = [
                    contrato for contrato in contratos_disponiveis
                    if contrato in set(permissoes['contratos_vinculados'])
                ]
            contrato_obra_atual = obra.get('cliente') or ''
            contrato_fora_da_lista = bool(contrato_obra_atual) and contrato_obra_atual not in contratos_disponiveis
            valor_inicial_contrato = None if contrato_fora_da_lista else contrato_obra_atual
            
            with ui.column().classes('w-full gap-3'):
                nome_input = ui.input(label='Nome do Contrato', value=obra['nome_contrato']).classes('w-1/2').props('outlined')
                contrato_input = ui.select(
                    contratos_disponiveis,
                    label='Contrato *',
                    value=valor_inicial_contrato
                ).classes('w-full').props('outlined')

                if not contratos_disponiveis:
                    ui.label('⚠️ Nenhum contrato disponível em contratos.db').style('color: #f44336; font-size: 12px;')
                elif contrato_fora_da_lista:
                    ui.label('⚠️ O contrato atual não existe na lista. Selecione um contrato válido para salvar.').style('color: #f44336; font-size: 12px;')
                
                with ui.row().classes('w-full gap-2'):
                    contrato_ic_input = ui.input(label='Contrato (IC)', value=obra.get('contrato_ic') or '').classes('w-full').props('outlined')
                    pedido_sap_input = ui.input(label='Pedido SAP', value=obra.get('pedido_sap') or '').classes('w-full').props('outlined')
                    prefixo_agencia_input = ui.input(label='Prefixo Agência', value=obra.get('prefixo_agencia') or '').classes('w-full').props('outlined')

                # Data de Acionamento
                with ui.input('Data de Acionamento', value=self.formatar_data_exibicao(obra.get('data_acionamento') or ''), placeholder='dd/mm/aaaa').classes('w-full').props('outlined').tooltip('📅 Data usada como base para calcular prazos iniciais. Se alterada, os prazos das tarefas dependentes serão recalculados.') as data_acionamento_input:
                    with ui.menu().props('no-parent-event') as menu_acionamento:
                        with ui.date(value=obra.get('data_acionamento') or '') as date_picker_acionamento:
                            date_picker_acionamento.on('update:model-value', lambda e: data_acionamento_input.set_value(self.formatar_data_exibicao(e.args) if e.args else ''))
                            with ui.row().classes('justify-end'):
                                ui.button('Fechar', on_click=menu_acionamento.close).props('flat')
                    with data_acionamento_input.add_slot('append'):
                        ui.icon('edit_calendar').on('click', menu_acionamento.open).classes('cursor-pointer')

                servico_input = ui.input(label='Serviço', value=obra.get('servico') or '').classes('w-full').props('outlined')
            
            ui.separator().classes('my-4')
            
            # ===== SEÇÃO 2: Valores Financeiros =====
            ui.label('💰 Valores Financeiros').style('font-size: 16px; font-weight: bold; color: #1976d2;')
            
            with ui.row().classes('w-full gap-2'):
                valor_input = ui.number(label='Valor do Contrato (R$)', value=obra['valor_contrato'], min=0, step=0.01, format='%.2f').classes('w-1/3').props('outlined')
                valor_parceiro_input = ui.number(label='Valor Parceiro (R$)', value=obra.get('valor_parceiro') or 0, min=0, step=0.01, format='%.2f').classes('w-1/3').props('outlined')
                valor_percentual_input = ui.number(label='Valor % (%)', value=obra.get('valor_percentual') or 0, min=0, max=100, step=0.01, format='%.2f').classes('w-1/3').props('outlined')
            
            total_obra_input = ui.number(label='Total da Obra (R$)', value=obra.get('total_obra') or 0, min=0, step=0.01, format='%.2f').classes('w-full').props('outlined')
            
            ui.separator().classes('my-4')
            
            # ===== SEÇÃO 3: Prazos e Datas =====
            ui.label('📅 Prazos e Datas').style('font-size: 16px; font-weight: bold; color: #1976d2;')
            
            with ui.row().classes('w-full gap-2'):
                meses = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 
                        'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro']
                mes_execucao_input = ui.select(meses, label='Mês de Execução', value=obra.get('mes_execucao')).classes('w-1/2').props('outlined')
                ano_execucao_input = ui.number(label='Ano', value=obra.get('ano_execucao') or datetime.date.today().year, min=2020, max=2050, step=1).classes('w-1/2').props('outlined')
            
            with ui.input('Data de início da obra', value=self.formatar_data_exibicao(obra.get('data_inicio') or ''), placeholder='dd/mm/aaaa').classes('w-full').props('outlined').tooltip('📅 Data em que a obra deve começar. Este campo será preenchido pelo coordenador.') as data_input:
                with ui.menu().props('no-parent-event') as menu:
                    with ui.date(value=obra.get('data_inicio') or '') as date_picker:
                        date_picker.on('update:model-value', lambda e: data_input.set_value(self.formatar_data_exibicao(e.args) if e.args else ''))
                        with ui.row().classes('justify-end'):
                            ui.button('Fechar', on_click=menu.close).props('flat')
                with data_input.add_slot('append'):
                    ui.icon('edit_calendar').on('click', menu.open).classes('cursor-pointer')
            
            # Data de Assinatura (condicional)
            data_assinatura_props = 'outlined' if contrato_assinado_concluido else 'outlined disable'
            tooltip_assinatura = '📅 Data de assinatura do contrato' if contrato_assinado_concluido else '🔒 Complete a tarefa "CONTRATO ASSINADO" para desbloquear'
            
            with ui.input('Data de Assinatura do Contrato', value=self.formatar_data_exibicao(obra.get('data_assinatura') or ''), placeholder='dd/mm/aaaa').classes('w-full').props(data_assinatura_props).tooltip(tooltip_assinatura) as data_assinatura_input:
                pass
            self._data_assinatura_input = data_assinatura_input

            # Data da AIO (condicional)
            data_aio_props = 'outlined' if aio_concluido else 'outlined disable'
            tooltip_aio = '📅 Data da Autorização de Início de Obra' if aio_concluido else '🔒 Complete a tarefa "SOLICITAR A DATA DA AIO" para desbloquear'
            
            with ui.input('Data da AIO', value=self.formatar_data_exibicao(obra.get('data_aio') or ''), placeholder='dd/mm/aaaa').classes('w-full').props(data_aio_props).tooltip(tooltip_aio) as data_aio_input:
                pass
            self._data_aio_input = data_aio_input

            status_input = ui.select(
                STATUS_OPTIONS,
                label='Status',
                value=obra['status'] or 'Não Iniciada'
            ).classes('w-full').props('outlined')
            
            ui.separator()
            
            # Checklist
            ui.label('📋 Checklist de Atividades').style('font-size: 18px; font-weight: bold; margin-top: 10px;')
            
            # Dicionário para armazenar temporariamente os estados dos checkboxes
            checklist_estados = {}
            
            checklist_container = ui.column().classes('w-full gap-2')
            
            def atualizar_checklist():
                """Recarrega todos os itens do checklist a partir do banco"""
                checklist_estados.clear()
                checklist_container.clear()
                checklist_atualizado = self.db.obter_checklist(obra_id)
                with checklist_container:
                    for it in checklist_atualizado:
                        self.criar_item_checklist_editavel(it, checklist_estados, obra_id, atualizar_checklist)
            
            with checklist_container:
                for item in checklist:
                    self.criar_item_checklist_editavel(item, checklist_estados, obra_id, atualizar_checklist)
            
            ui.separator()
            
            # Botões de ação
            with ui.row().classes('w-full justify-between'):
                ui.button('🗑️ Excluir Obra', on_click=lambda: self.confirmar_exclusao(dialog, obra_id)).props('color=negative flat')
                
                with ui.row().classes('gap-2'):
                    ui.button('Cancelar', on_click=lambda: [dialog.close(), self.renderizar_obras()]).props('flat')
                    ui.button('💾 Salvar Alterações', on_click=lambda: self.atualizar_obra_dialog(
                        dialog, obra_id, nome_input.value, contrato_input.value,
                        valor_input.value, data_input.value, status_input.value, checklist_estados,
                        checklist_container,  # << PASSA O CONTAINER
                        contrato_ic=contrato_ic_input.value,
                        pedido_sap=pedido_sap_input.value or None,
                        prefixo_agencia=prefixo_agencia_input.value,
                        servico=servico_input.value,
                        valor_parceiro=valor_parceiro_input.value,
                        valor_percentual=valor_percentual_input.value,
                        total_obra=total_obra_input.value,
                        mes_execucao=mes_execucao_input.value,
                        ano_execucao=int(ano_execucao_input.value) if ano_execucao_input.value else None,
                        data_assinatura=data_assinatura_input.value if data_assinatura_input.value else None,
                        data_aio=data_aio_input.value if data_aio_input.value else None,
                        data_acionamento=data_acionamento_input.value if data_acionamento_input.value else None
                    )).props('color=primary')
        
        dialog.open()

        if contrato_fora_da_lista:
            self.notificar('⚠️ Selecione um contrato da lista para continuar.', tipo='warning')
        
        # Verifica se há datas críticas pendentes (tarefas concluídas mas datas não preenchidas)
        datas_pendentes = {}
        if contrato_assinado_concluido and not (obra.get('data_assinatura') or '').strip():
            datas_pendentes['data_assinatura'] = '📝 Data de Assinatura do Contrato'
        if aio_concluido and not (obra.get('data_aio') or '').strip():
            datas_pendentes['data_aio'] = '📅 Data da AIO (Autorização de Início de Obra)'
        
        # Se há datas pendentes, abre um único dialog consolidado
        if datas_pendentes:
            self.abrir_dialog_datas_criticas_consolidado(obra_id, datas_pendentes, atualizar_checklist)

    def criar_item_checklist_editavel(self, item: Dict, checklist_estados: Dict, obra_id: int,
                                       atualizar_checklist_fn=None):
        """Cria um item do checklist no modo de edição.
        Renderiza diretamente a partir dos dados já carregados (sem query extra).
        Ao marcar/desmarcar, atualiza TODO o checklist via atualizar_checklist_fn.
        """
        
        # Verifica se está bloqueado e determina motivo
        bloqueado = bool(item.get('bloqueado', 0))
        motivo_bloqueio = ''
        
        if bloqueado:
            base_calculo = item.get('base_calculo', '')
            if base_calculo == 'assinatura':
                motivo_bloqueio = '🔒 Aguardando data de assinatura do contrato'
            elif base_calculo == 'aio':
                motivo_bloqueio = '🔒 Aguardando data da AIO'
            elif base_calculo == 'criacao':
                motivo_bloqueio = '🔒 Aguardando data de acionamento'
            elif base_calculo == 'fim_tarefa':
                motivo_bloqueio = '🔒 Aguardando conclusão de tarefa dependente'
            else:
                motivo_bloqueio = '🔒 Tarefa bloqueada'
        
        # Calcula dias restantes (se tiver data_limite)
        if item['data_limite'] and not bloqueado:
            dias_restantes = self.calcular_dias_restantes_exibicao(item)
        else:
            dias_restantes = None
        
        # Define cor baseada no status
        if bloqueado:
            cor_status = '#bdbdbd'  # Cinza claro
            texto_status = motivo_bloqueio
        elif item['concluido']:
            cor_status = 'green'
            texto_status = '✓ Concluída'
        elif dias_restantes is not None:
            sufixo_dias = ' dias úteis' if self.usa_dias_uteis_exibicao(item) else ' dias'
            if dias_restantes < 0:
                cor_status = 'red'
                texto_status = f'⚠️ {abs(dias_restantes)}{sufixo_dias} em atraso'
            elif dias_restantes == 0:
                cor_status = 'orange'
                texto_status = f'⏰ Prazo é hoje!'
            elif dias_restantes <= 3:
                cor_status = 'orange'
                texto_status = f'⏰ {dias_restantes}{sufixo_dias} restantes'
            else:
                cor_status = 'gray'
                texto_status = f'📅 {dias_restantes}{sufixo_dias} restantes'
        else:
            cor_status = 'gray'
            texto_status = 'Sem prazo definido'
        
        with ui.card().classes('w-full').style(f'border-left: 3px solid {cor_status}; padding: 10px; {"opacity: 0.6;" if bloqueado else ""}').tooltip(motivo_bloqueio if bloqueado else ''):
            with ui.row().classes('w-full items-center justify-between'):
                with ui.row().classes('items-center gap-3'):
                    # Ícone de cadeado se bloqueado
                    if bloqueado:
                        ui.icon('lock').style('color: #999; font-size: 18px;')
                    
                    # Checkbox - desabilitado se bloqueado
                    checkbox_props = 'disable' if bloqueado else ''
                    checkbox = ui.checkbox(value=bool(item['concluido'])).props(checkbox_props)
                    
                    # Armazena referência para uso posterior no "Salvar"
                    checklist_estados[item['id']] = checkbox
                    
                    # Evento: ao marcar/desmarcar, salva e atualiza TODO o checklist
                    if not bloqueado:
                        def on_change(e, item_id=item['id']):
                            novo_valor = bool(e.value)
                            # Salva no banco imediatamente
                            trigger_ui = self.db.marcar_item_checklist(item_id, novo_valor)
                            
                            # Se marcou como concluído e há trigger_ui, abre dialog de data crítica
                            # Neste caso, o próprio dialog cuidará de atualizar o checklist
                            if trigger_ui and novo_valor and obra_id:
                                self.abrir_dialog_data_critica(obra_id, trigger_ui, atualizar_checklist_fn)
                                return
                            
                            # Se desmarcou e tinha trigger_ui, limpa e desabilita o campo de data na UI
                            if trigger_ui and not novo_valor:
                                trigger_input_map = {
                                    'data_assinatura': '_data_assinatura_input',
                                    'data_aio': '_data_aio_input',
                                }
                                attr_name = trigger_input_map.get(trigger_ui)
                                if attr_name and hasattr(self, attr_name):
                                    input_ref = getattr(self, attr_name)
                                    if input_ref:
                                        try:
                                            input_ref.set_value('')
                                            input_ref.props('outlined disable')
                                        except Exception:
                                            pass
                                
                                # Se cascateou (ex: desmarcar CONTRATO ASSINADO afeta SOLICITAR A DATA DA AIO
                                # que tem trigger_ui=data_aio), limpa também o campo cascateado
                                cascata_map = {
                                    'data_assinatura': 'data_aio',  # assinatura -> aio pode cascatear
                                }
                                cascata_trigger = cascata_map.get(trigger_ui)
                                if cascata_trigger:
                                    cascata_attr = trigger_input_map.get(cascata_trigger)
                                    if cascata_attr and hasattr(self, cascata_attr):
                                        cascata_ref = getattr(self, cascata_attr)
                                        if cascata_ref:
                                            try:
                                                cascata_ref.set_value('')
                                                cascata_ref.props('outlined disable')
                                            except Exception:
                                                pass
                            
                            # Atualiza todo o checklist (inclui itens dependentes)
                            if atualizar_checklist_fn:
                                ui.timer(0.05, atualizar_checklist_fn, once=True)
                        
                        checkbox.on_value_change(on_change)
                    
                    # Informações
                    with ui.column().classes('gap-0'):
                        if item['concluido']:
                            style_texto = 'text-decoration: line-through; color: #999;'
                        elif bloqueado:
                            style_texto = 'color: #999;'
                        else:
                            style_texto = 'font-weight: bold;'
                        ui.label(item['descricao']).style(style_texto)
                        ui.label(texto_status).style(f'font-size: 11px; color: {cor_status};')
                        
                        # Mostra data de conclusão se concluída
                        if item['concluido'] and item.get('data_conclusao'):
                            data_concl_fmt = self.formatar_data_exibicao(item['data_conclusao'])
                            if data_concl_fmt:
                                ui.label(f'✓ Concluída em {data_concl_fmt}').style('font-size: 10px; color: #999; font-style: italic;')
                        
                        # Mostra informações de reiteração se tarefa atrasada
                        if not item['concluido'] and not bloqueado and dias_restantes is not None and dias_restantes < 0:
                            info_reiteracao = self.formatar_info_reiteracao(item)
                            if info_reiteracao:
                                ui.label(info_reiteracao).style('font-size: 10px; color: #ff5722; font-weight: bold;')
                
                # Data limite (se disponível)
                if item['data_limite'] and not bloqueado:
                    data_formatada = self.formatar_data_exibicao(item['data_limite'])
                    
                    if data_formatada == datetime.datetime.today().strftime('%d/%m/%Y'):
                        ui.label(f'⏰ Prazo: {data_formatada} (HOJE!)').style('font-size: 12px; color: red; font-weight: bold;')
                    else:
                        ui.label(f'Prazo: {data_formatada}').style('font-size: 12px; color: #666;')
                elif bloqueado:
                    ui.label('Bloqueada').style('font-size: 12px; color: #999;')
    
    def abrir_dialog_datas_criticas_consolidado(self, obra_id: int, datas_pendentes: Dict[str, str], atualizar_checklist_fn=None):
        """Abre dialog consolidado para preencher múltiplas datas críticas de uma vez."""
        with ui.dialog() as dialog_data, ui.card().style('min-width: 450px; max-width: 550px; padding: 25px;'):
            ui.label('⏰ Datas Críticas Pendentes').style('font-size: 20px; font-weight: bold; margin-bottom: 10px;')
            ui.label('Complete as informações para que os prazos das tarefas possam ser calculados corretamente:').style(
                'color: #666; margin-bottom: 15px; font-size: 14px;'
            )
            
            # Dicionário para armazenar os inputs de data
            data_inputs = {}
            data_hoje_iso = datetime.date.today().strftime('%Y-%m-%d')
            data_hoje_formatada = datetime.date.today().strftime('%d/%m/%Y')
            
            # Cria um campo de data para cada data pendente
            for campo, label in datas_pendentes.items():
                ui.label(label).style('font-size: 14px; font-weight: bold; margin-top: 10px; color: #1976d2;')
                
                with ui.input('Data *', value=data_hoje_formatada, placeholder='dd/mm/aaaa').classes('w-full').props('outlined') as data_input:
                    with ui.menu().props('no-parent-event') as menu:
                        with ui.date(value=data_hoje_iso) as date_picker:
                            date_picker.on('update:model-value', lambda e, inp=data_input: inp.set_value(
                                self.formatar_data_exibicao(e.args) if e.args else ''
                            ))
                            with ui.row().classes('justify-end'):
                                ui.button('Fechar', on_click=menu.close).props('flat')
                    with data_input.add_slot('append'):
                        ui.icon('edit_calendar').on('click', menu.open).classes('cursor-pointer')
                
                data_inputs[campo] = data_input
            
            ui.label('Estas datas críticas serão usadas para calcular prazos de tarefas dependentes.').style(
                'font-size: 11px; color: #999; margin-top: 15px; padding: 10px; background-color: #f5f5f5; border-radius: 4px;'
            )
            
            ui.separator()
            
            # Botões de ação
            with ui.row().classes('w-full justify-end gap-2'):
                def pular_datas():
                    dialog_data.close()
                
                ui.button('Pular por enquanto', on_click=pular_datas).props('flat')
                
                def salvar_todas_datas():
                    """Valida e salva todas as datas críticas."""
                    # Valida se todos os campos foram preenchidos
                    for campo, data_input in data_inputs.items():
                        if not data_input.value or not data_input.value.strip():
                            self.notificar(f'⚠️ Informe a data para {datas_pendentes[campo]}', tipo='warning')
                            return
                    
                    # Salva todas as datas
                    try:
                        for campo, data_input in data_inputs.items():
                            data = self.converter_data_para_iso(data_input.value)
                            self.db.atualizar_data_critica(obra_id, campo, data)
                            self.db.recalcular_checklist(obra_id, campo, data)
                            
                            # Atualiza o input visual se a referência ainda existe
                            if campo == 'data_assinatura' and hasattr(self, '_data_assinatura_input'):
                                try:
                                    self._data_assinatura_input.set_value(self.formatar_data_exibicao(data))
                                except Exception:
                                    pass
                            elif campo == 'data_aio' and hasattr(self, '_data_aio_input'):
                                try:
                                    self._data_aio_input.set_value(self.formatar_data_exibicao(data))
                                except Exception:
                                    pass
                        
                        dialog_data.close()
                        
                        # Atualiza checklist dinamicamente
                        if atualizar_checklist_fn:
                            ui.timer(0.05, atualizar_checklist_fn, once=True)
                        
                        self.notificar('✅ Datas críticas salvas! Prazos recalculados.', tipo='positive')
                    
                    except Exception as e:
                        log_error(e, "agenda_obras", "Salvar datas críticas consolidado")
                        self.notificar(f'❌ Erro ao salvar: {str(e)}', tipo='negative')
                
                ui.button('💾 Salvar Datas', on_click=salvar_todas_datas).props('color=primary')
            
            dialog_data.open()

    def abrir_dialog_data_critica(self, obra_id: int, campo: str, atualizar_checklist_fn=None, dialog_edicao=None):
        """Abre dialog para preencher datas críticas (data_assinatura ou data_aio)
        [DEPRECADO] - Use abrir_dialog_datas_criticas_consolidado para múltiplas datas."""
        obra = self.db.obter_obra(obra_id)

        # Define labels baseado no campo
        labels = {
            'data_assinatura': ('📝 Data de Assinatura do Contrato', 'Informe a data em que o contrato foi assinado:'),
            'data_aio': ('📅 Data da AIO (Autorização de Início de Obra)', 'Informe a data da Autorização de Início de Obra:')
        }

        titulo, descricao = labels.get(campo, ('Preencher Data', 'Informe a data solicitada:'))

        with ui.dialog() as dialog_data, ui.card().style('min-width: 400px; padding: 20px;'):
            ui.label(titulo).style('font-size: 18px; font-weight: bold; margin-bottom: 10px;')
            ui.label(descricao).style('color: #666; margin-bottom: 15px;')

            # Date picker
            data_hoje_formatada = datetime.date.today().strftime('%d/%m/%Y')
            data_hoje_iso = datetime.date.today().strftime('%Y-%m-%d')

            with ui.input('Data *', value=data_hoje_formatada, placeholder='dd/mm/aaaa').classes('w-full').props('outlined') as data_input:
                with ui.menu().props('no-parent-event') as menu:
                    with ui.date(value=data_hoje_iso) as date_picker:
                        date_picker.on('update:model-value', lambda e: data_input.set_value(self.formatar_data_exibicao(e.args) if e.args else ''))
                        with ui.row().classes('justify-end'):
                            ui.button('Fechar', on_click=menu.close).props('flat')
                with data_input.add_slot('append'):
                    ui.icon('edit_calendar').on('click', menu.open).classes('cursor-pointer')

            ui.label('Esta data crítica será usada para calcular prazos de tarefas dependentes.').style(
                'font-size: 11px; color: #999; margin-top: 10px;'
            )

            ui.separator()

            # Botões de ação
            with ui.row().classes('w-full justify-end gap-2'):
                def pular_data_critica():
                    dialog_data.close()
                    if atualizar_checklist_fn:
                        ui.timer(0.05, atualizar_checklist_fn, once=True)

                ui.button('Pular por enquanto', on_click=pular_data_critica).props('flat')

                ui.button('💾 Salvar e Recalcular', on_click=lambda: self.salvar_data_critica(
                    dialog_data, obra_id, campo, data_input.value, atualizar_checklist_fn, dialog_edicao
                )).props('color=primary')

            dialog_data.open()

    def salvar_data_critica(self, dialog, obra_id: int, campo: str, data: str, atualizar_checklist_fn=None, dialog_edicao=None):
        """Salva data crítica e recalcula checklist"""
        if not data:
            self.notificar('⚠️ Informe uma data válida!', tipo='warning')
            return

        try:
            # Converte data para formato ISO
            data_iso = self.converter_data_para_iso(data)

            if campo not in ('data_assinatura', 'data_aio'):
                raise ValueError(f"Campo desconhecido: {campo}")

            # Atualiza APENAS o campo de data crítica
            self.db.atualizar_data_critica(obra_id, campo, data_iso)

            # Recalcula checklist
            self.db.recalcular_checklist(obra_id, campo, data_iso)

            # Atualiza os inputs de data no dialog de edição imediatamente
            data_formatada = self.formatar_data_exibicao(data_iso)
            if campo == 'data_assinatura' and hasattr(self, '_data_assinatura_input'):
                try:
                    self._data_assinatura_input.set_value(data_formatada)
                except Exception:
                    pass
            elif campo == 'data_aio' and hasattr(self, '_data_aio_input'):
                try:
                    self._data_aio_input.set_value(data_formatada)
                except Exception:
                    pass

            # Fecha o dialog de data crítica
            dialog.close()

            # Atualiza checklist dinamicamente
            if atualizar_checklist_fn:
                ui.timer(0.05, atualizar_checklist_fn, once=True)

            campo_label = 'Data de Assinatura' if campo == 'data_assinatura' else 'Data da AIO'
            self.notificar(f'✅ {campo_label} salva! Prazos recalculados.', tipo='positive')

        except Exception as e:
            log_error(e, "agenda_obras", f"Salvar data crítica - campo: {campo}")
            self.notificar(f'❌ Erro ao salvar: {str(e)}', tipo='negative')
    
    def atualizar_obra_dialog(self, dialog, obra_id: int, nome: str, cliente: str,
                            valor: float, data_inicio: str, status: str, checklist_estados: Dict = None, 
                            checklist_container = None, **kwargs):
        """Atualiza obra e checklist a partir do dialog de detalhes"""
        if not nome or not cliente:
            self.notificar('⚠️ Nome e Contrato são obrigatórios!', tipo='warning')
            return
        
        if not valor or valor <= 0:
            self.notificar('⚠️ Valor deve ser maior que zero!', tipo='warning')
            return

        if not self._usuario_pode_acessar_contrato(cliente):
            self.notificar('⛔ Você não possui permissão para alterar para este contrato.', tipo='negative')
            return
        
        try:
            # Converte datas para formato ISO
            data_inicio = self.converter_data_para_iso(data_inicio)
            if 'data_assinatura' in kwargs:
                kwargs['data_assinatura'] = self.converter_data_para_iso(kwargs['data_assinatura'])
            if 'data_aio' in kwargs:
                kwargs['data_aio'] = self.converter_data_para_iso(kwargs['data_aio'])
            if 'data_conclusao' in kwargs:
                kwargs['data_conclusao'] = self.converter_data_para_iso(kwargs['data_conclusao'])
            if 'data_acionamento' in kwargs:
                kwargs['data_acionamento'] = self.converter_data_para_iso(kwargs['data_acionamento'])
            
            # Busca dados antigos para comparação
            obra_antiga = self.db.obter_obra(obra_id)
            
            # Atualiza dados da obra com todos os campos
            requer_recalculo = self.db.atualizar_obra(obra_id, nome, cliente, valor, data_inicio, status, **kwargs)
            
            # Verifica se precisa recalcular datas
            recalculou = False
            datas_recalculadas = []

            if obra_antiga['data_inicio'] != data_inicio:
                self.db.recalcular_checklist(obra_id, 'data_inicio', data_inicio)
                datas_recalculadas.append('data de início')
                recalculou = True
            
            # Verifica se data_acionamento foi alterada
            data_acionamento_nova = kwargs.get('data_acionamento')
            if data_acionamento_nova and obra_antiga.get('data_acionamento') != data_acionamento_nova:
                self.db.recalcular_checklist(obra_id, 'data_acionamento', data_acionamento_nova)
                datas_recalculadas.append('data de acionamento')
                recalculou = True

            # Verifica se data_assinatura foi alterada
            data_assinatura_nova = kwargs.get('data_assinatura')
            if data_assinatura_nova and obra_antiga.get('data_assinatura') != data_assinatura_nova:
                self.db.recalcular_checklist(obra_id, 'data_assinatura', data_assinatura_nova)
                datas_recalculadas.append('data de assinatura')
                recalculou = True
            
            # Verifica se data_aio foi alterada
            data_aio_nova = kwargs.get('data_aio')
            if data_aio_nova and obra_antiga.get('data_aio') != data_aio_nova:
                self.db.recalcular_checklist(obra_id, 'data_aio', data_aio_nova)
                datas_recalculadas.append('data da AIO')
                recalculou = True

            if datas_recalculadas:
                bases = ' e '.join(datas_recalculadas) if len(datas_recalculadas) <= 2 else ', '.join(datas_recalculadas[:-1]) + ' e ' + datas_recalculadas[-1]
                self.notificar(f'🔄 Prazos recalculados com base na {bases}', tipo='info')
            
            # Os checkboxes já salvam no banco instantaneamente via on_value_change,
            # então não é necessário re-salvar aqui.
            
            # Apenas recria o checklist se houve recálculo de datas
            # (os checkboxes já se atualizam dinamicamente quando marcados/desmarcados)
            if recalculou and checklist_container:
                checklist_estados.clear()
                
                def atualizar_checklist_local():
                    checklist_container.clear()
                    checklist = self.db.obter_checklist(obra_id)
                    with checklist_container:
                        for item in checklist:
                            self.criar_item_checklist_editavel(item, checklist_estados, obra_id, atualizar_checklist_local)
                
                atualizar_checklist_local()
            
            # Notifica sucesso
            self.notificar('✅ Obra atualizada!', tipo='positive', timeout=3)
            
            # NÃO fecha o dialog
            # O dialog permanece aberto
            
        except Exception as e:
            log_error(e, "agenda_obras", f"Atualizar obra - ID: {obra_id}")
            self.notificar(f'❌ Erro ao atualizar: {str(e)}', tipo='negative')

    def confirmar_exclusao(self, dialog_pai, obra_id: int):
        """Confirmação de exclusão de obra"""
        with ui.dialog() as dialog_confirm, ui.card().style('padding: 20px;'):
            ui.label('⚠️ Confirmar Exclusão').style('font-size: 18px; font-weight: bold;')
            ui.label('Tem certeza que deseja excluir esta obra?').style('margin: 15px 0;')
            ui.label('Esta ação não pode ser desfeita!').style('color: red; font-size: 12px;')
            
            with ui.row().classes('w-full justify-end gap-2 mt-4'):
                ui.button('Cancelar', on_click=dialog_confirm.close).props('flat')
                ui.button('Excluir', on_click=lambda: self.excluir_obra(
                    dialog_confirm, dialog_pai, obra_id
                )).props('color=negative')
        
        dialog_confirm.open()
    
    def excluir_obra(self, dialog_confirm, dialog_pai, obra_id: int):
        """Exclui obra do banco de dados"""
        try:
            self.db.deletar_obra(obra_id)
            self.notificar('🗑️ Obra excluída com sucesso!', tipo='positive')
            dialog_confirm.close()
            dialog_pai.close()
            self.renderizar_obras()
        except Exception as e:
            log_error(e, "agenda_obras", f"Excluir obra - ID: {obra_id}")
            self.notificar(f'❌ Erro ao excluir: {str(e)}', tipo='negative')
    
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
