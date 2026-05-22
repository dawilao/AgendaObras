"""
Mixin com todos os dialogs de obra: nova obra, detalhes/edição, checklist, datas críticas,
medições, conclusão e exclusão.
"""

from nicegui import ui
import datetime
from core.error_logger import log_error
from services.auth_service import obter_usuario_logado
from utils.formatters import (
    STATUS_OPTIONS,
    STATUS_VISUAL_EDICAO_OPTIONS,
    rotulo_alterar_medicoes,
    status_edicao_para_banco,
    datas_iguais_normalizadas,
    converter_data_para_iso,
    formatar_data_exibicao,
)
from services.obra_service import status_visual_para_edicao, obra_tem_medicoes_concluidas

TAREFA_SOLICITACAO_ACESSO = 'SOLICITAÇÃO DE ACESSO'
TAREFA_RENOVACAO_ACESSO = 'RENOVAÇÃO DE SOLICITAÇÃO DE ACESSO'


class ObraDialogsMixin:
    def nova_entrada(self):
        """Dialog para adicionar nova obra"""
        permissoes = self._obter_permissoes_usuario()

        with ui.dialog() as dialog, ui.card().classes('responsive-dialog-lg').style('padding: 20px; max-height: 90vh; overflow-y: auto;'):
            ui.label('➕ Nova Obra').style('font-size: 22px; font-weight: bold; margin-bottom: 15px;')

            ui.label('📋 Informações Básicas').style('font-size: 16px; font-weight: bold; margin-top: 10px; color: #1976d2;')

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

            with ui.row().classes('w-full gap-2 flex-wrap'):
                contrato_ic_input = ui.input(label='Contrato (IC)').classes('w-full').props('outlined')
                pedido_sap_input = ui.input(label='Pedido SAP').classes('w-full').props('outlined')
                prefixo_agencia_input = ui.input(label='Prefixo Agência').classes('w-full').props('outlined')

            with ui.input('Data de Acionamento', value='', placeholder='dd/mm/aaaa').classes('w-full').props('outlined').tooltip('📅 Data usada como base para calcular prazos iniciais (ex: RETORNO PROJETO E ORÇAMENTO). Se não informada, será usada a data de criação do card.') as data_acionamento_input:
                with ui.menu().props('no-parent-event') as menu_acionamento:
                    with ui.date(value='') as date_picker_acionamento:
                        date_picker_acionamento.on('update:model-value', lambda e: data_acionamento_input.set_value(formatar_data_exibicao(e.args) if e.args else ''))
                        with ui.row().classes('justify-end'):
                            ui.button('Fechar', on_click=menu_acionamento.close).props('flat')
                with data_acionamento_input.add_slot('append'):
                    ui.icon('edit_calendar').on('click', menu_acionamento.open).classes('cursor-pointer')

            servico_input = ui.input(label='Serviço').classes('w-full').props('outlined')

            ui.separator().classes('my-4')

            ui.label('💰 Valores Financeiros').style('font-size: 16px; font-weight: bold; color: #1976d2;')

            with ui.row().classes('w-full gap-2 flex-wrap'):
                valor_input = ui.number(label='Valor do Contrato (R$) *', min=0, step=0.01, format='%.2f').classes('w-full sm:w-[32%]').props('outlined')
                valor_percentual_input = ui.number(label='% Parceiro', min=0, max=100, step=0.01, format='%.2f').classes('w-full sm:w-[32%]').props('outlined')
                valor_parceiro_input = ui.number(label='Valor Parceiro (R$)', min=0, step=0.01, format='%.2f').classes('w-full sm:w-[32%]').props('outlined readonly')

            def _atualizar_parceiro_nova():
                vc = float(valor_input.value or 0)
                pct = float(valor_percentual_input.value or 0)
                valor_parceiro_input.set_value(round(vc * pct / 100, 2))

            valor_input.on_value_change(lambda e: _atualizar_parceiro_nova())
            valor_percentual_input.on_value_change(lambda e: _atualizar_parceiro_nova())

            total_obra_input = ui.number(label='Total da Obra (R$) *', min=0, step=0.01, format='%.2f').classes('w-full').props('outlined').tooltip('💰 [OBRIGATÓRIO] Valor total da obra para rastreamento financeiro da Fase 3')

            ui.separator().classes('my-4')

            ui.label('📅 Prazos e Datas').style('font-size: 16px; font-weight: bold; color: #1976d2;')

            with ui.row().classes('w-full gap-2 flex-wrap'):
                meses = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
                         'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro']
                mes_execucao_input = ui.select(meses, label='Mês de Execução').classes('w-full sm:w-[49%]').props('outlined')
                ano_execucao_input = ui.number(label='Ano', value=datetime.date.today().year, min=2020, max=2050, step=1).classes('w-full sm:w-[49%]').props('outlined')

            with ui.input('Data de início da obra', value='', placeholder='dd/mm/aaaa').classes('w-full').props('outlined').tooltip('📅 Data em que a obra deve começar. Este campo será preenchido pelo coordenador.') as data_input:
                with ui.menu().props('no-parent-event') as menu:
                    with ui.date(value='') as date_picker:
                        date_picker.on('update:model-value', lambda e: data_input.set_value(formatar_data_exibicao(e.args) if e.args else ''))
                        with ui.row().classes('justify-end'):
                            ui.button('Fechar', on_click=menu.close).props('flat')
                with data_input.add_slot('append'):
                    ui.icon('edit_calendar').on('click', menu.open).classes('cursor-pointer')

            with ui.input('Data de Assinatura do Contrato', value='', placeholder='dd/mm/aaaa').classes('w-full').props('outlined disable').tooltip('🔒 Será desbloqueado quando a tarefa "CONTRATO ASSINADO" for concluída') as data_assinatura_input:
                with ui.menu().props('no-parent-event') as menu_assinatura:
                    with ui.date() as date_picker_assinatura:
                        date_picker_assinatura.on('update:model-value', lambda e: data_assinatura_input.set_value(formatar_data_exibicao(e.args) if e.args else ''))
                        with ui.row().classes('justify-end'):
                            ui.button('Fechar', on_click=menu_assinatura.close).props('flat')
                with data_assinatura_input.add_slot('append'):
                    ui.icon('lock').classes('cursor-not-allowed')

            with ui.input('Data da AIO', value='', placeholder='dd/mm/aaaa').classes('w-full').props('outlined disable').tooltip('🔒 Será desbloqueado quando a tarefa "SOLICITAR A DATA DA AIO" for concluída') as data_aio_input:
                with ui.menu().props('no-parent-event') as menu_aio:
                    with ui.date() as date_picker_aio:
                        date_picker_aio.on('update:model-value', lambda e: data_aio_input.set_value(formatar_data_exibicao(e.args) if e.args else ''))
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
        if not nome or not cliente:
            self.notificar('Nome do contrato e Contrato são obrigatórios!', tipo='warning')
            return

        if not self._usuario_pode_acessar_contrato(cliente):
            self.notificar('⛔ Você não possui permissão para criar obra neste contrato.', tipo='negative')
            return

        if not valor or valor <= 0:
            self.notificar('Valor do contrato deve ser maior que zero!', tipo='warning')
            return

        total_obra = kwargs.get('total_obra')
        if not total_obra or total_obra <= 0:
            self.notificar('Total da Obra é obrigatório e deve ser maior que zero!', tipo='warning')
            return

        try:
            data_inicio = converter_data_para_iso(data_inicio)
            if 'data_assinatura' in kwargs:
                kwargs['data_assinatura'] = converter_data_para_iso(kwargs['data_assinatura'])
            if 'data_aio' in kwargs:
                kwargs['data_aio'] = converter_data_para_iso(kwargs['data_aio'])
            if 'data_conclusao' in kwargs:
                kwargs['data_conclusao'] = converter_data_para_iso(kwargs['data_conclusao'])
            if 'data_acionamento' in kwargs:
                kwargs['data_acionamento'] = converter_data_para_iso(kwargs['data_acionamento'])

            obra_id = self.db.criar_obra(nome, cliente, valor, data_inicio, status, **kwargs)

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
            self.notificar('Obra não encontrada.', tipo='warning')
            return

        if not self._usuario_pode_acessar_contrato(obra.get('cliente')):
            self.notificar('⛔ Você não tem acesso a este contrato.', tipo='negative')
            return

        checklist = self.db.obter_checklist(obra_id)
        status_conclusao = (obra.get('status_conclusao_obra') or '').strip().lower()
        status_visual_edicao = status_visual_para_edicao(obra, checklist)

        contrato_assinado_concluido = any(
            item['descricao'] == 'CONTRATO ASSINADO' and item['concluido']
            for item in checklist
        )
        aio_concluido = any(
            item['descricao'] == 'SOLICITAR A DATA DA AIO' and item['concluido']
            for item in checklist
        )

        with ui.dialog() as dialog, ui.card().classes('responsive-dialog-lg').style('padding: 20px; max-height: 90vh; overflow-y: auto;'):
            with ui.row().classes('w-full items-center justify-between'):
                ui.label(f'{obra["nome_contrato"]}').style('font-size: 22px; font-weight: bold;')
                ui.button(icon='close', on_click=lambda: fechar_dialog_com_autosalvamento()).props('flat round')

            if status_conclusao == 'com_pendencias':
                with ui.card().classes('w-full').style('background: #fff8e1; border-left: 4px solid #f57c00; padding: 12px; margin-top: 10px;'):
                    ui.label('⚠️ Esta obra foi concluída com pendências.').style('font-size: 13px; font-weight: bold; color: #f57c00;')
                    ui.label('Use este botão somente quando todas as pendências já tiverem sido resolvidas.').style('font-size: 12px; color: #8a5a00;')

                    def resolver_pendencias_obra():
                        try:
                            self.db.registrar_finalizacao_obra(obra_id, 'sem_pendencias')
                            obra['status_conclusao_obra'] = 'sem_pendencias'
                            self.notificar('✅ Pendências resolvidas. O card agora será exibido como Concluído.', tipo='positive')
                            try:
                                dialog.close()
                            except Exception:
                                pass
                            ui.timer(0.05, self.renderizar_obras, once=True)
                        except Exception as e:
                            log_error(e, 'agenda_obras', 'Resolver pendências da obra')
                            self.notificar(f'❌ Erro ao resolver pendências: {e}', tipo='negative')

                    ui.button('✅ Marcar pendências como resolvidas', on_click=resolver_pendencias_obra).props('color=positive')

            ui.separator()

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
                nome_input = ui.input(label='Nome do Contrato', value=obra['nome_contrato']).classes('w-full sm:w-1/2').props('outlined')
                contrato_input = ui.select(
                    contratos_disponiveis,
                    label='Contrato *',
                    value=valor_inicial_contrato
                ).classes('w-full').props('outlined')

                if not contratos_disponiveis:
                    ui.label('⚠️ Nenhum contrato disponível em contratos.db').style('color: #f44336; font-size: 12px;')
                elif contrato_fora_da_lista:
                    ui.label('⚠️ O contrato atual não existe na lista. Selecione um contrato válido para salvar.').style('color: #f44336; font-size: 12px;')

                with ui.row().classes('w-full gap-2 flex-wrap'):
                    contrato_ic_input = ui.input(label='Contrato (IC)', value=obra.get('contrato_ic') or '').classes('w-full').props('outlined')
                    pedido_sap_input = ui.input(label='Pedido SAP', value=obra.get('pedido_sap') or '').classes('w-full').props('outlined')
                    prefixo_agencia_input = ui.input(label='Prefixo Agência', value=obra.get('prefixo_agencia') or '').classes('w-full').props('outlined')

                with ui.input('Data de Acionamento', value=formatar_data_exibicao(obra.get('data_acionamento') or ''), placeholder='dd/mm/aaaa').classes('w-full').props('outlined').tooltip('📅 Data usada como base para calcular prazos iniciais. Se alterada, os prazos das tarefas dependentes serão recalculados.') as data_acionamento_input:
                    with ui.menu().props('no-parent-event') as menu_acionamento:
                        with ui.date(value=obra.get('data_acionamento') or '') as date_picker_acionamento:
                            date_picker_acionamento.on('update:model-value', lambda e: data_acionamento_input.set_value(formatar_data_exibicao(e.args) if e.args else ''))
                            with ui.row().classes('justify-end'):
                                ui.button('Fechar', on_click=menu_acionamento.close).props('flat')
                    with data_acionamento_input.add_slot('append'):
                        ui.icon('edit_calendar').on('click', menu_acionamento.open).classes('cursor-pointer')

                servico_input = ui.input(label='Serviço', value=obra.get('servico') or '').classes('w-full').props('outlined')

            ui.separator().classes('my-4')

            ui.label('💰 Valores Financeiros').style('font-size: 16px; font-weight: bold; color: #1976d2;')

            with ui.row().classes('w-full gap-2 flex-wrap'):
                valor_input = ui.number(label='Valor do Contrato (R$)', value=obra['valor_contrato'], min=0, step=0.01, format='%.2f').classes('w-full sm:w-[32%]').props('outlined')
                valor_percentual_input = ui.number(label='% Parceiro', value=obra.get('valor_percentual') or 0, min=0, max=100, step=0.01, format='%.2f').classes('w-full sm:w-[32%]').props('outlined')
                valor_parceiro_input = ui.number(label='Valor Parceiro (R$)', value=obra.get('valor_parceiro') or 0, min=0, step=0.01, format='%.2f').classes('w-full sm:w-[32%]').props('outlined readonly')

            def _atualizar_parceiro_edicao():
                vc = float(valor_input.value or 0)
                pct = float(valor_percentual_input.value or 0)
                valor_parceiro_input.set_value(round(vc * pct / 100, 2))

            valor_input.on_value_change(lambda e: _atualizar_parceiro_edicao())
            valor_percentual_input.on_value_change(lambda e: _atualizar_parceiro_edicao())
            _atualizar_parceiro_edicao()

            total_obra_input = ui.number(label='Total da Obra (R$) *', value=obra.get('total_obra') or 0, min=0, step=0.01, format='%.2f').classes('w-full').props('outlined').tooltip('💰 [OBRIGATÓRIO] Valor total da obra para rastreamento financeiro da Fase 3')

            ui.separator().classes('my-4')

            ui.label('📅 Prazos e Datas').style('font-size: 16px; font-weight: bold; color: #1976d2;')

            with ui.row().classes('w-full gap-2 flex-wrap'):
                meses = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
                         'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro']
                mes_execucao_input = ui.select(meses, label='Mês de Execução', value=obra.get('mes_execucao')).classes('w-full sm:w-[49%]').props('outlined')
                ano_execucao_input = ui.number(label='Ano', value=obra.get('ano_execucao') or datetime.date.today().year, min=2020, max=2050, step=1).classes('w-full sm:w-[49%]').props('outlined')

            with ui.input('Data de início da obra', value=formatar_data_exibicao(obra.get('data_inicio') or ''), placeholder='dd/mm/aaaa').classes('w-full').props('outlined').tooltip('📅 Data em que a obra deve começar. Este campo será preenchido pelo coordenador.') as data_input:
                with ui.menu().props('no-parent-event') as menu:
                    with ui.date(value=obra.get('data_inicio') or '') as date_picker:
                        date_picker.on('update:model-value', lambda e: data_input.set_value(formatar_data_exibicao(e.args) if e.args else ''))
                        with ui.row().classes('justify-end'):
                            ui.button('Fechar', on_click=menu.close).props('flat')
                with data_input.add_slot('append'):
                    ui.icon('edit_calendar').on('click', menu.open).classes('cursor-pointer')

            data_assinatura_props = 'outlined' if contrato_assinado_concluido else 'outlined disable'
            tooltip_assinatura = '📅 Data de assinatura do contrato' if contrato_assinado_concluido else '🔒 Complete a tarefa "CONTRATO ASSINADO" para desbloquear'

            with ui.input('Data de Assinatura do Contrato', value=formatar_data_exibicao(obra.get('data_assinatura') or ''), placeholder='dd/mm/aaaa').classes('w-full').props(data_assinatura_props).tooltip(tooltip_assinatura) as data_assinatura_input:
                pass
            self._data_assinatura_input = data_assinatura_input

            data_aio_props = 'outlined' if aio_concluido else 'outlined disable'
            tooltip_aio = '📅 Data da Autorização de Início de Obra' if aio_concluido else '🔒 Complete a tarefa "SOLICITAR A DATA DA AIO" para desbloquear'

            with ui.input('Data da AIO', value=formatar_data_exibicao(obra.get('data_aio') or ''), placeholder='dd/mm/aaaa').classes('w-full').props(data_aio_props).tooltip(tooltip_aio) as data_aio_input:
                pass
            self._data_aio_input = data_aio_input

            status_input = ui.select(
                STATUS_VISUAL_EDICAO_OPTIONS,
                label='Status',
                value=status_visual_edicao
            ).classes('w-full').props('outlined')
            self._status_input_atual = status_input

            ui.label('📝 Observações').style('font-size: 16px; font-weight: bold; color: #1976d2; margin-top: 10px;')
            observacoes_input = ui.textarea(
                label='Observações da Obra',
                value=obra.get('observacoes') or '',
                placeholder='Digite observações da obra...'
            ).classes('w-full').props('outlined autogrow rows=4')

            self._observacoes_input_atual = observacoes_input

            obs_usuario = (obra.get('obs_usuario') or '').strip()
            obs_data = (obra.get('obs_data') or '').strip()
            if obs_usuario and obs_data:
                try:
                    obs_data_fmt = datetime.datetime.strptime(obs_data, '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y %H:%M')
                except Exception:
                    obs_data_fmt = obs_data
                ui.label(f'Última atualização: {obs_usuario} em {obs_data_fmt}').style('font-size: 11px; color: #777;')

            ui.separator()

            ui.label('📋 Checklist de Atividades').style('font-size: 18px; font-weight: bold; margin-top: 10px;')

            checklist_estados = {}

            checklist_container = ui.column().classes('w-full gap-2')

            medicoes_registro = self.db.obter_medicoes_obra(obra_id)
            quantidade_medicoes = int((medicoes_registro or {}).get('quantidade') or 0)
            data_inicio_preenchida = bool((obra.get('data_inicio') or '').strip())
            botao_medicoes = None

            with ui.row().classes('w-full items-center justify-between gap-2'):
                ui.label('Configuração de medições').style('font-size: 12px; color: #666; font-weight: bold;')
                if data_inicio_preenchida:
                    botao_medicoes = ui.button(
                        rotulo_alterar_medicoes(quantidade_medicoes, True),
                        on_click=lambda: self.abrir_dialog_selecionar_medicoes(obra_id, atualizar_checklist, botao_medicoes)
                    )
                    botao_medicoes.props('flat color=primary size=sm')
                else:
                    ui.button('Alterar medições', on_click=None).props('flat color=primary size=sm disable').tooltip('Preencha a Data de início da obra para configurar as medições.')

            autosave_em_execucao = {'ativo': False}

            def autosalvar_ao_sair():
                """Salva observações pendentes ao sair do diálogo de edição."""
                if autosave_em_execucao['ativo']:
                    return
                autosave_em_execucao['ativo'] = True
                try:
                    observacoes_nova = (observacoes_input.value or '').strip()
                    observacoes_antiga = (obra.get('observacoes') or '').strip()

                    if observacoes_nova != observacoes_antiga:
                        usuario = obter_usuario_logado() or {}
                        nome_usuario = ' '.join([
                            (usuario.get('nome') or '').strip(),
                            (usuario.get('sobrenome') or '').strip(),
                        ]).strip() or (usuario.get('email') or '').strip() or 'Sistema'

                        obs_data = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S') if observacoes_nova else None
                        obs_usuario = nome_usuario if observacoes_nova else None

                        sucesso = self.db.atualizar_observacoes_obra(
                            obra_id,
                            observacoes_nova,
                            obs_usuario,
                            obs_data,
                        )

                        if sucesso:
                            obra['observacoes'] = observacoes_nova
                            obra['obs_usuario'] = obs_usuario or ''
                            obra['obs_data'] = obs_data or ''
                        else:
                            self.notificar('Não foi possível salvar automaticamente as observações.', tipo='warning')
                except Exception as e:
                    log_error(e, "agenda_obras", f"Auto-save ao sair do diálogo da obra - ID: {obra_id}")
                finally:
                    autosave_em_execucao['ativo'] = False

            def fechar_dialog_com_autosalvamento():
                autosalvar_ao_sair()
                dialog.close()

            dialog.on('hide', lambda e: [autosalvar_ao_sair(), self.renderizar_obras()])

            def atualizar_checklist():
                """Recarrega todos os itens do checklist a partir do banco"""
                checklist_estados.clear()
                checklist_container.clear()
                checklist_atualizado = self.db.obter_checklist(obra_id)
                with checklist_container:
                    for it in checklist_atualizado:
                        self.criar_item_checklist_editavel(it, checklist_estados, obra_id, atualizar_checklist, checklist_completo=checklist_atualizado)

                obra_atualizada = self.db.obter_obra(obra_id) or obra
                novo_status = status_visual_para_edicao(obra_atualizada, checklist_atualizado)
                try:
                    status_input.value = novo_status
                    status_input.update()
                except Exception:
                    pass

            with checklist_container:
                for item in checklist:
                    self.criar_item_checklist_editavel(item, checklist_estados, obra_id, atualizar_checklist, checklist_completo=checklist)

            ui.separator()

            pode_excluir = permissoes['is_admin']
            with ui.row().classes('w-full justify-between'):
                botao_excluir = ui.button(
                    '🗑️ Excluir Obra',
                    on_click=(lambda: self.confirmar_exclusao(dialog, obra_id)) if pode_excluir else None,
                ).props('color=negative flat' + ('' if pode_excluir else ' disable'))

                if not pode_excluir:
                    botao_excluir.tooltip('Somente administradores podem excluir cards/obras.')

                with ui.row().classes('gap-2'):
                    ui.button('Cancelar', on_click=lambda: fechar_dialog_com_autosalvamento()).props('flat')
                    ui.button('💾 Salvar Alterações', on_click=lambda: self.atualizar_obra_dialog(
                        dialog, obra_id, nome_input.value, contrato_input.value,
                        valor_input.value, data_input.value, status_input.value, checklist_estados,
                        checklist_container,
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
                        data_acionamento=data_acionamento_input.value if data_acionamento_input.value else None,
                        observacoes=observacoes_input.value
                    )).props('color=primary')

        dialog.open()

        if contrato_fora_da_lista:
            self.notificar('Selecione um contrato da lista para continuar.', tipo='warning')

        datas_pendentes = {}
        if contrato_assinado_concluido and not (obra.get('data_assinatura') or '').strip():
            datas_pendentes['data_assinatura'] = '📝 Data de Assinatura do Contrato'
        if aio_concluido and not (obra.get('data_aio') or '').strip():
            datas_pendentes['data_aio'] = '📅 Data da AIO (Autorização de Início de Obra)'

        if datas_pendentes:
            self.abrir_dialog_datas_criticas_consolidado(obra_id, datas_pendentes, atualizar_checklist)

    def criar_item_checklist_editavel(self, item, checklist_estados, obra_id: int,
                                      atualizar_checklist_fn=None, checklist_completo=None):
        """Cria um item do checklist no modo de edição."""
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

        if item['data_limite'] and not bloqueado:
            dias_restantes = self.calcular_dias_restantes_exibicao(item)
        else:
            dias_restantes = None

        if bloqueado:
            cor_status = '#bdbdbd'
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
                    if bloqueado:
                        ui.icon('lock').style('color: #999; font-size: 18px;')

                    checkbox_props = 'disable' if bloqueado else ''
                    checkbox = ui.checkbox(value=bool(item['concluido'])).props(checkbox_props)

                    checklist_estados[item['id']] = checkbox

                    if not bloqueado:
                        def on_change(e, item_id=item['id'], item_descricao=item.get('descricao', '')):
                            novo_valor = bool(e.value)

                            if novo_valor and item_descricao == TAREFA_SOLICITACAO_ACESSO:
                                try:
                                    self.abrir_dialog_dados_acesso(obra_id, item_id, e.sender, atualizar_checklist_fn)
                                except Exception as exc:
                                    log_error(exc, 'agenda_obras', f'Erro ao abrir dialog de acesso - item {item_id}')
                                return

                            if novo_valor and item_descricao == TAREFA_RENOVACAO_ACESSO:
                                try:
                                    self.abrir_dialog_nova_renovacao_acesso(obra_id, item_id, e.sender, atualizar_checklist_fn)
                                except Exception as exc:
                                    log_error(exc, 'agenda_obras', f'Erro ao abrir dialog de nova renovação de acesso - item {item_id}')
                                return

                            if novo_valor and item_descricao.startswith('CONFIRMAÇÃO DE MEDIÇÃO'):
                                try:
                                    self.abrir_dialog_valor_medicao(obra_id, item_id, e.sender, atualizar_checklist_fn)
                                except Exception as exc:
                                    log_error(exc, 'agenda_obras', f'Erro ao abrir dialog de medicao - item {item_id}')
                                return

                            trigger_ui = self.db.marcar_item_checklist(item_id, novo_valor)

                            if novo_valor and not trigger_ui and item_descricao.startswith('MEDIÇÃO ') and obra_tem_medicoes_concluidas(self.db, obra_id):
                                ui.timer(0.1, lambda: self.abrir_dialog_conclusao_obra(obra_id, atualizar_checklist_fn, getattr(self, '_observacoes_input_atual', None)), once=True)
                                return

                            if trigger_ui and novo_valor and obra_id:
                                self.abrir_dialog_data_critica(obra_id, trigger_ui, atualizar_checklist_fn)
                                return

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

                                cascata_map = {
                                    'data_assinatura': 'data_aio',
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

                            if atualizar_checklist_fn:
                                ui.timer(0.05, atualizar_checklist_fn, once=True)

                        checkbox.on_value_change(on_change)

                    with ui.column().classes('gap-0'):
                        if item['concluido']:
                            style_texto = 'text-decoration: line-through; color: #999;'
                        elif bloqueado:
                            style_texto = 'color: #999;'
                        else:
                            style_texto = 'font-weight: bold;'
                        ui.label(item['descricao']).style(style_texto)
                        ui.label(texto_status).style(f'font-size: 11px; color: {cor_status};')

                        if item['concluido'] and item.get('data_conclusao'):
                            data_concl_fmt = formatar_data_exibicao(item['data_conclusao'])
                            if data_concl_fmt:
                                ui.label(f'✓ Concluída em {data_concl_fmt}').style('font-size: 10px; color: #999; font-style: italic;')

                        if item['concluido'] and item.get('descricao') == TAREFA_SOLICITACAO_ACESSO:
                            renovacao_concluida = any(
                                (it.get('descricao') or '').strip() == TAREFA_RENOVACAO_ACESSO and it.get('concluido')
                                for it in (checklist_completo or [])
                            )
                            dados_acesso = self.db.obter_dados_acesso(item['id'])
                            with ui.row().classes('items-center gap-2').style('margin-top: 6px; flex-wrap: wrap;'):
                                if dados_acesso and dados_acesso.get('data_fim_acesso'):
                                    inicio_fmt = formatar_data_exibicao(dados_acesso.get('data_inicio_acesso') or '')
                                    fim_fmt = formatar_data_exibicao(dados_acesso['data_fim_acesso'])
                                    periodo = f'{inicio_fmt} → {fim_fmt}' if inicio_fmt else fim_fmt
                                    if renovacao_concluida:
                                        ui.label(f'Acesso: {periodo}').style('color: #666; font-size: 13px;')
                                    else:
                                        ui.label(f'Acesso: {periodo}').style(
                                            'font-size: 12px; font-weight: 600; color: #1565c0;'
                                            'background: #e3f2fd; padding: 3px 10px;'
                                            'border-radius: 12px; border: 1px solid #90caf9;'
                                        )
                                else:
                                    ui.label('Datas de acesso não informadas').style(
                                        'font-size: 12px; font-weight: 600; color: #bf360c;'
                                        'background: #fbe9e7; padding: 3px 10px;'
                                        'border-radius: 12px; border: 1px solid #ffab91;'
                                    )
                                if not renovacao_concluida:
                                    ui.button('Editar acesso', icon='edit_calendar',
                                              on_click=lambda _obra_id=obra_id, _item=item: self.abrir_dialog_dados_acesso(
                                                  _obra_id, _item['id'], None, atualizar_checklist_fn
                                              )).props('outline dense color=primary size=sm')

                        if not item['concluido'] and not bloqueado and dias_restantes is not None and dias_restantes < 0:
                            info_reiteracao = self.formatar_info_reiteracao(item)
                            if info_reiteracao:
                                ui.label(info_reiteracao).style('font-size: 10px; color: #ff5722; font-weight: bold;')

                if item['data_limite'] and not bloqueado:
                    data_formatada = formatar_data_exibicao(item['data_limite'])

                    if item['concluido']:
                        ui.label(f'Prazo: {data_formatada}').style('font-size: 12px; color: #666; text-decoration: line-through;')
                    elif data_formatada == datetime.datetime.today().strftime('%d/%m/%Y'):
                        ui.label(f'⏰ Prazo: {data_formatada} (HOJE!)').style('font-size: 12px; color: red; font-weight: bold;')
                    else:
                        ui.label(f'Prazo: {data_formatada}').style('font-size: 12px; color: #666;')
                elif bloqueado:
                    ui.label('Bloqueada').style('font-size: 12px; color: #999;')

    def abrir_dialog_datas_criticas_consolidado(self, obra_id: int, datas_pendentes, atualizar_checklist_fn=None):
        """Abre dialog consolidado para preencher múltiplas datas críticas de uma vez."""
        with ui.dialog() as dialog_data, ui.card().classes('responsive-dialog-sm').style('padding: 20px;'):
            ui.label('⏰ Datas Críticas Pendentes').style('font-size: 20px; font-weight: bold; margin-bottom: 10px;')
            ui.label('Complete as informações para que os prazos das tarefas possam ser calculados corretamente:').style(
                'color: #666; margin-bottom: 15px; font-size: 14px;'
            )

            data_inputs = {}
            data_hoje_iso = datetime.date.today().strftime('%Y-%m-%d')
            data_hoje_formatada = datetime.date.today().strftime('%d/%m/%Y')

            for campo, label in datas_pendentes.items():
                ui.label(label).style('font-size: 14px; font-weight: bold; margin-top: 10px; color: #1976d2;')

                with ui.input('Data *', value=data_hoje_formatada, placeholder='dd/mm/aaaa').classes('w-full').props('outlined') as data_input:
                    with ui.menu().props('no-parent-event') as menu:
                        with ui.date(value=data_hoje_iso) as date_picker:
                            date_picker.on('update:model-value', lambda e, inp=data_input: inp.set_value(
                                formatar_data_exibicao(e.args) if e.args else ''
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

            with ui.row().classes('w-full justify-end gap-2'):
                def pular_datas():
                    dialog_data.close()

                ui.button('Pular por enquanto', on_click=pular_datas).props('flat')

                def salvar_todas_datas():
                    for campo, data_input in data_inputs.items():
                        if not data_input.value or not data_input.value.strip():
                            self.notificar(f'⚠️ Informe a data para {datas_pendentes[campo]}', tipo='warning')
                            return

                    try:
                        for campo, data_input in data_inputs.items():
                            data = converter_data_para_iso(data_input.value)
                            self.db.atualizar_data_critica(obra_id, campo, data)
                            self.db.recalcular_checklist(obra_id, campo, data)

                            if campo == 'data_assinatura' and hasattr(self, '_data_assinatura_input'):
                                try:
                                    self._data_assinatura_input.set_value(formatar_data_exibicao(data))
                                except Exception:
                                    pass
                            elif campo == 'data_aio' and hasattr(self, '_data_aio_input'):
                                try:
                                    self._data_aio_input.set_value(formatar_data_exibicao(data))
                                except Exception:
                                    pass

                        dialog_data.close()

                        if atualizar_checklist_fn:
                            ui.timer(0.05, atualizar_checklist_fn, once=True)

                        self.notificar('✅ Datas críticas salvas! Prazos recalculados.', tipo='positive')

                    except Exception as e:
                        log_error(e, "agenda_obras", "Salvar datas críticas consolidado")
                        self.notificar(f'❌ Erro ao salvar: {str(e)}', tipo='negative')

                ui.button('💾 Salvar Datas', on_click=salvar_todas_datas).props('color=primary')

            dialog_data.open()

    def abrir_dialog_data_critica(self, obra_id: int, campo: str, atualizar_checklist_fn=None, dialog_edicao=None):
        """Abre dialog para preencher datas críticas (data_assinatura ou data_aio).
        [DEPRECADO] - Use abrir_dialog_datas_criticas_consolidado para múltiplas datas."""
        labels = {
            'data_assinatura': ('📝 Data de Assinatura do Contrato', 'Informe a data em que o contrato foi assinado:'),
            'data_aio': ('📅 Data da AIO (Autorização de Início de Obra)', 'Informe a data da Autorização de Início de Obra:')
        }

        titulo, descricao = labels.get(campo, ('Preencher Data', 'Informe a data solicitada:'))

        with ui.dialog() as dialog_data, ui.card().classes('responsive-dialog-sm').style('padding: 20px;'):
            ui.label(titulo).style('font-size: 18px; font-weight: bold; margin-bottom: 10px;')
            ui.label(descricao).style('color: #666; margin-bottom: 15px;')

            data_hoje_formatada = datetime.date.today().strftime('%d/%m/%Y')
            data_hoje_iso = datetime.date.today().strftime('%Y-%m-%d')

            with ui.input('Data *', value=data_hoje_formatada, placeholder='dd/mm/aaaa').classes('w-full').props('outlined') as data_input:
                with ui.menu().props('no-parent-event') as menu:
                    with ui.date(value=data_hoje_iso) as date_picker:
                        date_picker.on('update:model-value', lambda e: data_input.set_value(formatar_data_exibicao(e.args) if e.args else ''))
                        with ui.row().classes('justify-end'):
                            ui.button('Fechar', on_click=menu.close).props('flat')
                with data_input.add_slot('append'):
                    ui.icon('edit_calendar').on('click', menu.open).classes('cursor-pointer')

            ui.label('Esta data crítica será usada para calcular prazos de tarefas dependentes.').style(
                'font-size: 11px; color: #999; margin-top: 10px;'
            )

            ui.separator()

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
            self.notificar('Informe uma data válida!', tipo='warning')
            return

        try:
            data_iso = converter_data_para_iso(data)

            if campo not in ('data_assinatura', 'data_aio'):
                raise ValueError(f"Campo desconhecido: {campo}")

            self.db.atualizar_data_critica(obra_id, campo, data_iso)
            self.db.recalcular_checklist(obra_id, campo, data_iso)

            data_formatada = formatar_data_exibicao(data_iso)
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

            dialog.close()

            if atualizar_checklist_fn:
                ui.timer(0.05, atualizar_checklist_fn, once=True)

            campo_label = 'Data de Assinatura' if campo == 'data_assinatura' else 'Data da AIO'
            self.notificar(f'✅ {campo_label} salva! Prazos recalculados.', tipo='positive')

        except Exception as e:
            log_error(e, "agenda_obras", f"Salvar data crítica - campo: {campo}")
            self.notificar(f'❌ Erro ao salvar: {str(e)}', tipo='negative')

    def abrir_dialog_selecionar_medicoes(self, obra_id: int, atualizar_checklist_fn=None, botao_medicoes=None):
        """Abre diálogo para o usuário selecionar quantas medições deseja (0-6)."""
        obra = self.db.obter_obra(obra_id)
        if not obra:
            self.notificar('Obra não encontrada.', tipo='warning')
            return

        data_inicio_obra = (obra.get('data_inicio') or '').strip()
        if not data_inicio_obra:
            self.notificar('Preencha a Data de início da obra antes de configurar as medições.', tipo='warning')
            return

        registro = self.db.obter_medicoes_obra(obra_id)
        valor_atual = registro.get('quantidade') if registro else 0

        with ui.dialog() as dialog_med, ui.card().classes('responsive-dialog-sm').style('padding: 20px;'):
            ui.label('🔧 Configurar Medições').style('font-size: 18px; font-weight: bold; margin-bottom: 8px;')
            ui.label('Selecione a quantidade de medições para este card (máx 12).').style('color: #666; margin-bottom: 10px;')

            options = [str(i) for i in range(0, 13)]
            select_input = ui.select(options, label='Medições', value=str(valor_atual or 0)).classes('w-full').props('outlined')

            ui.separator()

            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('Cancelar', on_click=dialog_med.close).props('flat')

                def confirmar():
                    try:
                        qtd = int(select_input.value or 0)
                        if qtd < 1 or qtd > 12:
                            self.notificar('Escolha um valor entre 1 e 12.', tipo='warning')
                            return

                        self.db.criar_medicoes_dinamicas(obra_id, qtd)

                        if botao_medicoes:
                            try:
                                botao_medicoes.text = rotulo_alterar_medicoes(qtd, True)
                            except Exception:
                                pass

                        if obra_tem_medicoes_concluidas(self.db, obra_id):
                            dialog_med.close()
                            if atualizar_checklist_fn:
                                ui.timer(0.05, atualizar_checklist_fn, once=True)
                            ui.timer(0.1, lambda: self.abrir_dialog_conclusao_obra(obra_id, atualizar_checklist_fn, self._observacoes_input_atual), once=True)
                            return

                        if atualizar_checklist_fn:
                            ui.timer(0.05, atualizar_checklist_fn, once=True)
                        else:
                            ui.timer(0.05, self.renderizar_obras, once=True)

                        dialog_med.close()
                        self.notificar('✅ Medições configuradas com sucesso.', tipo='positive')
                    except Exception as e:
                        log_error(e, 'agenda_obras', 'Configurar medições')
                        self.notificar(f'❌ Erro ao configurar medições: {e}', tipo='negative')

                ui.button('Confirmar', on_click=confirmar).props('color=primary')

        dialog_med.open()

    def abrir_dialog_conclusao_obra(self, obra_id: int, atualizar_checklist_fn=None, observacoes_input_ref=None):
        """Abre diálogo para confirmar a conclusão da obra após finalizar as medições."""
        obra = self.db.obter_obra(obra_id)
        if not obra:
            self.notificar('Obra não encontrada.', tipo='warning')
            return

        status_atual = (obra.get('status_conclusao_obra') or '').strip().lower()
        if status_atual in {'sem_pendencias', 'com_pendencias'}:
            return

        observacoes = (obra.get('observacoes') or '').strip()

        with ui.dialog() as dialog_finalizacao, ui.card().classes('responsive-dialog-sm').style('padding: 20px;'):
            ui.label('Finalizar Obra').style('font-size: 18px; font-weight: bold; margin-bottom: 8px;')
            ui.label('Todas as medições foram concluídas. Confirme como deseja encerrar este card.').style('color: #666; margin-bottom: 10px;')

            if observacoes:
                ui.label('Observações registradas:').style('font-size: 12px; color: #888; margin-top: 8px;')
                ui.label(observacoes).style('white-space: pre-wrap; font-size: 13px; background: #f8f9fa; padding: 10px; border-radius: 6px;')

            pendencias_input = ui.textarea('Pendências da obra (opcional)', value='', placeholder='Descreva aqui as pendências para manter o alerta crítico diário').classes('w-full mt-2').props('outlined autogrow')
            pendencias_input.visible = False

            ui.separator()

            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('Cancelar', on_click=dialog_finalizacao.close).props('flat')

                def mostrar_pendencias():
                    pendencias_input.visible = True
                    try:
                        pendencias_input.update()
                    except Exception:
                        pass

                def concluir_sem_pendencias():
                    try:
                        self.db.registrar_finalizacao_obra(obra_id, 'sem_pendencias')
                        dialog_finalizacao.close()
                        if atualizar_checklist_fn:
                            ui.timer(0.05, atualizar_checklist_fn, once=True)
                        else:
                            ui.timer(0.05, self.renderizar_obras, once=True)
                        self.notificar('✅ Obra finalizada sem pendências.', tipo='positive')
                    except Exception as e:
                        log_error(e, 'agenda_obras', 'Finalizar obra sem pendências')
                        self.notificar(f'❌ Erro ao finalizar obra: {e}', tipo='negative')

                def concluir_com_pendencias():
                    try:
                        texto_pendencias = (pendencias_input.value or '').strip()
                        observacoes_atualizadas = observacoes

                        if texto_pendencias:
                            bloco_pendencias = f'Pendências da conclusão:\n{texto_pendencias}'
                            if bloco_pendencias not in observacoes_atualizadas:
                                observacoes_atualizadas = (
                                    f'{observacoes_atualizadas}\n\n{bloco_pendencias}'
                                    if observacoes_atualizadas
                                    else bloco_pendencias
                                )

                        if observacoes_atualizadas != observacoes:
                            usuario = obter_usuario_logado() or {}
                            nome_usuario = ' '.join([
                                (usuario.get('nome') or '').strip(),
                                (usuario.get('sobrenome') or '').strip(),
                            ]).strip() or (usuario.get('email') or '').strip() or 'Sistema'

                            obs_data = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            sucesso_obs = self.db.atualizar_observacoes_obra(
                                obra_id,
                                observacoes_atualizadas,
                                nome_usuario,
                                obs_data,
                            )

                            if sucesso_obs:
                                try:
                                    obra['observacoes'] = observacoes_atualizadas
                                    obra['obs_usuario'] = nome_usuario
                                    obra['obs_data'] = obs_data
                                    if observacoes_input_ref:
                                        try:
                                            observacoes_input_ref.value = observacoes_atualizadas
                                            observacoes_input_ref.update()
                                        except Exception:
                                            pass
                                except Exception:
                                    pass

                        self.db.registrar_finalizacao_obra(obra_id, 'com_pendencias')
                        dialog_finalizacao.close()
                        if atualizar_checklist_fn:
                            ui.timer(0.05, atualizar_checklist_fn, once=True)
                        else:
                            ui.timer(0.05, self.renderizar_obras, once=True)
                        self.notificar('Obra finalizada com pendências. Alertas críticos diários ativos.', tipo='warning')
                    except Exception as e:
                        log_error(e, 'agenda_obras', 'Finalizar obra com pendências')
                        self.notificar(f'❌ Erro ao finalizar obra: {e}', tipo='negative')

                ui.button('OBRA CONCLUÍDA SEM PENDÊNCIAS', on_click=concluir_sem_pendencias).props('color=positive')
                ui.button('OBRA CONCLUÍDA COM PENDÊNCIAS', on_click=mostrar_pendencias).props('color=negative')
                ui.button('Confirmar pendências', on_click=concluir_com_pendencias).props('color=negative flat')

        dialog_finalizacao.open()

    def abrir_dialog_valor_medicao(self, obra_id: int, item_id: int, checkbox_obj, atualizar_checklist_fn):
        """Abre o diálogo para inserir o valor faturado no mês e só então conclui a tarefa."""
        obra_data = self.db.obter_obra(obra_id)
        pct_parceiro = float((obra_data or {}).get('valor_percentual') or 0)

        with ui.dialog() as dialog, ui.card().classes('responsive-dialog-sm').style('padding: 20px; min-width: 300px;'):
            ui.label('💰 Valor da Medição').style('font-size: 18px; font-weight: bold; margin-bottom: 8px;')
            ui.label('Informe o valor faturado referente a esta medição.').style('color: #666; margin-bottom: 10px;')

            valor_input = ui.number('Valor Medido (R$)', format='%.2f', min=0).classes('w-full').props('outlined autofocus')

            if pct_parceiro > 0:
                ui.label(f'% Parceiro cadastrado: {pct_parceiro:.2f}%').style(
                    'font-size: 12px; color: #666; margin-top: 4px;'
                )
                label_split = ui.label('').style('font-size: 12px; color: #7b1fa2; font-weight: bold;')

                def _atualizar_split():
                    val = float(valor_input.value or 0)
                    vp = round(val * pct_parceiro / 100, 2)
                    ve = round(val - vp, 2)
                    label_split.set_text(
                        f'Parceiro: {self.helper.formatar_valor(vp)} | Empresa: {self.helper.formatar_valor(ve)}'
                    )

                valor_input.on_value_change(lambda e: _atualizar_split())

            ui.separator().classes('my-4')

            def confirmar():
                try:
                    valor = float(valor_input.value) if valor_input.value is not None else 0.0
                    if valor < 0:
                        self.notificar('O valor medido não pode ser negativo!', tipo='warning')
                        return

                    vp = round(valor * pct_parceiro / 100, 2)
                    ve = round(valor - vp, 2)
                    sucesso = self.db.registrar_valor_medido(
                        item_id, valor,
                        valor_parceiro_medicao=vp,
                        valor_empresa_medicao=ve
                    )
                    if not sucesso:
                        self.notificar('❌ Erro ao salvar o valor da medição no banco.', tipo='negative')
                        return

                    self.db.marcar_item_checklist(item_id, True)

                    dialog.close()

                    self.notificar('✅ Valor medido salvo com sucesso!', tipo='positive')

                    if self.db.verificar_todas_medicoes_concluidas(obra_id):
                        ui.timer(0.1, lambda: self.abrir_dialog_conclusao_obra(obra_id, atualizar_checklist_fn, getattr(self, '_observacoes_input_atual', None)), once=True)
                    else:
                        if atualizar_checklist_fn:
                            ui.timer(0.05, atualizar_checklist_fn, once=True)
                        self.renderizar_obras()

                except Exception as e:
                    log_error(e, 'agenda_obras', f'Confirmar valor de medição - item {item_id}')
                    self.notificar(f'❌ Erro ao processar medição: {e}', tipo='negative')

            def cancelar():
                checkbox_obj.set_value(False)
                dialog.close()

            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('Cancelar', on_click=cancelar).props('flat color=red')
                ui.button('Confirmar', on_click=confirmar).props('color=positive')

        dialog.open()

    def abrir_dialog_dados_acesso(self, obra_id: int, item_id: int, checkbox_obj, atualizar_checklist_fn):
        """Abre o diálogo para registrar datas de vigência do acesso e cria/atualiza tarefa de renovação."""
        dados_atuais = self.db.obter_dados_acesso(item_id)
        val_inicio = formatar_data_exibicao((dados_atuais or {}).get('data_inicio_acesso') or '') or ''
        val_fim = formatar_data_exibicao((dados_atuais or {}).get('data_fim_acesso') or '') or ''
        iso_inicio = (dados_atuais or {}).get('data_inicio_acesso') or ''
        iso_fim = (dados_atuais or {}).get('data_fim_acesso') or ''

        with ui.dialog() as dialog, ui.card().classes('responsive-dialog-sm').style('padding: 20px; min-width: 340px;'):
            ui.label('Dados de Acesso').style('font-size: 18px; font-weight: bold; margin-bottom: 8px;')
            ui.label('Informe o período de vigência do acesso obtido.').style('color: #666; margin-bottom: 14px;')

            with ui.input('Data de início *', value=val_inicio, placeholder='dd/mm/aaaa').classes('w-full').props('outlined') as inicio_input:
                with ui.menu().props('no-parent-event') as menu_inicio:
                    with ui.date(value=iso_inicio or None) as dp_inicio:
                        dp_inicio.on('update:model-value', lambda e: inicio_input.set_value(formatar_data_exibicao(e.args) if e.args else ''))
                        with ui.row().classes('justify-end'):
                            ui.button('Fechar', on_click=menu_inicio.close).props('flat')
                with inicio_input.add_slot('append'):
                    ui.icon('edit_calendar').on('click', menu_inicio.open).classes('cursor-pointer')

            with ui.input('Data fim *', value=val_fim, placeholder='dd/mm/aaaa').classes('w-full').props('outlined').style('margin-top: 12px;') as fim_input:
                with ui.menu().props('no-parent-event') as menu_fim:
                    with ui.date(value=iso_fim or None) as dp_fim:
                        dp_fim.on('update:model-value', lambda e: fim_input.set_value(formatar_data_exibicao(e.args) if e.args else ''))
                        with ui.row().classes('justify-end'):
                            ui.button('Fechar', on_click=menu_fim.close).props('flat')
                with fim_input.add_slot('append'):
                    ui.icon('edit_calendar').on('click', menu_fim.open).classes('cursor-pointer')

            ui.separator().classes('my-4')

            def confirmar():
                data_inicio = converter_data_para_iso(inicio_input.value)
                data_fim = converter_data_para_iso(fim_input.value)
                if not data_inicio:
                    self.notificar('Data de início é obrigatória!', tipo='warning')
                    return
                if not data_fim:
                    self.notificar('Data fim é obrigatória!', tipo='warning')
                    return

                hoje_iso = datetime.date.today().isoformat()
                if data_fim < hoje_iso:
                    self.notificar('Data fim está no passado. A tarefa de renovação será criada com prazo imediato.', tipo='warning')

                sucesso = self.db.salvar_dados_acesso(item_id, obra_id, data_inicio, data_fim)
                if not sucesso:
                    self.notificar('Erro ao salvar os dados de acesso.', tipo='negative')
                    return

                ja_concluida = (self.db.obter_item_checklist(item_id) or {}).get('concluido', 0)
                if not ja_concluida:
                    self.db.marcar_item_checklist(item_id, True)

                dialog.close()
                self.notificar('Dados de acesso salvos e tarefa de renovação agendada!', tipo='positive')
                if atualizar_checklist_fn:
                    ui.timer(0.05, atualizar_checklist_fn, once=True)

            def cancelar():
                if checkbox_obj is not None:
                    checkbox_obj.set_value(False)
                dialog.close()

            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('Cancelar', on_click=cancelar).props('flat color=red')
                ui.button('Confirmar', on_click=confirmar).props('color=positive')

        dialog.open()

    def abrir_dialog_nova_renovacao_acesso(self, obra_id: int, item_id: int, checkbox_obj, atualizar_checklist_fn):
        """Abre o diálogo para questionar o usuário se deseja criar uma nova tarefa de renovação de acesso após o prazo da tarefa anterior expirar."""
        with ui.dialog() as dialog, ui.card().classes('responsive-dialog-sm').style('padding: 20px; min-width: 300px;'):
            ui.label('Renovação de Acesso').style('font-size: 18px; font-weight: bold; margin-bottom: 8px;')
            ui.label('Deseja atualizar as datas de acesso ou concluir a tarefa?').style('color: #666; margin-bottom: 14px;')

            def atualizar_datas():
                # Usa o item de origem (SOLICITAÇÃO DE ACESSO) para pré-preencher e salvar as datas
                item_origem_id = self.db.obter_tarefa_origem_id(item_id) or item_id
                self.abrir_dialog_dados_acesso(obra_id, item_origem_id, checkbox_obj, atualizar_checklist_fn)
                dialog.close()

            def concluir_tarefa():
                if checkbox_obj is not None:
                    try:
                        self.db.marcar_item_checklist(item_id, True)
                    except Exception:
                        pass
                dialog.close()
                if atualizar_checklist_fn:
                    ui.timer(0.05, atualizar_checklist_fn, once=True)

            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('Concluir tarefa', on_click=concluir_tarefa).props('flat color=green')
                ui.button('Atualizar Datas', on_click=atualizar_datas).props('color=primary')

        dialog.open()

    def atualizar_obra_dialog(self, dialog, obra_id: int, nome: str, cliente: str,
                              valor: float, data_inicio: str, status: str, checklist_estados=None,
                              checklist_container=None, **kwargs):
        """Atualiza obra e checklist a partir do dialog de detalhes"""
        if not nome or not cliente:
            self.notificar('Nome e Contrato são obrigatórios!', tipo='warning')
            return

        if not valor or valor <= 0:
            self.notificar('Valor deve ser maior que zero!', tipo='warning')
            return

        total_obra = kwargs.get('total_obra')
        if not total_obra or total_obra <= 0:
            self.notificar('Total da Obra é obrigatório e deve ser maior que zero!', tipo='warning')
            return

        if not self._usuario_pode_acessar_contrato(cliente):
            self.notificar('⛔ Você não possui permissão para alterar para este contrato.', tipo='negative')
            return

        try:
            data_inicio = converter_data_para_iso(data_inicio)
            if 'data_assinatura' in kwargs:
                kwargs['data_assinatura'] = converter_data_para_iso(kwargs['data_assinatura'])
            if 'data_aio' in kwargs:
                kwargs['data_aio'] = converter_data_para_iso(kwargs['data_aio'])
            if 'data_conclusao' in kwargs:
                kwargs['data_conclusao'] = converter_data_para_iso(kwargs['data_conclusao'])
            if 'data_acionamento' in kwargs:
                kwargs['data_acionamento'] = converter_data_para_iso(kwargs['data_acionamento'])

            observacoes_nova = (kwargs.pop('observacoes', '') or '').strip()

            obra_antiga = self.db.obter_obra(obra_id)

            status = status_edicao_para_banco(status)
            requer_recalculo = self.db.atualizar_obra(obra_id, nome, cliente, valor, data_inicio, status, **kwargs)

            observacoes_antiga = ((obra_antiga or {}).get('observacoes') or '').strip()
            if observacoes_nova != observacoes_antiga:
                usuario = obter_usuario_logado() or {}
                nome_usuario = ' '.join([
                    (usuario.get('nome') or '').strip(),
                    (usuario.get('sobrenome') or '').strip(),
                ]).strip() or (usuario.get('email') or '').strip() or 'Sistema'

                obs_data = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S') if observacoes_nova else None
                obs_usuario = nome_usuario if observacoes_nova else None

                sucesso_obs = self.db.atualizar_observacoes_obra(
                    obra_id,
                    observacoes_nova,
                    obs_usuario,
                    obs_data,
                )

                if not sucesso_obs:
                    self.notificar('Obra salva, mas houve erro ao atualizar observações.', tipo='warning')

            recalculou = False
            datas_recalculadas = []

            data_inicio_antiga = (obra_antiga or {}).get('data_inicio')
            if not datas_iguais_normalizadas(data_inicio_antiga, data_inicio):
                self.db.recalcular_checklist(obra_id, 'data_inicio', data_inicio)
                datas_recalculadas.append('data de início')
                recalculou = True

            data_acionamento_nova = kwargs.get('data_acionamento')
            if data_acionamento_nova and obra_antiga.get('data_acionamento') != data_acionamento_nova:
                self.db.recalcular_checklist(obra_id, 'data_acionamento', data_acionamento_nova)
                datas_recalculadas.append('data de acionamento')
                recalculou = True

            data_assinatura_nova = kwargs.get('data_assinatura')
            if data_assinatura_nova and obra_antiga.get('data_assinatura') != data_assinatura_nova:
                self.db.recalcular_checklist(obra_id, 'data_assinatura', data_assinatura_nova)
                datas_recalculadas.append('data de assinatura')
                recalculou = True

            data_aio_nova = kwargs.get('data_aio')
            if data_aio_nova and obra_antiga.get('data_aio') != data_aio_nova:
                self.db.recalcular_checklist(obra_id, 'data_aio', data_aio_nova)
                datas_recalculadas.append('data da AIO')
                recalculou = True

            if datas_recalculadas:
                bases = ' e '.join(datas_recalculadas) if len(datas_recalculadas) <= 2 else ', '.join(datas_recalculadas[:-1]) + ' e ' + datas_recalculadas[-1]
                self.notificar(f'🔄 Prazos recalculados com base na {bases}', tipo='info')

            if recalculou and checklist_container:
                checklist_estados.clear()

                def atualizar_checklist_local():
                    checklist_container.clear()
                    checklist = self.db.obter_checklist(obra_id)
                    with checklist_container:
                        for item in checklist:
                            self.criar_item_checklist_editavel(item, checklist_estados, obra_id, atualizar_checklist_local, checklist_completo=checklist)

                    try:
                        obra_atual = self.db.obter_obra(obra_id) or obra_antiga or {}
                        novo_status = status_visual_para_edicao(obra_atual, checklist)
                        if hasattr(self, '_status_input_atual') and self._status_input_atual:
                            self._status_input_atual.value = novo_status
                            self._status_input_atual.update()
                    except Exception:
                        pass

                    try:
                        obra_atual = self.db.obter_obra(obra_id) or {}
                        novo_obs = (obra_atual.get('observacoes') or '').strip()
                        if 'observacoes_input' in locals():
                            try:
                                observacoes_input.value = novo_obs
                                observacoes_input.update()
                            except Exception:
                                pass
                    except Exception:
                        pass

                atualizar_checklist_local()
                try:
                    if not (data_inicio and str(data_inicio).strip()):
                        return

                    med = self.db.obter_medicoes_obra(obra_id)
                    if not med or (med and (med.get('quantidade') is None or int(med.get('quantidade')) == 0)):
                        ui.timer(0.05, lambda: self.abrir_dialog_selecionar_medicoes(obra_id, atualizar_checklist_local), once=True)
                except Exception:
                    pass

            self.notificar('✅ Obra atualizada!', tipo='positive', timeout=3)

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
