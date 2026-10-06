"""
Mixin do financeiro Omie na tela de Obras: resumo no card, janela do financeiro,
ligação obra ↔ projeto, chaves e atualização. Permissões conferidas no servidor
(services.financeiro_service); quem não pode alterar não vê os botões de alteração.
"""

from datetime import datetime

from nicegui import ui, run

from core.error_logger import log_error
from db.omie_repo import OmieRepository, CONFERIDO
from services import omie_atualizacao as atualizacao
from services.financeiro_service import (usuario_atual, pode_ver_financeiro, pode_editar_financeiro,
                                         pode_validar_parceiros)
from services.omie_financeiro import (GRUPOS, moeda, custos_mat_mo, totais_custos, avisos_vinculo,
                                      resumo_obra, financeiro_obra, diferencas, textos_diferencas,
                                      pagamentos_por_fornecedor, parceiros_obra)
from services.omie_integracao import chaves_configuradas, modo_simulado, sugerir_projetos
from utils.formatters import formatar_data_hora_local as _data_local

ACOES_HISTORICO = {
    'vinculo_criado': 'Ligou ao projeto do Omie', 'vinculo_trocado': 'Trocou o projeto do Omie',
    'vinculo_reconfirmado': 'Reconfirmou a ligação', 'vinculo_desfeito': 'Desfez a ligação',
    'vinculo_em_lote': 'Ligou obras em lote', 'lote_conferido': 'Marcou a consulta como conferida',
    'atualizacao_iniciada': 'Iniciou a atualização do Omie', 'atualizacao_concluida': 'Concluiu a atualização do Omie',
    'atualizacao_interrompida': 'Interrompeu a atualização do Omie',
    'atualizacao_bloqueada': 'Atualização bloqueada pelo Omie (30 min)',
    'chaves_configuradas': 'Informou as chaves do Omie', 'chaves_removidas': 'Removeu as chaves do Omie',
    'financeiro_exportado': 'Exportou o financeiro (CSV)',
    'parceiro_validado': 'Validou fornecedor da 2.01.97', 'parceiro_alterado': 'Alterou a validação de fornecedor',
    'parceiro_desfeito': 'Desfez a validação de fornecedor',
    'conferencia_reaberta': 'Consulta voltou para conferência (houve mudanças)',
    'arquivo_enviado': 'Enviou arquivo', 'arquivo_anexado': 'Anexou arquivo das Comunicações',
    'arquivo_corrigido': 'Corrigiu arquivo', 'arquivo_excluido': 'Excluiu arquivo',
}
TIPOS_ARQUIVO = {'cct': 'CCT', 'orcamento': 'Orçamento', 'aditivo': 'Aditivo'}
PAPEIS = {'parceiro': 'Parceiro da obra', 'outro': 'Outro prestador'}
CORES_COMPARACAO = {'vermelho': ('#ffebee', '#c62828'), 'ambar': ('#fff8e1', '#8d6e00'),
                    'ok': ('#e8f5e9', '#2e7d32')}

GRUPOS_EXTRATO = {
    'pagamentos': 'Pagamentos (conta paga)', 'recebimentos': 'Recebimentos (conta recebida)',
    'tarifas': 'Tarifas', 'debitos_diretos': 'Outros débitos diretos', 'creditos_diretos': 'Créditos diretos',
    'adiantamentos': 'Adiantamentos', 'transferencias': 'Transferências',
    'previsoes_abertos': 'Previsões / em aberto', 'cancelados': 'Cancelados', 'a_classificar': 'A classificar',
}
PASSOS_CONFERENCIA = (
    '1. Abra o Omie → FINANÇAS (ícone verde) → Aprovação de pagamentos.',
    '2. Na última coluna, dê dois cliques em Omie Cash.',
    '3. Limpe todos os filtros → escolha o período → Atualizar.',
    '4. Analise pelo projeto da obra (IC ou número de serviço).',
)
ESTILO_DIALOGO = 'width: min(1400px, 96vw); max-width: 96vw; max-height: 94vh; overflow: auto;'


def apagar_ao_fechar(dialog):
    """Remove o diálogo da página quando ele fecha (senão cada abertura fica acumulada no navegador)."""
    dialog.on('hide', lambda: None if dialog.is_deleted else dialog.delete())
    return dialog


def _selo_simulado(dados):
    if (dados or {}).get('simulado'):
        ui.label('DADOS SIMULADOS · não são do Omie').style(
            'font-size: 11px; font-weight: 700; color: #6a1b9a; background: #f3e5f5; '
            'padding: 2px 8px; border-radius: 4px;')


def _data_br(iso_dia):
    try:
        return datetime.strptime(iso_dia, '%Y-%m-%d').strftime('%d/%m/%Y')
    except (TypeError, ValueError):
        return iso_dia or ''


def _cor_saldo(valor):
    """Positivo verde, negativo vermelho; zero ou desconhecido sem sinal."""
    if valor is None or valor == 0:
        return '#1a2332'
    return '#2e7d32' if valor > 0 else '#c62828'


class OmieFinanceiroMixin:

    @property
    def omie_repo(self):
        if getattr(self, '_omie_repo', None) is None:
            self._omie_repo = OmieRepository(self.db.db_name)
        return self._omie_repo

    def _usuario_omie(self):
        """Usuário do banco (com a permissão Financeiro); None se a sessão não for válida."""
        try:
            return usuario_atual()
        except PermissionError:
            return None

    # ------------------------------------------------------------------ card
    def renderizar_bloco_omie(self, obra):
        """Resumo do Omie na aba Financeiro do card (só para quem pode ver)."""
        user = getattr(self, '_usuario_fin', None) or self._usuario_omie()
        if not pode_ver_financeiro(user, obra):
            return False
        blocos = self.__dict__.setdefault('_blocos_omie', {})

        @ui.refreshable
        def bloco():
            try:
                resumo = resumo_obra(obra, self.omie_repo.situacao(obra['id'], com_anterior=False))
            except Exception as e:
                log_error(e, 'omie_financeiro', f"Resumo Omie - obra {obra['id']}")
                ui.label('Financeiro Omie indisponível no momento.').style('font-size: 12px; color: #999;')
                return
            with ui.column().classes('w-full gap-1').style(
                'background: #f4f8fd; border-left: 3px solid #1976d2; border-radius: 4px; padding: 6px 8px;'
            ):
                if resumo is None:
                    ui.label('Financeiro Omie ainda não ligado a esta obra.').style(
                        'font-size: 12px; color: #999; font-style: italic;')
                    if pode_editar_financeiro(user):
                        ui.button('Ligar ao Omie', icon='link',
                                  on_click=lambda: self.abrir_financeiro_omie(obra)).props(
                            'flat dense no-caps size=sm color=primary')
                    return
                vinculo, lote = resumo['vinculo'], resumo['lote']
                with ui.row().classes('w-full items-center no-wrap gap-1'):
                    ui.icon('account_balance').style('color: #1976d2; font-size: 15px;')
                    ui.label(f"Omie · {vinculo['nome_projeto']}").style(
                        'font-size: 12px; font-weight: 700; color: #1a2332; overflow: hidden; '
                        'text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0;')
                    conferido = vinculo['estado'] == CONFERIDO
                    ui.badge('Conferido' if conferido else 'Em conferência',
                             color='green' if conferido else 'orange').props('outline')
                if lote:
                    _selo_simulado(lote['dados'])
                    totais = resumo['totais']
                    ui.label(f"Custos pagos: {moeda(totais['pago'])}").style(
                        'font-size: 13px; color: #1a2332; font-weight: bold;')
                    ui.label(f"Custos a pagar: {moeda(totais['aberto'])}").style('font-size: 12px; color: #666;')
                    ind = resumo['indicadores']
                    if resumo['notas_encontradas']:
                        ui.label(f"Recebido líquido: {moeda(ind['recebido'])}").style('font-size: 12px; color: #1a2332;')
                        ui.label(f"Saldo de caixa: {moeda(ind['saldo_caixa'])}").style(
                            f"font-size: 12px; font-weight: bold; color: {_cor_saldo(ind['saldo_caixa'])};")
                    else:
                        ui.label('Recebimentos não encontrados no Omie').style(
                            'font-size: 11px; color: #e65100;')
                    self._resumo_parceiros_card(obra, lote['dados'])
                    ui.label(f"Consulta de {_data_local(lote['consultado_em'])}").style('font-size: 10px; color: #999;')
                else:
                    ui.label('Ainda não atualizado do Omie.').style('font-size: 12px; color: #999; font-style: italic;')
                if resumo['erro']:
                    ui.label(f"Última atualização falhou em {_data_local(resumo['erro']['consultado_em'])}").style(
                        'font-size: 11px; color: #c62828;').tooltip(resumo['erro']['motivo'] or '')
                if resumo['avisos']:
                    ui.label(f"⚠ {len(resumo['avisos'])} aviso(s) na ligação").style(
                        'font-size: 11px; color: #e65100;').tooltip('\n'.join(resumo['avisos']))
                ui.button('Abrir financeiro', icon='open_in_full',
                          on_click=lambda: self.abrir_financeiro_omie(obra)).props(
                    'flat dense no-caps size=sm color=primary')

        blocos[obra['id']] = bloco
        bloco()
        return True

    def _resumo_parceiros_card(self, obra, dados):
        try:
            parceiros = self._dados_parceiros(obra, dados)
        except Exception as e:
            log_error(e, 'omie_financeiro', f"Parceiros no card - obra {obra['id']}")
            return
        comparacao = parceiros['comparacao']
        if comparacao['nivel'] in ('ambar', 'vermelho'):
            ui.label(f"⚠ {comparacao['texto']}").style(
                f"font-size: 11px; color: {CORES_COMPARACAO[comparacao['nivel']][1]}; font-weight: 600;")
        if parceiros['a_validar']:
            ui.label(f"{len(parceiros['a_validar'])} parceiro(s) a validar").style('font-size: 11px; color: #e65100;')

    def _atualizar_blocos_omie(self, obra_ids=None):
        for obra_id, bloco in list(getattr(self, '_blocos_omie', {}).items()):
            if obra_ids is not None and obra_id not in obra_ids:
                continue
            try:
                bloco.refresh()
            except Exception:
                # Card já removido da tela (troca de página/filtro).
                self._blocos_omie.pop(obra_id, None)

    # ------------------------------------------------------------- janela
    def abrir_financeiro_omie(self, obra):
        user = self._usuario_omie()
        if not pode_ver_financeiro(user, obra):
            ui.notify('Financeiro restrito ao administrador, ao Financeiro e ao coordenador desta obra.', type='warning')
            return
        editar = pode_editar_financeiro(user)
        obra = self.db.obter_obra(obra['id']) or obra

        with apagar_ao_fechar(ui.dialog()) as dialog, ui.card().style(ESTILO_DIALOGO):
            @ui.refreshable
            def conteudo():
                situacao = self.omie_repo.situacao(obra['id'])
                vinculo, lote, erro = situacao['vinculo'], situacao['lote'], situacao['erro']
                with ui.row().classes('w-full items-center justify-between no-wrap'):
                    with ui.column().classes('gap-0'):
                        ic = (obra.get('contrato_ic') or '').strip() or 'não cadastrado'
                        ui.label(f"{obra['nome_contrato']} · IC {ic}").style(
                            'font-size: 20px; font-weight: 700; color: #1a2332;')
                        if vinculo:
                            with ui.row().classes('items-center gap-2'):
                                ui.label(f"Projeto Omie: {vinculo['nome_projeto']}").style('font-size: 13px; color: #555;')
                                conferido = vinculo['estado'] == CONFERIDO
                                ui.badge('Conferido' if conferido else 'Em conferência',
                                         color='green' if conferido else 'orange').props('outline')
                            if vinculo['estado'] == CONFERIDO and vinculo.get('conferido_por_nome'):
                                ui.label(f"Conferido por {vinculo['conferido_por_nome']} em "
                                         f"{_data_local(vinculo['conferido_em'])}").style('font-size: 11px; color: #888;')
                    ui.button(icon='close', on_click=dialog.close).props('flat round').tooltip('Fechar financeiro')

                def recarregar():
                    if not dialog.is_deleted:   # a janela pode ter sido fechada durante a atualização
                        conteudo.refresh()
                    self._atualizar_blocos_omie([obra['id']])

                if not vinculo:
                    with ui.card().classes('w-full').style('background: #fafafa; padding: 16px;'):
                        ui.label('Financeiro Omie ainda não ligado a esta obra.').style('font-size: 14px; color: #666;')
                        ui.label('A ligação usa o projeto do Omie que tem o IC da obra no nome; nunca a cidade.').style(
                            'font-size: 12px; color: #999;')
                        if editar:
                            ui.button('Ligar a um projeto do Omie', icon='link',
                                      on_click=lambda: self._dialogo_escolher_projeto(obra, recarregar)).props(
                                'unelevated no-caps')
                    return

                avisos = avisos_vinculo(obra, vinculo, lote and lote['dados'])
                if avisos:
                    with ui.column().classes('w-full gap-1').style(
                            'background: #fff8e1; border-left: 4px solid #f9a825; padding: 8px 12px; border-radius: 4px;'):
                        for aviso in avisos:
                            ui.label(f'⚠ {aviso}').style('font-size: 13px; color: #8d6e00;')
                if erro:
                    texto = (f"Última atualização falhou em {_data_local(erro['consultado_em'])}: {erro['motivo']}"
                             + (f" · exibindo dados de {_data_local(lote['consultado_em'])}" if lote else ''))
                    ui.label(texto).style('font-size: 13px; color: #c62828; background: #ffebee; '
                                          'padding: 8px 12px; border-radius: 4px; width: 100%;')

                if editar:
                    self._acoes_financeiro_omie(obra, vinculo, lote, avisos, recarregar)

                if not lote:
                    ui.label('Ainda não há consulta do Omie para esta obra. Use "Atualizar esta obra".').style(
                        'font-size: 14px; color: #999; padding: 12px 0;')
                    self._painel_historico(obra)
                    return

                _selo_simulado(lote['dados'])
                with ui.row().classes('w-full items-center justify-between'):
                    ui.label(f"Consulta de {_data_local(lote['consultado_em'])} · período "
                             f"{_data_br(lote['inicio'])} a {_data_br(lote['fim'])}").style('font-size: 12px; color: #888;')
                    ui.button('Exportar', icon='download', on_click=lambda: self._exportar_financeiro_omie(obra)).props(
                        'flat dense no-caps').tooltip('Baixar o financeiro desta consulta em CSV (abre no Excel)')
                self._faixa_diferencas(obra, situacao['anterior'], lote)

                financeiro = financeiro_obra(obra, lote['dados'])
                with ui.tabs().props('no-caps align=center').classes('w-full text-blue-800') as abas:
                    aba_custo = ui.tab('Custo', icon='payments')
                    aba_recebimento = ui.tab('Recebimento', icon='receipt_long')
                    aba_saldo = ui.tab('Saldo bruto', icon='account_balance')
                with ui.tab_panels(abas, value=aba_custo).classes('w-full'):
                    with ui.tab_panel(aba_custo):
                        self._painel_custo(financeiro['custos'])
                        self._painel_parceiros(obra, lote['dados'], pode_validar_parceiros(user, obra), recarregar)
                    with ui.tab_panel(aba_recebimento):
                        self._painel_recebimento(financeiro, vinculo['estado'] == CONFERIDO)
                    with ui.tab_panel(aba_saldo):
                        self._painel_saldo(financeiro['indicadores'])
                self._painel_conferencia(lote['dados'])
                self._painel_historico(obra)

            conteudo()
        dialog.open()

    @staticmethod
    def _faixa_diferencas(obra, anterior, lote):
        dif = diferencas(anterior, lote, obra)
        if not dif:
            return
        textos = textos_diferencas(dif)
        desde = _data_local(dif['desde'])
        if not textos:
            ui.label(f'Sem mudanças desde a consulta de {desde}.').style('font-size: 12px; color: #888;')
            return
        with ui.column().classes('w-full gap-0').style(
                'background: #e3f2fd; border-left: 4px solid #1976d2; padding: 6px 12px; border-radius: 4px;'):
            ui.label(f'Desde a consulta de {desde}').style('font-size: 12px; font-weight: 700; color: #0d47a1;')
            for texto in textos:
                ui.label(f'• {texto}').style('font-size: 13px; color: #1a2332;')

    def _exportar_financeiro_omie(self, obra):
        try:
            nome, conteudo = atualizacao.exportar_financeiro(self.omie_repo, obra, self._usuario_omie())
        except (PermissionError, ValueError) as e:
            ui.notify(str(e), type='warning')
            return
        ui.download.content(conteudo, nome, 'text/csv')

    def _painel_historico(self, obra):
        with ui.expansion('Histórico', icon='history').classes('w-full'):
            try:
                acoes = atualizacao.historico(self.omie_repo, obra, self._usuario_omie())
            except PermissionError as e:
                ui.label(str(e)).style('font-size: 12px; color: #999;')
                return
            self._linhas_historico(acoes)

    @staticmethod
    def _linhas_historico(acoes, nomes_obras=None):
        """Ações do financeiro; com nomes_obras (histórico geral), mostra também a obra."""
        if not acoes:
            ui.label('Nenhuma ação registrada.').style('font-size: 12px; color: #999;')
            return
        for acao in acoes:
            detalhe = acao.get('detalhe') or {}
            extra = detalhe.get('projeto') or ''
            if acao['acao'].startswith('atualizacao_') and 'ok' in detalhe:
                extra = f"{detalhe['ok']} ok · {detalhe.get('erro', 0)} com erro"
            if detalhe.get('mudancas'):
                extra = '; '.join(detalhe['mudancas'])
            if 'fornecedor' in detalhe:
                extra = ' · '.join(t for t in (detalhe.get('nome') or f"código {detalhe['fornecedor']}",
                                               PAPEIS.get(detalhe.get('papel'), '')) if t)
            if acao['acao'].startswith('arquivo_'):
                if 'depois' in detalhe:
                    antes, depois = detalhe.get('antes') or {}, detalhe['depois']
                    extra = (f"{antes.get('nome')} ({TIPOS_ARQUIVO.get(antes.get('tipo'), '')}) → "
                             f"{depois.get('nome')} ({TIPOS_ARQUIVO.get(depois.get('tipo'), '')})")
                else:
                    extra = f"{detalhe.get('nome', '')} ({TIPOS_ARQUIVO.get(detalhe.get('tipo'), '')})"
            if nomes_obras is not None and acao.get('obra_id') is not None:
                obra = nomes_obras.get(acao['obra_id']) or f"obra {acao['obra_id']} (excluída)"
                extra = f'{obra} · {extra}' if extra else obra
            with ui.row().classes('w-full no-wrap gap-2').style('border-bottom: 1px solid #f0f0f0; padding: 2px 0;'):
                ui.label(_data_local(acao['quando'])).style('font-size: 12px; color: #888; min-width: 110px;')
                ui.label(acao.get('usuario_nome') or '—').style('font-size: 12px; color: #555; min-width: 120px;')
                ui.label(ACOES_HISTORICO.get(acao['acao'], acao['acao']) + (f' · {extra}' if extra else '')).style(
                    'font-size: 12px; color: #1a2332;')

    def _acoes_financeiro_omie(self, obra, vinculo, lote, avisos, recarregar):
        async def atualizar_esta():
            await self.atualizar_omie(obra_ids=[obra['id']], ao_terminar=recarregar)

        def conferir():
            try:
                if atualizacao.marcar_conferido(self.omie_repo, obra['id'], self._usuario_omie()):
                    ui.notify('Consulta marcada como conferida.', type='positive')
                recarregar()
            except (PermissionError, ValueError) as e:
                ui.notify(str(e), type='warning')

        with ui.row().classes('w-full items-center gap-2'):
            ui.button('Atualizar esta obra', icon='sync', on_click=atualizar_esta).props('outline no-caps')
            if vinculo['estado'] != CONFERIDO and lote:
                ui.button('Marcar como conferido', icon='task_alt', on_click=conferir).props('outline no-caps color=green')
            if any('renomeado' in a or 'mudou' in a for a in avisos):
                ui.button('Reconfirmar ligação', icon='published_with_changes',
                          on_click=lambda: self._reconfirmar_ligacao(obra, vinculo, lote, recarregar)).props(
                    'outline no-caps color=orange')
            ui.button('Trocar ligação', icon='swap_horiz',
                      on_click=lambda: self._dialogo_escolher_projeto(obra, recarregar)).props('flat no-caps')
            ui.button('Desfazer ligação', icon='link_off',
                      on_click=lambda: self._confirmar_desfazer_ligacao(obra, recarregar)).props('flat no-caps color=negative')

    def _painel_custo(self, custos):
        grupos = custos_mat_mo(custos)
        totais = totais_custos(custos)
        ui.label('Gastos pagos · MAT e MO').style('font-size: 18px; font-weight: 700;')
        with ui.row().classes('w-full gap-3'):
            for chave, titulo in GRUPOS:
                self._cartao_valor(titulo, grupos[chave]['pago'])
        ui.label('MAT: Fornecedor de Material. MO provisória: Prestador de Serviço/Parceiro + Fornecedor de '
                 'Serviços; serviços podem incluir materiais. Outros: seguros, taxas, reembolsos e demais categorias. '
                 'Valores líquidos pagos no período consultado.').style('font-size: 12px; color: #777;')
        with ui.row().classes('w-full gap-3'):
            self._cartao_valor('Custos pagos líquidos', totais['pago'])
            self._cartao_valor('Custos a pagar', totais['aberto'])
        rotulos = dict(GRUPOS)
        with ui.expansion('Composição por categoria e valores a pagar', icon='list').classes('w-full'):
            ui.table(columns=[{'name': k, 'label': v, 'field': k, 'align': 'left'} for k, v in (
                ('grupo', 'Grupo'), ('categoria', 'Categoria Omie'), ('pago', 'Pago líquido'), ('aberto', 'A pagar'))],
                rows=[{'grupo': rotulos[c['grupo']],
                       'categoria': c['codigo'] + (f" · {c['descricao']}" if c['descricao'] else ''),
                       'pago': moeda(c['pago_centavos']), 'aberto': moeda(c['aberto_centavos'])} for c in custos],
                row_key='categoria').classes('w-full')

    @staticmethod
    def _cartao_valor(titulo, valor, cor='#1a2332', abaixo=None):
        with ui.card().classes('shadow-none').style('flex: 1; min-width: 180px; background: #f8fafc;'):
            ui.label(titulo).style('font-size: 12px; color: #666;')
            ui.label(moeda(valor)).style(f'font-size: 20px; font-weight: 700; color: {cor};')
            if abaixo:
                ui.label(abaixo).style('font-size: 11px; color: #888;')

    def _dados_parceiros(self, obra, dados):
        pagos = pagamentos_por_fornecedor(dados)
        validacoes = self.omie_repo.parceiros_da_obra(obra['id'])
        fornecedores = self.omie_repo.fornecedores({p['codigo'] for p in pagos if p['codigo']} | set(validacoes))
        # Medições só são lidas quando há comparação possível.
        comparar = float(obra.get('valor_percentual') or 0) > 0 and any(
            v['papel'] == 'parceiro' for v in validacoes.values())
        medicoes = self.db.obter_valores_medicoes(obra['id']) if comparar else []
        return parceiros_obra(obra, dados, validacoes, fornecedores, medicoes, pagos=pagos)

    def _painel_parceiros(self, obra, dados, pode_validar, recarregar):
        try:
            parceiros = self._dados_parceiros(obra, dados)
        except Exception as e:
            log_error(e, 'omie_financeiro', f"Parceiros Omie - obra {obra['id']}")
            ui.label('Parceiros indisponíveis no momento.').style('font-size: 12px; color: #999;')
            return
        ui.separator().classes('my-2')
        ui.label('Parceiros · categoria 2.01.97').style('font-size: 18px; font-weight: 700;')
        ui.label('O total da categoria 2.01.97 reúne vários prestadores e não é comparado com o % Parceiro. '
                 'Marque qual fornecedor é o parceiro contratado; só os parceiros validados entram na comparação '
                 'com as medições. O pago na categoria continua em "MO / serviços".').style(
            'font-size: 12px; color: #777;')

        comparacao = parceiros['comparacao']
        fundo, cor = CORES_COMPARACAO.get(comparacao['nivel'], ('#f5f5f5', '#666'))
        ui.label(comparacao['texto']).style(f'font-size: 13px; color: {cor}; background: {fundo}; '
                                            'padding: 6px 12px; border-radius: 4px; width: 100%;')
        if 'pago' in comparacao:
            with ui.row().classes('w-full gap-3'):
                self._cartao_valor('Pago aos parceiros validados', comparacao['pago'])
                self._cartao_valor('Parceiro medido até agora', comparacao['medido'])
                self._cartao_valor('Total previsto do parceiro', comparacao['previsto'])

        def executar(funcao, item, *args):
            try:
                funcao(self.omie_repo, obra, item['codigo'], *args, self._usuario_omie())
            except (PermissionError, ValueError) as e:
                ui.notify(str(e), type='warning')
                return
            recarregar()

        def linha(item):
            validacao = item['validacao']
            with ui.row().classes('w-full items-center no-wrap gap-2').style(
                    'border-bottom: 1px solid #eee; padding: 4px 0;'):
                with ui.column().classes('gap-0').style('flex: 1; min-width: 0;'):
                    ui.label(item['nome']).style('font-size: 13px; font-weight: 600; color: #1a2332;')
                    codigo = f"Código Omie {item['codigo']}" if item['codigo'] else 'Sem código no Omie'
                    ui.label(f"{codigo} · {item['documento']}").style('font-size: 11px; color: #888;')
                    if validacao:
                        ui.label(f"{PAPEIS[validacao['papel']]} · validado por {validacao['validado_por_nome'] or '—'} "
                                 f"em {_data_local(validacao['validado_em'])}").style('font-size: 11px; color: #888;')
                with ui.column().classes('gap-0 items-end'):
                    ui.label(moeda(item['pago_centavos'])).style('font-size: 13px; font-weight: 700;')
                    ui.label(f"{item['pagamentos']} pagamento(s)").style('font-size: 11px; color: #888;')
                if not pode_validar or not item['codigo']:
                    return
                if validacao is None:
                    ui.button('É parceiro da obra', icon='handshake',
                              on_click=lambda i=item: executar(atualizacao.validar_parceiro, i, 'parceiro')).props(
                        'outline dense no-caps size=sm color=primary')
                    ui.button('Outro prestador',
                              on_click=lambda i=item: executar(atualizacao.validar_parceiro, i, 'outro')).props(
                        'flat dense no-caps size=sm')
                else:
                    outro_papel = 'outro' if validacao['papel'] == 'parceiro' else 'parceiro'
                    ui.button('Alterar', icon='swap_horiz',
                              on_click=lambda i=item, p=outro_papel: executar(atualizacao.validar_parceiro, i, p)).props(
                        'flat dense no-caps size=sm').tooltip(f'Mudar para "{PAPEIS[outro_papel]}"')
                    ui.button('Desfazer', icon='undo',
                              on_click=lambda i=item: executar(atualizacao.desfazer_parceiro, i)).props(
                        'flat dense no-caps size=sm color=negative').tooltip('Voltar para "a validar"')

        ui.label('Parceiros da obra').style('font-size: 14px; font-weight: 700; margin-top: 8px;')
        if not parceiros['parceiros']:
            ui.label('Nenhum parceiro validado.').style('font-size: 12px; color: #999;')
        for item in parceiros['parceiros']:
            linha(item)
        if parceiros['a_validar']:
            ui.label(f"Outros parceiros identificados (a validar) · {len(parceiros['a_validar'])}").style(
                'font-size: 14px; font-weight: 700; color: #e65100; margin-top: 8px;')
            for item in parceiros['a_validar']:
                linha(item)
        if parceiros['outros']:
            with ui.expansion(f"Outros prestadores · {len(parceiros['outros'])}", icon='engineering').classes('w-full'):
                for item in parceiros['outros']:
                    linha(item)

    def _painel_recebimento(self, financeiro, conferido):
        ind, notas = financeiro['indicadores'], financeiro['notas']
        if notas is None:
            ui.label('Recebimentos não encontrados no Omie para este projeto — conferir no Omie. '
                     'Não significa valor zero.').style(
                'font-size: 14px; color: #e65100; background: #fff3e0; padding: 10px 12px; border-radius: 4px;')
            return
        if not conferido:
            ui.label('Valores de NF a conferir no Omie (campos ainda não validados com uma consulta real).').style(
                'font-size: 12px; color: #8d6e00; background: #fff8e1; padding: 6px 12px; border-radius: 4px;')
        with ui.row().classes('w-full gap-3'):
            self._cartao_valor('Recebido da CAIXA (líquido)', ind['recebido'],
                               abaixo=f"(BRUTO: {moeda(ind['recebido_bruto'])})")
            self._cartao_valor('Faturado nos títulos consultados', ind['faturado'])
            self._cartao_valor('Faturado em aberto — líquido', ind['faturado_aberto'])
        ui.label('Medições faturadas · títulos vinculados às NFs').style('font-size: 16px; font-weight: 700;')
        ui.table(columns=[{'name': k, 'label': v, 'field': k, 'align': 'left'} for k, v in (
            ('nf', 'NF'), ('vencimento', 'Vencimento'), ('bruto', 'Valor bruto'), ('retencoes', 'Retenções'),
            ('recebido', 'Recebido líquido'), ('aberto', 'Aberto líquido'), ('situacao', 'Situação'))],
            rows=[{'id': i, 'nf': n['nf'] + (f" · {n['parcela']}" if n['parcela'] else ''),
                   'vencimento': n['vencimento'], 'bruto': moeda(n['bruto_centavos']),
                   'retencoes': moeda(n['retencoes_centavos']), 'recebido': moeda(n['recebido_centavos']),
                   'aberto': moeda(n['aberto_centavos']), 'situacao': n['situacao']} for i, n in enumerate(notas)],
            row_key='id').classes('w-full')
        ui.label('Recebimento parcial sem bruto atribuível fica "A confirmar". Retenções ainda sem campo '
                 'identificado no Omie: "A confirmar" não significa "sem retenção".').style('font-size: 12px; color: #777;')

    def _painel_saldo(self, ind):
        ui.label('Saldo bruto de caixa').style('font-size: 18px; font-weight: 700;')
        ui.label('Recebido da CAIXA (líquido) − custos pagos líquidos').style('font-size: 12px; color: #777;')
        with ui.row().classes('w-full gap-3'):
            self._cartao_valor('Recebido da CAIXA (líquido)', ind['recebido'],
                               abaixo=f"(BRUTO: {moeda(ind['recebido_bruto'])})")
            self._cartao_valor('Custos pagos líquidos', ind['custos_pagos'])
            self._cartao_valor('Saldo bruto de caixa', ind['saldo_caixa'], cor=_cor_saldo(ind['saldo_caixa']))
        ui.label('Retrato do caixa consultado: não é lucro e não inclui contas ainda a pagar ou a receber.').style(
            'font-size: 12px; color: #777;')
        ui.separator()
        with ui.row().classes('w-full gap-3'):
            self._cartao_valor('Total da Obra (cadastro)', ind['valor_obra'])
            self._cartao_valor('Saldo contratual a receber', ind['saldo_contratual'])
        if ind['valor_obra'] is None:
            ui.label('Total da Obra não informado no cadastro: saldo contratual indisponível.').style(
                'font-size: 12px; color: #e65100;')
        ui.label('Saldo contratual = Total da Obra (contrato + aditivo do cadastro) − recebido líquido. Inclui '
                 'retenções e valores ainda não faturados; não equivale a NFs vencidas.').style(
            'font-size: 12px; color: #777;')

    def _painel_conferencia(self, dados):
        conciliacao = dados.get('conciliacao') or {}
        status = conciliacao.get('status', 'Pendente')
        cor = {'Totais conferem': '#2e7d32', 'Divergência': '#c62828'}.get(status, '#e65100')
        with ui.expansion(f'Conferência com o extrato · {status}', icon='fact_check').classes('w-full'):
            ui.label(conciliacao.get('motivo') or conciliacao.get('escopo') or '').style(f'font-size: 12px; color: {cor};')
            if conciliacao.get('linhas'):
                ui.table(columns=[{'name': k, 'label': v, 'field': k, 'align': 'left'} for k, v in (
                    ('tipo', 'Tipo'), ('conta', 'Conta'), ('categoria', 'Categoria'), ('api', 'Baixas (API)'),
                    ('extrato', 'Extrato'), ('diferenca', 'Diferença'))],
                    rows=[{**l, 'api': moeda(l['api']), 'extrato': moeda(l['extrato']),
                           'diferenca': moeda(l['diferenca']), 'id': f"{l['tipo']}-{l['conta']}-{l['categoria']}"}
                          for l in conciliacao['linhas']], row_key='id').classes('w-full')
            if dados.get('resumo_extrato'):
                ui.label('Movimentos do extrato do projeto, separados por origem').style(
                    'font-size: 13px; font-weight: 600; margin-top: 8px;')
                ui.table(columns=[{'name': k, 'label': v, 'field': k, 'align': 'left'} for k, v in (
                    ('grupo', 'Origem'), ('quantidade', 'Registros'), ('valor', 'Valor no extrato'))],
                    rows=[{'grupo': GRUPOS_EXTRATO.get(k, k), 'quantidade': v['quantidade'], 'valor': moeda(v['centavos'])}
                          for k, v in dados['resumo_extrato'].items()], row_key='grupo').classes('w-full')
            for aviso in dados.get('avisos', []):
                if 'renomeado' not in aviso:
                    ui.label(f'ℹ {aviso}').style('font-size: 12px; color: #777;')
        ui.button('Origem da informação', icon='info', on_click=self._dialogo_origem_omie).props('flat no-caps')

    @staticmethod
    def _dialogo_origem_omie():
        with apagar_ao_fechar(ui.dialog()) as dialog, ui.card().style('max-width: 720px;'):
            ui.label('Origem da informação · Omie').style('font-size: 18px; font-weight: 700;')
            ui.label('Como conferir na tela do Omie').style('font-weight: 600; color: #1565c0;')
            for passo in PASSOS_CONFERENCIA:
                ui.label(passo).style('font-size: 13px;')
            ui.label('Consultas usadas (somente leitura)').style('font-weight: 600; color: #1565c0; margin-top: 8px;')
            for texto in ('ConsultarProjeto / ListarProjetos · projeto ligado à obra',
                          'ListarContasCorrentes · todas as contas, todas as páginas',
                          'ListarExtrato · extrato de cada conta no período, filtrado pelo projeto',
                          'ListarMovimentos · títulos (CP/CR) e baixas do período (BXCP/BXCR) do projeto'):
                ui.label(texto).style('font-size: 13px;')
            ui.label('Retrato da consulta: não é atualizado sozinho. Custos de tarifas, créditos diretos, previsões '
                     'e adiantamentos ficam separados do total pago.').style('font-size: 12px; color: #777;')
            ui.button('Fechar', on_click=dialog.close).props('flat')
        dialog.open()

    # ------------------------------------------------------------- ligação
    async def _carregar_projetos(self, recarregar=False):
        user = self._usuario_omie()
        if not self._garantir_chaves():
            return None
        try:
            return await run.io_bound(atualizacao.projetos_omie, user, self.db.listar_obras(), None, recarregar)
        except (PermissionError, ValueError, RuntimeError) as e:
            ui.notify(str(e), type='warning')
        except Exception as e:
            log_error(e, 'omie_financeiro', 'Listar projetos do Omie')
            ui.notify('Não foi possível consultar os projetos do Omie.', type='warning')
        return None

    async def _dialogo_escolher_projeto(self, obra, ao_terminar=None):
        projetos = await self._carregar_projetos()
        if projetos is None:
            return
        ligados = {v['codigo_projeto'] for v in self.omie_repo.vinculos() if v['obra_id'] != obra['id']}
        livres = [p for p in projetos if p['codigo'] not in ligados]
        sugestao = sugerir_projetos([obra], livres)[obra['id']]
        opcoes = {p['codigo']: p['nome'] for p in livres}
        inicial = sugestao['projetos'][0]['codigo'] if sugestao['situacao'] == 'sugerida' else None
        with apagar_ao_fechar(ui.dialog()) as dialog, ui.card().style('min-width: min(560px, 92vw);'):
            ui.label(f"Ligar {obra['nome_contrato']} ao Omie").style('font-size: 18px; font-weight: 700;')
            ic = (obra.get('contrato_ic') or '').strip() or 'não cadastrado'
            ui.label(f'IC da obra: {ic}').style('font-size: 13px; color: #555;')
            if sugestao['situacao'] == 'nenhuma':
                ui.label('Nenhum projeto do Omie tem o número deste IC no nome. Confira o IC no cadastro da obra.').style(
                    'font-size: 12px; color: #e65100;')
            elif sugestao['situacao'] == 'ambigua':
                ui.label(f"{len(sugestao['projetos'])} projetos têm o número deste IC no nome. Escolha o correto.").style(
                    'font-size: 12px; color: #e65100;')
            escolha = ui.select(opcoes, value=inicial, with_input=True, label='Projeto do Omie').props(
                'outlined dense clearable').classes('w-full')

            def confirmar():
                if escolha.value is None:
                    ui.notify('Escolha um projeto.', type='warning')
                    return
                try:
                    atualizacao.ligar(self.omie_repo, obra, {'codigo': escolha.value, 'nome': opcoes[escolha.value]},
                                      self._usuario_omie())
                except (PermissionError, ValueError) as e:
                    ui.notify(str(e), type='warning')
                    return
                ui.notify('Obra ligada ao projeto do Omie. Atualize para buscar os dados.', type='positive')
                dialog.close()
                self._atualizar_blocos_omie([obra['id']])
                if ao_terminar:
                    ao_terminar()

            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('Cancelar', on_click=dialog.close).props('flat no-caps')
                ui.button('Ligar', icon='link', on_click=confirmar).props('unelevated no-caps')
        dialog.open()

    def _reconfirmar_ligacao(self, obra, vinculo, lote, ao_terminar):
        nome = ((lote or {}).get('dados') or {}).get('projeto')
        try:
            atualizacao.ligar(self.omie_repo, obra, {'codigo': vinculo['codigo_projeto'],
                                                     'nome': nome or vinculo['nome_projeto']}, self._usuario_omie())
            ui.notify('Ligação reconfirmada.', type='positive')
        except (PermissionError, ValueError) as e:
            ui.notify(str(e), type='warning')
        ao_terminar()

    def _confirmar_desfazer_ligacao(self, obra, ao_terminar):
        with apagar_ao_fechar(ui.dialog()) as dialog, ui.card():
            ui.label('Desfazer a ligação com o Omie?').style('font-size: 16px; font-weight: 700;')
            ui.label('As consultas guardadas desta obra serão apagadas. O histórico de ações é mantido.').style(
                'font-size: 13px; color: #666;')

            def confirmar():
                try:
                    atualizacao.desfazer_ligacao(self.omie_repo, obra['id'], self._usuario_omie())
                    ui.notify('Ligação desfeita.', type='positive')
                except (PermissionError, ValueError) as e:
                    ui.notify(str(e), type='warning')
                dialog.close()
                ao_terminar()

            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('Cancelar', on_click=dialog.close).props('flat no-caps')
                ui.button('Desfazer', on_click=confirmar).props('unelevated no-caps color=negative')
        dialog.open()

    async def abrir_obras_sem_ligacao(self):
        projetos = await self._carregar_projetos(recarregar=True)
        if projetos is None:
            return
        linhas = atualizacao.obras_sem_ligacao(self.omie_repo, self.db.listar_obras(), projetos)
        with apagar_ao_fechar(ui.dialog()) as dialog, ui.card().style(
                'width: min(900px, 96vw); max-height: 90vh; overflow: auto;'):
            ui.label('Obras sem ligação ao Omie').style('font-size: 18px; font-weight: 700;')
            ui.label('Sugestão pelo número do IC no nome do projeto; nunca pela cidade. Marque as sugestões '
                     'corretas e confirme; as demais podem ser escolhidas uma a uma.').style('font-size: 12px; color: #777;')
            if not linhas:
                ui.label('Todas as obras já estão ligadas.').style('color: #2e7d32; padding: 12px 0;')
            marcadas = {}
            for linha in linhas:
                obra = linha['obra']
                ic = (obra.get('contrato_ic') or '').strip() or 'sem IC'
                with ui.row().classes('w-full items-center no-wrap gap-2').style(
                        'border-bottom: 1px solid #eee; padding: 4px 0;'):
                    if linha['situacao'] == 'sugerida':
                        marcadas[obra['id']] = (ui.checkbox(value=True), obra, linha['projetos'][0])
                    else:
                        ui.element('div').style('width: 40px;')
                    with ui.column().classes('gap-0').style('flex: 1; min-width: 0;'):
                        ui.label(f"{obra['nome_contrato']} · IC {ic}").style('font-size: 13px; font-weight: 600;')
                        if linha['situacao'] == 'sugerida':
                            texto, cor = f"Sugestão: {linha['projetos'][0]['nome']}", '#1565c0'
                        elif linha['situacao'] == 'ambigua':
                            texto, cor = f"{len(linha['projetos'])} projetos com este IC — escolha o correto", '#e65100'
                        else:
                            texto, cor = 'Nenhum projeto com este IC no Omie — conferir o cadastro', '#999'
                        ui.label(texto).style(f'font-size: 12px; color: {cor};')
                    if linha['situacao'] != 'sugerida':
                        ui.button('Escolher projeto', on_click=lambda o=obra: self._dialogo_escolher_projeto(
                            o, dialog.close)).props('flat dense no-caps')

            def confirmar():
                pares = [(obra, projeto) for caixa, obra, projeto in marcadas.values() if caixa.value]
                if not pares:
                    ui.notify('Nenhuma sugestão marcada.', type='warning')
                    return
                try:
                    gravados = atualizacao.ligar_em_lote(self.omie_repo, pares, self._usuario_omie())
                except (PermissionError, ValueError) as e:
                    ui.notify(str(e), type='warning')
                    return
                ui.notify(f'{gravados} obra(s) ligada(s) ao Omie. Atualize para buscar os dados.', type='positive')
                dialog.close()
                self._atualizar_blocos_omie()

            with ui.expansion('Histórico de ações do Financeiro', icon='history').classes('w-full'):
                try:
                    nomes = {o['id']: o.get('nome_contrato') or '' for o in self.db.listar_obras()}
                    self._linhas_historico(atualizacao.historico_geral(self.omie_repo, self._usuario_omie()), nomes)
                except PermissionError as e:
                    ui.label(str(e)).style('font-size: 12px; color: #999;')

            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('Fechar', on_click=dialog.close).props('flat no-caps')
                if marcadas:
                    ui.button('Confirmar selecionadas', icon='done_all', on_click=confirmar).props('unelevated no-caps')
        dialog.open()

    # ------------------------------------------------------- chaves e atualização
    def _garantir_chaves(self, depois=None):
        if modo_simulado() or chaves_configuradas()['configuradas']:
            return True
        self.abrir_chaves_omie(depois)
        return False

    def abrir_chaves_omie(self, depois=None):
        info = chaves_configuradas()
        with ui.dialog() as dialog, ui.card().style('min-width: min(480px, 92vw);'):
            ui.label('Chaves do Omie').style('font-size: 18px; font-weight: 700;')
            if info['origem'] == 'servidor':
                ui.label('As chaves estão configuradas no servidor e só podem ser trocadas lá.').style('font-size: 13px;')
                ui.button('Fechar', on_click=dialog.close).props('flat no-caps')
                dialog.open()
                return
            if info['origem'] == 'tela':
                ui.label(f"Configuradas por {info['por']} em {_data_local(info['em'])}.").style('font-size: 13px; color: #555;')
            ui.label('As chaves ficam só na memória do servidor e somem quando ele reinicia. Nunca são exibidas '
                     'de novo nem registradas. O AgendaObras só faz consultas de leitura.').style(
                'font-size: 12px; color: #777;')
            chave = ui.input('APP KEY', password=True, password_toggle_button=True).props(
                'outlined dense autocomplete=off').classes('w-full')
            segredo = ui.input('APP SECRET', password=True, password_toggle_button=True).props(
                'outlined dense autocomplete=off').classes('w-full')

            def limpar():
                chave.set_value('')
                segredo.set_value('')

            dialog.on('hide', limpar)

            async def salvar():
                valores = (chave.value or '', segredo.value or '')
                limpar()
                try:
                    await run.io_bound(atualizacao.configurar_chaves, self.omie_repo, *valores, self._usuario_omie())
                except (PermissionError, ValueError) as e:
                    ui.notify(str(e), type='warning')
                    return
                ui.notify('Chaves do Omie conferidas e guardadas na memória do servidor.', type='positive')
                dialog.close()
                if depois:
                    await depois()

            def remover():
                try:
                    atualizacao.remover_chaves(self.omie_repo, self._usuario_omie())
                    ui.notify('Chaves removidas da memória do servidor.', type='positive')
                except (PermissionError, ValueError) as e:
                    ui.notify(str(e), type='warning')
                dialog.close()

            with ui.row().classes('w-full justify-end gap-2'):
                if info['origem'] == 'tela':
                    ui.button('Remover', on_click=remover).props('flat no-caps color=negative')
                ui.button('Cancelar', on_click=dialog.close).props('flat no-caps')
                ui.button('Testar e salvar', icon='key', on_click=salvar).props('unelevated no-caps')
        dialog.open()

    def montar_acoes_omie_topbar(self):
        """Botões do Financeiro na barra de Obras (ao lado do toggle Grade/Kanban)."""
        user = self._usuario_omie()
        if not pode_editar_financeiro(user):
            return
        if modo_simulado():
            ui.badge('Omie simulado', color='purple').props('outline').style('margin-right: 6px;').tooltip(
                'OMIE_MODO=simulado: as consultas usam dados fictícios')
        with ui.element('div').classes('ao-view-toggle').style('margin-right: 8px;'):
            self._btn_omie_atualizar = ui.button(icon='sync', on_click=lambda: self.atualizar_omie()).props(
                'flat dense').classes('ao-view-toggle-btn').tooltip('Atualizar do Omie')
            ui.button(icon='link', on_click=self.abrir_obras_sem_ligacao).props('flat dense').classes(
                'ao-view-toggle-btn').tooltip('Obras sem ligação ao Omie')
            ui.button(icon='key', on_click=lambda: self.abrir_chaves_omie()).props('flat dense').classes(
                'ao-view-toggle-btn').tooltip('Chaves do Omie')
        with ui.row().classes('items-center no-wrap gap-1').style('margin-right: 8px;') as self._omie_status:
            ui.spinner(size='sm')
            self._omie_progresso = ui.label('').style('font-size: 12px; color: #555;')
            ui.button(icon='stop', on_click=self._interromper_omie).props('flat dense round color=negative').tooltip(
                'Interromper atualização')
        self._omie_status.set_visibility(False)

    def _interromper_omie(self):
        try:
            if atualizacao.interromper(self._usuario_omie()):
                self._omie_progresso.set_text('Interrompendo…')
        except PermissionError as e:
            ui.notify(str(e), type='warning')

    async def atualizar_omie(self, obra_ids=None, ao_terminar=None):
        user = self._usuario_omie()
        if not pode_editar_financeiro(user):
            ui.notify('Somente o Financeiro pode atualizar do Omie.', type='warning')
            return
        if not self._garantir_chaves(lambda: self.atualizar_omie(obra_ids, ao_terminar)):
            return
        # Progresso e timer ficam na barra de Obras, não no diálogo de onde a atualização partiu
        # (ele pode ser fechado e apagado enquanto a consulta roda).
        status = getattr(self, '_omie_status', None)
        timer = None
        if status is not None:
            status.set_visibility(True)
            with status:
                timer = ui.timer(0.5, lambda: self._omie_progresso.set_text(atualizacao.estado()['progresso']))
        try:
            resumo = await run.io_bound(atualizacao.atualizar, self.omie_repo, self.db.listar_obras(), user, obra_ids)
        except (PermissionError, ValueError, RuntimeError) as e:
            ui.notify(str(e), type='warning', timeout=8000)
            return
        except Exception as e:
            log_error(e, 'omie_financeiro', 'Atualizar do Omie')
            ui.notify('Atualização do Omie não concluída. Os dados anteriores foram mantidos.', type='warning')
            return
        finally:
            if timer is not None:
                timer.cancel()
            if status is not None:
                status.set_visibility(False)
        partes = [f"{resumo['ok']} obra(s) atualizada(s)"]
        mudancas = resumo.get('mudancas') or {}
        if mudancas.get('pagamentos'):
            partes.append(f"{mudancas['pagamentos']} pagamento(s) novo(s)")
        if mudancas.get('notas_recebidas'):
            partes.append(f"{mudancas['notas_recebidas']} NF(s) recebida(s)")
        if resumo.get('reabertas'):
            partes.append(f"{resumo['reabertas']} obra(s) com mudanças voltaram para conferência")
        if resumo['erro']:
            partes.append(f"{resumo['erro']} com erro")
        if resumo['nao_processadas']:
            partes.append(f"{resumo['nao_processadas']} não processada(s), com os dados anteriores mantidos")
        if resumo['bloqueado_ate']:
            partes.append(f"o Omie bloqueou as consultas até {resumo['bloqueado_ate'].astimezone().strftime('%H:%M')}")
        elif resumo['interrompido']:
            partes.append('atualização interrompida')
        ui.notify(' · '.join(partes), type='positive' if not resumo['erro'] and not resumo['bloqueado_ate'] else 'warning',
                  timeout=10000)
        self._atualizar_blocos_omie(obra_ids)
        if ao_terminar:
            ao_terminar()
