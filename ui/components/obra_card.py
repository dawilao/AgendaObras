"""
Mixin com o componente de card de obra (aba Informações, Checklist, Financeiro).
"""

from nicegui import ui
import datetime
from core.error_logger import log_error
from utils.formatters import formatar_data_exibicao

TAREFA_SOLICITACAO_ACESSO = 'SOLICITAÇÃO DE ACESSO'
TAREFA_RENOVACAO_ACESSO = 'RENOVAÇÃO DE SOLICITAÇÃO DE ACESSO'


class ObraCardMixin:
    def criar_card_obra(self, obra):
        """Cria um card individual de obra"""
        checklist = self.db.obter_checklist(obra['id'])
        progresso = self.helper.calcular_progresso(checklist)
        cor, icone, status_texto = self.helper.obter_status_visual(obra, checklist)

        proxima_tarefa = next((item for item in checklist if not item['concluido'] and not item['bloqueado']), None)

        with ui.card().classes('hover:shadow-lg transition-shadow').style(
            f'border-left: 5px solid {cor}; min-height: 250px;'
        ):
            with ui.row().classes('w-full items-center justify-between cursor-pointer').on('click', lambda o=obra: self.abrir_detalhes_obra(o['id'])):
                ui.label(obra['nome_contrato']).style('font-size: 18px; font-weight: bold;')
                ui.icon(icone).style(f'color: {cor}; font-size: 24px;')

            ui.separator()

            with ui.tabs().classes('w-full') as tabs:
                tab_info = ui.tab('Informações', icon='info')
                tab_checklist = ui.tab('Checklist', icon='checklist')
                tab_financeiro = ui.tab('Financeiro', icon='attach_money')

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
                                data_formatada = formatar_data_exibicao(obra['data_inicio'])
                                if data_formatada:
                                    ui.label(f'Início: {data_formatada}').style('color: #666; font-size: 13px;')
                                else:
                                    ui.label(f'Data de início não definida').style('color: #999; font-style: italic; font-size: 13px;')
                            else:
                                ui.label(f'Data de início não definida').style('color: #999; font-style: italic; font-size: 13px;')

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

                        item_acesso = next(
                            (i for i in checklist if (i.get('descricao') or '').strip() == TAREFA_SOLICITACAO_ACESSO),
                            None
                        )

                        if item_acesso and item_acesso.get('concluido'):
                            ui.separator()
                            if item_acesso.get('data_inicio_acesso') and item_acesso.get('data_fim_acesso'):
                                data_inicio = formatar_data_exibicao(item_acesso['data_inicio_acesso'])
                                data_fim = formatar_data_exibicao(item_acesso['data_fim_acesso'])
                                dias_ate_fim = (datetime.date.fromisoformat(item_acesso['data_fim_acesso']) - datetime.date.today()).days
                                renovacao_concluida = any(
                                    (i.get('descricao') or '').strip() == TAREFA_RENOVACAO_ACESSO and i.get('concluido')
                                    for i in checklist
                                )
                                if renovacao_concluida:
                                    cor_acesso = '#666'
                                    estilo_label = 'color: #666; font-size: 13px;'
                                else:
                                    cor_acesso = '#c62828' if dias_ate_fim <= 0 else '#e65100' if dias_ate_fim <= 15 else '#2e7d32'
                                    estilo_label = f'font-size: 13px; color: {cor_acesso}; font-weight: bold;'
                                with ui.row().classes('items-center gap-2'):
                                    ui.icon('key').style(f'color: {cor_acesso}; font-size: 16px;')
                                    ui.label(f'Acesso: {data_inicio} → {data_fim}').style(estilo_label)

                        ui.separator()
                        ui.label(f'Progresso: {progresso}%').style('font-size: 12px; font-weight: bold; color: #666;')
                        ui.linear_progress(progresso / 100, show_value=False).style('height: 8px;')

                        if proxima_tarefa:
                            ui.separator()
                            ui.label('🎯 Próxima Tarefa:').style('font-size: 12px; font-weight: bold; color: #1976d2; margin-top: 5px;')
                            with ui.row().classes('items-center gap-2'):
                                ui.icon('arrow_forward').style('color: #1976d2; font-size: 14px;')
                                ui.label(proxima_tarefa['descricao']).style('font-size: 12px; color: #333; font-weight: 500;')

                            if proxima_tarefa['data_limite']:
                                dias_restantes = self.calcular_dias_restantes_exibicao(proxima_tarefa)
                                sufixo_dias = ' dias úteis' if self.usa_dias_uteis_exibicao(proxima_tarefa) else ' dias'
                                data_formatada_prazo = formatar_data_exibicao(proxima_tarefa['data_limite'])
                                cor_prazo = 'red' if dias_restantes < 0 else 'orange' if dias_restantes <= 3 else 'green'

                                if dias_restantes == 0:
                                    ui.label(f'⏰ Prazo: {data_formatada_prazo} (HOJE!)').style(
                                        f'font-size: 11px; color: {cor_prazo}; margin-left: 20px;'
                                    )
                                else:
                                    ui.label(f'⏰ Prazo: {data_formatada_prazo} ({abs(dias_restantes)}{sufixo_dias} {"atrasado" if dias_restantes < 0 else "restante" if dias_restantes > 0 else "hoje"})').style(
                                        f'font-size: 11px; color: {cor_prazo}; margin-left: 20px;'
                                    )

                        observacoes_texto = (obra.get('observacoes') or '').strip()
                        obs_usuario = (obra.get('obs_usuario') or '').strip()
                        obs_data = (obra.get('obs_data') or '').strip()

                        obs_data_fmt = ''
                        if obs_data:
                            try:
                                dt = datetime.datetime.strptime(obs_data, '%Y-%m-%d %H:%M:%S')
                                obs_data_fmt = dt.strftime('%d/%m/%Y %H:%M')
                            except Exception:
                                obs_data_fmt = obs_data

                        with ui.card().classes('w-full').style('background-color: #f8f9fa; border-left: 4px solid #ccc; padding: 8px; margin-top: 8px;'):
                            ui.label('📝 Observações').style('font-size: 12px; font-weight: bold; color: #666;')
                            ui.label(observacoes_texto if observacoes_texto else 'Sem observações cadastradas.').style(
                                'font-size: 11px; color: #333; white-space: pre-line; '
                                'display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;'
                            )
                            if obs_usuario and obs_data_fmt:
                                ui.label(f'Atualizado por {obs_usuario} em {obs_data_fmt}').style('font-size: 10px; color: #777;')

                # Aba de Checklist
                with ui.tab_panel(tab_checklist).style('max-height: 370px; overflow-y: auto;'):
                    with ui.column().classes('w-full gap-1'):
                        tarefas_concluidas = sum(1 for item in checklist if item['concluido'])
                        ui.label(f'Total: {tarefas_concluidas}/{len(checklist)} tarefas concluídas').style(
                            'font-size: 11px; color: #666; font-weight: bold; margin-bottom: 5px;'
                        )

                        for item in checklist:
                            # Cálculo único por item — reutilizado no tooltip e no label inline
                            dias_restantes = (
                                self.calcular_dias_restantes_exibicao(item)
                                if item.get('data_limite') and not item.get('bloqueado') and not item.get('concluido')
                                else None
                            )

                            if item['concluido']:
                                data_conclusao = item.get('data_conclusao')
                                data_conclusao_fmt = formatar_data_exibicao(data_conclusao) if data_conclusao else ''
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
                            elif dias_restantes is not None:
                                sufixo_dias = ' dias úteis' if self.usa_dias_uteis_exibicao(item) else ' dias'
                                data_formatada = formatar_data_exibicao(item['data_limite'])
                                if dias_restantes < 0:
                                    tooltip_text = f"⚠️ Atrasada: {abs(dias_restantes)}{sufixo_dias} - Prazo: {data_formatada}"
                                    info_reiteracao = self.formatar_info_reiteracao(item)
                                    if info_reiteracao:
                                        tooltip_text += f"\n{info_reiteracao}"
                                elif dias_restantes == 0:
                                    tooltip_text = f"Prazo: {data_formatada} (HOJE!)"
                                else:
                                    tooltip_text = f"Prazo: {data_formatada} ({dias_restantes}{sufixo_dias} restantes)"
                            else:
                                tooltip_text = "Tarefa pendente"

                            with ui.row().classes('items-center gap-2').style(
                                'padding: 4px 8px; border-radius: 4px; cursor: default;'
                            ).tooltip(tooltip_text):
                                if item['concluido']:
                                    ui.icon('check_circle').style('color: green; font-size: 14px;')
                                    with ui.column().classes('gap-0'):
                                        ui.label(item['descricao']).style('font-size: 11px; color: #999; text-decoration: line-through;')
                                        if item.get('data_conclusao'):
                                            data_concl_fmt = formatar_data_exibicao(item['data_conclusao'])
                                            if data_concl_fmt:
                                                ui.label(f'✓ Concluída em {data_concl_fmt}').style('font-size: 9px; color: #999; font-style: italic;')
                                elif item['bloqueado']:
                                    ui.icon('lock').style('color: #ccc; font-size: 14px;')
                                    ui.label(item['descricao']).style('font-size: 11px; color: #ccc;')
                                else:
                                    ui.icon('radio_button_unchecked').style('color: #ff9800; font-size: 14px;')
                                    with ui.column().classes('gap-0'):
                                        ui.label(item['descricao']).style('font-size: 11px; color: #666;')
                                        if dias_restantes is not None and dias_restantes < 0:
                                            info_reiteracao = self.formatar_info_reiteracao(item)
                                            if info_reiteracao:
                                                ui.label(info_reiteracao).style('font-size: 9px; color: #ff5722; font-style: italic;')

                with ui.tab_panel(tab_financeiro).style('max-height: 370px; overflow-y: auto;'):
                    with ui.column().classes('w-full gap-2'):
                        # Valores estáticos: já disponíveis no dict da obra, sem query
                        valor_contrato = obra.get('valor_contrato') or 0
                        valor_aditivo = obra.get('valor_aditivo') or 0
                        total_obra = obra.get('total_obra') or 0
                        valor_percentual = obra.get('valor_percentual') or 0

                        ui.label(f'Valor do Contrato: {self.helper.formatar_valor(valor_contrato)}').style(
                            'font-size: 13px; color: #666;'
                        )
                        if valor_aditivo != 0:
                            _cor_aditivo = '#d32f2f' if valor_aditivo < 0 else '#1565c0'
                            _sinal = '−' if valor_aditivo < 0 else '+'
                            ui.label(
                                f'Valor do Aditivo: {_sinal} {self.helper.formatar_valor(abs(valor_aditivo))}'
                            ).style(f'font-size: 13px; color: {_cor_aditivo};')
                        ui.label(f'Total da Obra: {self.helper.formatar_valor(total_obra)}').style(
                            'font-size: 13px; color: #2e7d32; font-weight: bold;'
                        )

                        ui.separator().classes('my-2')

                        # Placeholder para conteúdo carregado sob demanda (lazy)
                        financeiro_carregado = {'ok': False}
                        container_lazy = ui.column().classes('w-full gap-2')
                        spinner_lazy = ui.spinner('dots', size='sm').style('color: #999;')

                        def _carregar_financeiro(obra_id=obra['id']):
                            if financeiro_carregado['ok']:
                                return
                            financeiro_carregado['ok'] = True
                            spinner_lazy.set_visibility(False)

                            soma_medidos = self.db.obter_soma_valores_medidos(obra_id)
                            historico = self.db.obter_valores_medicoes(obra_id)
                            soma_parceiro_medido = round(
                                sum((m.get('valor_parceiro_medicao') or 0) for m in historico), 2
                            )
                            soma_empresa_medido = round(
                                sum((m.get('valor_empresa_medicao') or 0) for m in historico), 2
                            )

                            percentual_faturado = (soma_medidos / total_obra * 100) if total_obra > 0 else 0.0
                            total_a_medir = total_obra - soma_medidos

                            with container_lazy:
                                ui.label(f'Total Medido: {self.helper.formatar_valor(soma_medidos)}').style(
                                    'font-size: 13px; color: #1976d2; font-weight: bold;'
                                )

                                cor_pct = '#d32f2f' if percentual_faturado > 100 else '#1976d2'
                                ui.label(f'% Medida da Obra: {percentual_faturado:.2f}%').style(
                                    f'font-size: 13px; color: {cor_pct}; font-weight: bold;'
                                )
                                ui.linear_progress(
                                    min(percentual_faturado / 100, 1.0), show_value=False
                                ).style('height: 8px;').props(f'color={"negative" if percentual_faturado > 100 else "primary"}')

                                cor_saldo = '#d32f2f' if total_a_medir < 0 else '#2e7d32'
                                label_saldo = f'Total a Medir (Saldo): {self.helper.formatar_valor(total_a_medir)}'
                                if total_a_medir < 0:
                                    label_saldo += '  ⚠️ Acima do orçamento!'
                                ui.label(label_saldo).style(
                                    f'font-size: 13px; color: {cor_saldo}; font-weight: bold;'
                                )

                                if valor_percentual > 0:
                                    total_parceiro = round(valor_contrato * valor_percentual / 100, 2)
                                    total_empresa = round(total_obra - total_parceiro, 2)
                                    ui.separator().classes('my-1')
                                    ui.label(
                                        f'Valor Total do Parceiro ({valor_percentual:.2f}%): {self.helper.formatar_valor(total_parceiro)}'
                                    ).style('font-size: 13px; color: #7b1fa2;')
                                    ui.label(
                                        f'Valor Destinado à Empresa: {self.helper.formatar_valor(total_empresa)}'
                                    ).style('font-size: 13px; color: #e65100; font-weight: bold;')
                                    if soma_parceiro_medido or soma_empresa_medido:
                                        ui.label(
                                            f'↳ Parceiro medido até agora: {self.helper.formatar_valor(soma_parceiro_medido)}'
                                        ).style('font-size: 12px; color: #7b1fa2;')
                                        ui.label(
                                            f'↳ Empresa medida até agora: {self.helper.formatar_valor(soma_empresa_medido)}'
                                        ).style('font-size: 12px; color: #e65100;')

                                if historico:
                                    ui.separator().classes('my-2')
                                    ui.label('Histórico de Medições').style(
                                        'font-size: 12px; font-weight: bold; color: #555;'
                                    )
                                    with ui.column().classes('w-full gap-1'):
                                        for med in historico:
                                            mes_ref = med.get('mes_referencia') or ''
                                            try:
                                                ano, mes = mes_ref.split('-')
                                                mes_label = f"{int(mes):02d}/{ano}"
                                            except Exception:
                                                mes_label = mes_ref or '—'
                                            data_conf = med.get('data_conclusao') or med.get('data_medicao') or ''
                                            try:
                                                data_fmt = datetime.datetime.strptime(data_conf, '%Y-%m-%d').strftime('%d/%m/%Y')
                                            except Exception:
                                                data_fmt = data_conf
                                            vp_med = med.get('valor_parceiro_medicao') or 0
                                            ve_med = med.get('valor_empresa_medicao') or 0
                                            with ui.row().classes('w-full items-center justify-between').style(
                                                'background: #f5f5f5; border-radius: 4px; padding: 4px 8px;'
                                            ):
                                                ui.label(f'Medição {mes_label}').style('font-size: 12px; color: #444;')
                                                with ui.row().classes('items-center gap-3'):
                                                    with ui.column().classes('items-end gap-0'):
                                                        ui.label(f'Total: {self.helper.formatar_valor(med["valor_medido"])}').style(
                                                            'font-size: 11px; color: #1976d2; font-weight: bold;'
                                                        )
                                                        if vp_med or ve_med:
                                                            ui.label(f'P: {self.helper.formatar_valor(vp_med)}').style(
                                                                'font-size: 10px; color: #7b1fa2;'
                                                            )
                                                            ui.label(f'E: {self.helper.formatar_valor(ve_med)}').style(
                                                                'font-size: 10px; color: #e65100;'
                                                            )
                                                    ui.label(data_fmt).style('font-size: 11px; color: #999;')

                        tab_financeiro.on('click', _carregar_financeiro)
