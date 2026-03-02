"""
Módulo da interface principal do sistema AgendaObras.
Contém a classe AgendaObras com toda a lógica da interface gráfica usando NiceGUI.
"""

from nicegui import ui
import datetime
from typing import Dict
from database import Database
from email_service import EmailService
from obras_helper import ObrasHelper
from gerador_tarefas_recorrentes import GeradorTarefasRecorrentes
from notificador_prazos import NotificadorPrazos
from version_checker import VersionChecker
from config import VERSION
from error_logger import log_error

# Valores de status padrão (usado tanto no banco quanto na interface)
STATUS_OPTIONS = ['Não Iniciada', 'Em Andamento', 'Atrasada', 'Concluída']


class AgendaObras:
    def __init__(self):
        self.title = "AgendaObras"
        self.description = "Rastreador de Demandas de Engenharia"
        self.timeout_padrao = 3
        
        # Inicializa banco de dados
        self.db = Database()
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
    
    def converter_data_para_iso(self, data_str: str) -> str:
        """Converte data de dd/mm/aaaa para aaaa-mm-dd (formato ISO)
        Retorna string vazia se data_str for vazio
        Retorna a data original se já estiver no formato correto
        """
        if not data_str or not data_str.strip():
            return ''
        
        data_str = data_str.strip()
        
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
        if not data_str or not data_str.strip():
            return ''
        
        data_str = data_str.strip()
        
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
        with ui.header().classes('items-center').style('background-color: #1976d2; padding: 15px;'):
            ui.label('🏗️ AgendaObras').style(
                'font-size: 28px; color: white; font-weight: bold; margin-right: 30px;'
            )
            
            ui.button('➕ Nova Obra', on_click=self.nova_entrada).props('flat').style(
                'color: white; font-weight: bold; margin-right: 10px;'
            )
            
            # Campo de pesquisa
            self.input_pesquisa = ui.input(placeholder='🔍 Pesquisar obras...').props('outlined dense').style(
                'background-color: white; border-radius: 4px; margin-right: 10px; width: 300px;'
            )
            self.input_pesquisa.on('input', lambda: self.pesquisa(self.input_pesquisa.value))
            self.input_pesquisa.on('keydown.enter', lambda: self.pesquisa(self.input_pesquisa.value))
            
            ui.space()
            
            ui.button('🔄 Atualizar', on_click=self.atualizar_dados).props('flat').style(
                'color: white; font-weight: bold;'
            )
    
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
            
            obras = self.db.listar_obras(self.filtro_pesquisa if self.filtro_pesquisa else None)
            
            if not obras:
                with ui.card().classes('w-full').style('padding: 40px; text-align: center;'):
                    if self.filtro_pesquisa:
                        ui.icon('search_off').style('font-size: 48px; color: #bbb; margin-bottom: 10px;')
                        ui.label('Nenhuma obra encontrada').style('font-size: 18px; color: #999;')
                        ui.label(f'Não há obras que correspondam a "{self.filtro_pesquisa}"').style('font-size: 14px; color: #bbb;')
                        ui.button('Limpar pesquisa', on_click=self.atualizar_dados).props('outlined').style('margin-top: 15px;')
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
                            ui.label(f'Cliente: {obra["cliente"]}').style('color: #666; font-size: 13px;')
                        
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
                                dias_restantes = self.helper.calcular_dias_restantes(proxima_tarefa['data_limite'])
                                data_formatada_prazo = self.formatar_data_exibicao(proxima_tarefa['data_limite'])
                                cor_prazo = 'red' if dias_restantes < 0 else 'orange' if dias_restantes <= 3 else 'green'
                                
                                if dias_restantes == 0:
                                    ui.label(f'⏰ Prazo: {data_formatada_prazo} (HOJE!)').style(
                                        f'font-size: 11px; color: {cor_prazo}; margin-left: 20px;'
                                    )
                                else:
                                    ui.label(f'⏰ Prazo: {data_formatada_prazo} ({abs(dias_restantes)} dia{"s" if abs(dias_restantes) != 1 else ""} {"atrasado" if dias_restantes < 0 else "restante" if dias_restantes > 0 else "hoje"})').style(
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
                                dias_restantes = self.helper.calcular_dias_restantes(item['data_limite'])
                                data_formatada = self.formatar_data_exibicao(item['data_limite'])
                                if dias_restantes < 0:
                                    tooltip_text = f"⚠️ Atrasada: {abs(dias_restantes)} dias - Prazo: {data_formatada}"
                                    # Adiciona info de reiteração se houver
                                    info_reiteracao = self.formatar_info_reiteracao(item)
                                    if info_reiteracao:
                                        tooltip_text += f"\n{info_reiteracao}"
                                elif dias_restantes == 0:
                                    tooltip_text = f"Prazo: {data_formatada} (HOJE!)"
                                else:
                                    tooltip_text = f"Prazo: {data_formatada} ({dias_restantes} dias restantes)"
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
                                            dias_restantes = self.helper.calcular_dias_restantes(item['data_limite'])
                                            if dias_restantes < 0:
                                                info_reiteracao = self.formatar_info_reiteracao(item)
                                                if info_reiteracao:
                                                    ui.label(info_reiteracao).style('font-size: 9px; color: #ff5722; font-style: italic;')
    
    # ========== Dialogs ========== #
    def nova_entrada(self):
        """Dialog para adicionar nova obra"""
        with ui.dialog() as dialog, ui.card().style('min-width: 700px; max-width: 900px; padding: 20px; max-height: 90vh; overflow-y: auto;'):
            ui.label('➕ Nova Obra').style('font-size: 22px; font-weight: bold; margin-bottom: 15px;')
            
            # ===== SEÇÃO 1: Informações Básicas =====
            ui.label('📋 Informações Básicas').style('font-size: 16px; font-weight: bold; margin-top: 10px; color: #1976d2;')
            
            # Campos básicos
            nome_input = ui.input(label='Nome do Contrato *').classes('w-full').props('outlined')
            cliente_input = ui.input(label='Cliente *').classes('w-full').props('outlined')
            
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
                    dialog, nome_input.value, cliente_input.value, 
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
            self.notificar('⚠️ Nome do contrato e cliente são obrigatórios!', tipo='warning')
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
            
            with ui.column().classes('w-full gap-3'):
                nome_input = ui.input(label='Nome do Contrato', value=obra['nome_contrato']).classes('w-1/2').props('outlined')
                cliente_input = ui.input(label='Cliente', value=obra['cliente']).classes('w-full').props('outlined')
                
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
                if contrato_assinado_concluido:
                    data_assinatura_input.on('update:model-value', lambda e: self.salvar_data_critica(dialog, obra_id, 'data_assinatura', e.value))
            self._data_assinatura_input = data_assinatura_input

            # Data da AIO (condicional)
            data_aio_props = 'outlined' if aio_concluido else 'outlined disable'
            tooltip_aio = '📅 Data da Autorização de Início de Obra' if aio_concluido else '🔒 Complete a tarefa "SOLICITAR A DATA DA AIO" para desbloquear'
            
            with ui.input('Data da AIO', value=self.formatar_data_exibicao(obra.get('data_aio') or ''), placeholder='dd/mm/aaaa').classes('w-full').props(data_aio_props).tooltip(tooltip_aio) as data_aio_input:
                if aio_concluido:
                    data_aio_input.on('update:model-value', lambda e: self.salvar_data_critica(dialog, obra_id, 'data_aio', e.value))
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
                        dialog, obra_id, nome_input.value, cliente_input.value,
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
        
        # Após abrir o dialog, verifica se há datas críticas pendentes
        # (tarefas concluídas mas datas não preenchidas)
        datas_pendentes = []
        if contrato_assinado_concluido and not (obra.get('data_assinatura') or '').strip():
            datas_pendentes.append('data_assinatura')
        if aio_concluido and not (obra.get('data_aio') or '').strip():
            datas_pendentes.append('data_aio')
        
        for campo in datas_pendentes:
            self.abrir_dialog_data_critica(obra_id, campo, atualizar_checklist)

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
            dias_restantes = self.helper.calcular_dias_restantes(item['data_limite'])
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
            if dias_restantes < 0:
                cor_status = 'red'
                texto_status = f'⚠️ {abs(dias_restantes)} dias em atraso'
            elif dias_restantes == 0:
                cor_status = 'orange'
                texto_status = f'⏰ Prazo é hoje!'
            elif dias_restantes <= 3:
                cor_status = 'orange'
                texto_status = f'⏰ {dias_restantes} dias restantes'
            else:
                cor_status = 'gray'
                texto_status = f'📅 {dias_restantes} dias restantes'
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
    
    def abrir_dialog_data_critica(self, obra_id: int, campo: str, atualizar_checklist_fn=None, dialog_edicao=None):
        """Abre dialog para preencher datas críticas (data_assinatura ou data_aio)"""
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
        print(f"DEBUG: Iniciando salvar_data_critica com obra_id={obra_id}, campo={campo}, data={data}")
        if not data:
            self.notificar('⚠️ Informe uma data válida!', tipo='warning')
            print("DEBUG: Data inválida fornecida.")
            return

        try:
            # Converte data para formato ISO
            data = self.converter_data_para_iso(data)
            print(f"DEBUG: Data convertida para formato ISO: {data}")

            if campo not in ('data_assinatura', 'data_aio'):
                raise ValueError(f"Campo desconhecido: {campo}")

            # Atualiza APENAS o campo de data crítica (sem sobrescrever outros campos da obra)
            self.db.atualizar_data_critica(obra_id, campo, data)
            print(f"DEBUG: Campo {campo} atualizado com valor: {data}")

            # Recalcula checklist
            self.db.recalcular_checklist(obra_id, campo, data)
            print(f"DEBUG: Checklist recalculado para campo={campo}, data={data}")

            # Atualiza os inputs de data no dialog de edição imediatamente
            # (usa referências armazenadas como atributos da instância)
            data_formatada = self.formatar_data_exibicao(data)
            if campo == 'data_assinatura':
                if hasattr(self, '_data_assinatura_input') and self._data_assinatura_input:
                    try:
                        self._data_assinatura_input.set_value(data_formatada)
                        self._data_assinatura_input.props('outlined')  # Desbloqueia o campo
                        print("DEBUG: Campo data_assinatura atualizado no dialog de edição.")
                    except Exception:
                        print("DEBUG: Não foi possível atualizar data_assinatura_input (dialog pode ter sido fechado).")
            elif campo == 'data_aio':
                if hasattr(self, '_data_aio_input') and self._data_aio_input:
                    try:
                        self._data_aio_input.set_value(data_formatada)
                        self._data_aio_input.props('outlined')  # Desbloqueia o campo
                        print("DEBUG: Campo data_aio atualizado no dialog de edição.")
                    except Exception:
                        print("DEBUG: Não foi possível atualizar data_aio_input (dialog pode ter sido fechado).")

            # Fecha o dialog de data crítica
            dialog.close()
            print("DEBUG: Dialog de data crítica fechado.")

            # Atualiza checklist dinamicamente (com timer para evitar race condition)
            if atualizar_checklist_fn:
                ui.timer(0.05, atualizar_checklist_fn, once=True)
                print("DEBUG: Checklist será atualizado dinamicamente.")

            campo_label = 'Data de Assinatura' if campo == 'data_assinatura' else 'Data da AIO'
            self.notificar(f'✅ {campo_label} salva! Prazos recalculados.', tipo='positive')

        except Exception as e:
            log_error(e, "agenda_obras", f"Salvar data crítica - campo: {campo}")
            self.notificar(f'❌ Erro ao salvar: {str(e)}', tipo='negative')
            print(f"DEBUG: Erro ao salvar data crítica: {e}")
    
    def atualizar_obra_dialog(self, dialog, obra_id: int, nome: str, cliente: str,
                            valor: float, data_inicio: str, status: str, checklist_estados: Dict = None, 
                            checklist_container = None, **kwargs):
        """Atualiza obra e checklist a partir do dialog de detalhes"""
        if not nome or not cliente:
            self.notificar('⚠️ Nome e cliente são obrigatórios!', tipo='warning')
            return
        
        if not valor or valor <= 0:
            self.notificar('⚠️ Valor deve ser maior que zero!', tipo='warning')
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
