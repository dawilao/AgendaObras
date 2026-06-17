"""
Página Base de Cotações — gerencia cotações de itens por contrato.
"""

import asyncio
import datetime
import math
from typing import List, Optional

_ITENS_POR_PAGINA = 50

from nicegui import ui

from db.cotacoes_repo import CotacoesDatabase
from db.contratos_repo import ContratosDatabase
from db.obras_repo import ObrasRepository
from services.auth_service import obter_usuario_logado
from services.cotacoes_service import (
    gerar_modelo_plo,
    gerar_modelo_cotacoes,
    importar_plo_contrato,
    importar_template_cotacoes,
    importar_plo_obra,
    exportar_template_cotacoes,
    exportar_abc,
)
from core.error_logger import log_error


class CotacoesPage:
    def __init__(self):
        self._db = CotacoesDatabase()
        self._contratos_db = ContratosDatabase()
        self._obras_db = ObrasRepository()
        self._usuario = obter_usuario_logado()
        self._is_admin = bool(self._usuario.get('is_admin'))

        self._contrato_id: Optional[int] = None
        self._contrato_nome: str = ''
        self._busca: str = ''
        self._pagina: int = 0
        self._obra_id: Optional[int] = None
        self._obra_nome: str = ''
        self._abc_codigos: set = set()
        self._abc_quantidades: dict = {}

        self._tabela_container = None
        self._acoes_container = None
        self._tabela_outer = None
        self._sidebar_itens: dict = {}

        self._injetar_css()
        self._header()
        self._body()

    # ── CSS ───────────────────────────────────────────────────────────────────

    def _injetar_css(self):
        ui.add_head_html('''<style>
        :root { --nicegui-default-padding: 0; }
        .nicegui-content { padding: 0 !important; overflow: hidden; }

        .responsive-dialog {
            width: min(96vw, 900px) !important;
            max-width: 96vw !important;
        }
        .responsive-dialog-sm {
            width: min(96vw, 560px) !important;
            max-width: 96vw !important;
        }

        /* Layout principal */
        .cotacoes-layout {
            display: flex;
            flex-direction: row;
            width: 100%;
            box-sizing: border-box;
            height: calc(100vh - 56px);
            background: #f0f2f5;
            overflow: hidden;
        }

        /* Sidebar de contratos */
        .cotacoes-sidebar {
            width: 256px;
            min-width: 256px;
            background: #ffffff;
            border-right: 1px solid #e8eaf0;
            padding: 16px 12px;
            display: flex;
            flex-direction: column;
            gap: 2px;
            overflow-y: auto;
            box-shadow: 2px 0 8px rgba(0,0,0,0.04);
            flex-shrink: 0;
        }
        .cot-sidebar-title {
            font-size: 11px;
            font-weight: 700;
            color: #9e9e9e;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            margin-bottom: 8px;
            padding: 0 4px;
        }
        .cot-contrato-item {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 10px;
            border-radius: 8px;
            cursor: pointer;
            transition: background 0.15s;
            font-size: 13px;
            color: #424242;
            user-select: none;
        }
        .cot-contrato-item:hover { background: #f0f4ff; color: #1565c0; }
        .cot-contrato-item.ativo {
            background: #e8f0fe;
            color: #1565c0;
            font-weight: 600;
        }

        /* Área de conteúdo */
        .cotacoes-content {
            flex: 1;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            padding: 0;
            min-width: 0;
        }

        /* Barra de ações */
        .cot-acoes-bar {
            background: #ffffff;
            border-bottom: 1px solid #e8eaf0;
            padding: 10px 20px;
            display: flex;
            flex-direction: column;
            gap: 8px;
            flex-shrink: 0;
        }
        .cot-acoes-linha {
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: nowrap;
            min-width: 0;
        }
        .cot-acoes-divider {
            width: 1px;
            height: 20px;
            background: #e0e4ea;
            flex-shrink: 0;
        }
        /* Tabela */
        .cot-tabela-wrap {
            flex: 1;
            overflow: auto;
            padding: 16px 20px;
        }
        .cot-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            background: #ffffff;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 1px 4px rgba(0,0,0,0.06);
        }
        .cot-table th {
            background: #f5f7fa;
            padding: 8px 10px;
            text-align: left;
            border-bottom: 2px solid #e0e4ea;
            white-space: nowrap;
            font-size: 12px;
            font-weight: 700;
            color: #5c6370;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }
        .cot-table th.th-check { width: 32px; padding: 8px 4px; text-align: center; }
        .cot-table td {
            padding: 2px 4px;
            border-bottom: 1px solid #f0f2f5;
            vertical-align: middle;
        }
        .cot-table tr:hover td { background: #f8f9ff; }
        .cot-table td.cot-td-text {
            padding: 6px 10px;
            color: #374151;
        }
        .cot-table td.cot-td-num {
            padding: 6px 10px;
            color: #374151;
            text-align: right;
            font-variant-numeric: tabular-nums;
        }
        .cot-table td.cot-td-media {
            padding: 6px 10px;
            font-weight: 600;
            color: #1976d2;
            text-align: right;
            font-variant-numeric: tabular-nums;
        }
        .cot-table td.cot-td-curva {
            padding: 6px 10px;
            font-weight: 700;
            color: #7c3aed;
            text-align: center;
        }
        .cot-table td.cot-td-check {
            padding: 2px 4px;
            text-align: center;
        }
        .cot-table tr.linha-marcada td { background: #f0f9f0; }
        .cot-table tr.linha-marcada:hover td { background: #e6f5e6; }

        /* Input inline nas células editáveis */
        .cot-table td .q-field {
            margin: 0 !important;
            padding: 0 !important;
        }
        .cot-table td .q-field__control {
            min-height: 30px !important;
            padding: 0 6px !important;
        }
        .cot-table td .q-field__native {
            font-size: 13px !important;
            padding: 4px 0 !important;
        }
        .cot-table td .q-field__control:before {
            border-color: transparent !important;
        }
        .cot-table td .q-field__control:hover:before {
            border-color: #1976d2 !important;
        }
        .cot-table td .q-field--focused .q-field__control:before {
            border-color: #1976d2 !important;
        }

        /* Checkbox compacto na célula */
        .cot-table td .q-checkbox {
            margin: 0 auto;
        }

        /* Estado vazio */
        .cot-empty-state {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 12px;
            padding: 60px 20px;
            color: #9e9e9e;
            font-size: 14px;
            text-align: center;
        }

        /* Header */
        .cot-header-user {
            display: flex;
            align-items: center;
            gap: 7px;
            padding: 4px 10px 4px 6px;
            border-radius: 20px;
            background: rgba(255,255,255,0.1);
            font-size: 13px;
            color: rgba(255,255,255,0.88);
            font-weight: 500;
            border: 1px solid rgba(255,255,255,0.12);
        }
        .cot-header-avatar {
            width: 28px; height: 28px;
            border-radius: 50%;
            background: rgba(100,181,246,0.2);
            display: flex; align-items: center; justify-content: center;
            font-size: 11px; font-weight: 700; color: #90caf9;
            flex-shrink: 0;
        }

        /* Link de modelo */
        .cot-modelo-link {
            font-size: 12px;
            color: #1976d2;
            text-decoration: underline;
            cursor: pointer;
        }
        </style>''')

    # ── Header ────────────────────────────────────────────────────────────────

    def _header(self):
        usuario = self._usuario
        nome = usuario.get('nome', '')
        sobrenome = usuario.get('sobrenome', '')
        iniciais = ((nome[:1] + sobrenome[:1]) or nome[:2] or 'U').upper()
        nome_exibicao = f'{nome} {sobrenome}'.strip() or 'Usuário'

        with ui.header().classes('items-center').style(
            'background: #0f172a; padding: 0 20px; height: 56px; gap: 12px; '
            'flex-wrap: nowrap; box-shadow: 0 2px 10px rgba(0,0,0,0.25);'
        ):
            ui.button(icon='arrow_back', on_click=lambda: ui.navigate.to('/')).props(
                'flat round text-color=white'
            ).style('opacity: 0.7;').tooltip('Voltar ao Início')

            with ui.element('div').style(
                'display: flex; align-items: center; gap: 10px; '
                'border-left: 1px solid rgba(255,255,255,0.1); padding-left: 14px;'
            ):
                ui.label('📊').style('font-size: 18px; line-height: 1;')
                ui.label('Base de Cotações').style(
                    'font-size: clamp(15px,2vw,18px); color: white; '
                    'font-weight: 700; letter-spacing: -0.01em;'
                )

            ui.space()

            with ui.element('div').classes('cot-header-user'):
                with ui.element('div').classes('cot-header-avatar'):
                    ui.label(iniciais)
                ui.label(nome_exibicao).style(
                    'max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;'
                )

            ui.button(icon='logout', on_click=lambda: ui.navigate.to('/logout')).props(
                'flat round text-color=white'
            ).style('opacity: 0.6;').tooltip('Sair')

    # ── Body ──────────────────────────────────────────────────────────────────

    def _body(self):
        with ui.element('div').classes('cotacoes-layout'):
            with ui.element('div').classes('cotacoes-sidebar'):
                self._sidebar()
            with ui.element('div').classes('cotacoes-content'):
                self._acoes_container = ui.element('div').classes('cot-acoes-bar')
                self._tabela_outer = ui.element('div').classes('cot-tabela-wrap')
                self._renderizar_acoes()
                self._renderizar_tabela()

    # ── Sidebar ───────────────────────────────────────────────────────────────

    def _sidebar(self):
        ui.html('<div class="cot-sidebar-title">Contratos</div>', sanitize=False)

        usuario_id = self._usuario.get('id')
        if self._is_admin:
            contratos = self._contratos_db.listar_contratos_com_id()
        else:
            contratos = self._contratos_db.listar_contratos_usuario_com_id(usuario_id)

        if not contratos:
            ui.label('Nenhum contrato disponível.').style(
                'font-size: 12px; color: #9e9e9e; padding: 8px 4px;'
            )
            return

        for c in contratos:
            cid = c['id']
            nome = c['nome']
            el = ui.element('div').classes('cot-contrato-item')
            with el:
                ui.html(
                    '<span class="material-icons" style="font-size:16px;opacity:0.5;">description</span>',
                    sanitize=False
                )
                ui.label(nome).style(
                    'overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1;'
                )
            el.on('click', lambda cid=cid, nome=nome: self._selecionar_contrato(cid, nome))
            self._sidebar_itens[cid] = el

    def _selecionar_contrato(self, contrato_id: int, contrato_nome: str):
        for cid, el in self._sidebar_itens.items():
            el.classes(remove='ativo')
        if contrato_id in self._sidebar_itens:
            self._sidebar_itens[contrato_id].classes(add='ativo')

        self._contrato_id = contrato_id
        self._contrato_nome = contrato_nome
        self._busca = ''
        self._pagina = 0
        # Reset obra ao trocar contrato
        self._obra_id = None
        self._obra_nome = ''
        self._abc_codigos = set()
        self._abc_quantidades = {}
        self._renderizar_acoes()
        self._renderizar_tabela()

    # ── Área de ações ─────────────────────────────────────────────────────────

    def _renderizar_acoes(self):
        self._acoes_container.clear()
        with self._acoes_container:
            if self._contrato_id is None:
                ui.label('Selecione um contrato no menu lateral.').style(
                    'font-size: 13px; color: #9e9e9e;'
                )
                return

            # ── Linha 1: [Contrato] | [Busca] | [Ações] ──────────────────────
            with ui.element('div').classes('cot-acoes-linha'):
                # Campo de busca — ocupa o espaço disponível
                ui.input(
                    placeholder='Buscar por código ou descrição...',
                    value=self._busca,
                    on_change=lambda e: self._on_busca(e.value),
                ).props('outlined dense clearable').style(
                    'flex: 1; min-width: 160px;'
                )

                ui.html('<div class="cot-acoes-divider"></div>', sanitize=False)

                # Botões de ação — agrupados à direita, sem quebra de linha
                if self._is_admin:
                    ui.button(
                        'Importar Lista de Itens', icon='upload',
                        on_click=self._dialog_importar_plo
                    ).props('outlined dense color=primary').style('font-size: 12px; flex-shrink: 0;')

                ui.button(
                    'Atualizar Cotações', icon='price_change',
                    on_click=self._dialog_atualizar_cotacoes
                ).props('outlined dense color=secondary').style('font-size: 12px; flex-shrink: 0;')

                ui.button(
                    'Exportar dados', icon='download',
                    on_click=self._acao_exportar_template
                ).props('flat dense color=grey-7').style('font-size: 12px; flex-shrink: 0;').tooltip(
                    'Exportar todos os itens e cotações deste contrato (.xlsx)'
                )

            # ── Linha 2: [Obra select] | [PLO da Obra] | [ABC] ───────────────
            obras = self._obras_db.listar_obras()
            opcoes_obras = {str(o['id']): f'{o["nome_contrato"]} — {o["cliente"]}' for o in obras}

            with ui.element('div').classes('cot-acoes-linha'):
                ui.html(
                    '<div style="display:flex;align-items:center;gap:4px;'
                    'background:#f0f4ff;border:1px solid #c5d3f0;border-radius:6px;'
                    'padding:3px 8px;flex-shrink:0;">'
                    '<span class="material-icons" style="font-size:14px;color:#1976d2;">home_work</span>'
                    '<span style="font-size:12px;font-weight:600;color:#1565c0;white-space:nowrap;">Obra</span>'
                    '</div>',
                    sanitize=False
                )

                obra_select = ui.select(
                    options=opcoes_obras,
                    value=str(self._obra_id) if self._obra_id else None,
                    label=None,
                ).props('outlined dense clearable').style('flex: 1; min-width: 200px; max-width: 420px;')

                def _on_obra_change(e):
                    v = e.sender.value
                    if not v:
                        self._obra_id = None
                        self._obra_nome = ''
                        self._abc_codigos = set()
                        self._abc_quantidades = {}
                    else:
                        self._obra_id = int(v)
                        self._obra_nome = opcoes_obras.get(v, '')
                        self._abc_codigos = self._db.listar_abc_codigos(self._obra_id)
                        self._abc_quantidades = self._db.listar_abc_quantidades(self._obra_id)
                    self._renderizar_tabela()

                obra_select.on('update:model-value', _on_obra_change)

                ui.html('<div class="cot-acoes-divider"></div>', sanitize=False)

                ui.button(
                    'Importar PLO da Obra', icon='upload',
                    on_click=self._dialog_importar_plo_obra
                ).props('outlined dense color=teal').style('font-size: 12px; flex-shrink: 0;').bind_enabled_from(
                    self, '_obra_id', backward=lambda v: v is not None
                )

                ui.button(
                    'Exportar ABC', icon='table_chart',
                    on_click=self._acao_exportar_abc
                ).props('unelevated dense color=primary').style('font-size: 12px; flex-shrink: 0;').bind_enabled_from(
                    self, '_obra_id', backward=lambda v: v is not None
                )

    # ── Busca ─────────────────────────────────────────────────────────────────

    def _on_busca(self, valor: str):
        self._busca = (valor or '').strip().lower()
        self._pagina = 0
        self._renderizar_tabela()

    # ── Tabela ────────────────────────────────────────────────────────────────

    def _renderizar_tabela(self):
        self._tabela_outer.clear()
        with self._tabela_outer:
            if self._contrato_id is None:
                with ui.element('div').classes('cot-empty-state'):
                    ui.html(
                        '<span class="material-icons" style="font-size:48px;opacity:0.2;">table_chart</span>',
                        sanitize=False
                    )
                    ui.label('Selecione um contrato para ver os itens de cotação.')
                return

            itens = self._db.listar_itens_contrato(self._contrato_id)

            if self._busca:
                q = self._busca
                itens = [
                    i for i in itens
                    if q in (i.get('codigo') or '').lower()
                    or q in (i.get('descricao') or '').lower()
                ]

            if not itens:
                with ui.element('div').classes('cot-empty-state'):
                    ui.html(
                        '<span class="material-icons" style="font-size:48px;opacity:0.2;">search_off</span>',
                        sanitize=False
                    )
                    if self._busca:
                        ui.label(f'Nenhum item encontrado para "{self._busca}".')
                    else:
                        ui.label('Nenhum item cadastrado para este contrato.')
                        ui.label('Use "Importar PLO" para adicionar itens.').style(
                            'font-size: 12px; color: #bbb;'
                        )
                return

            com_obra = self._obra_id is not None

            if com_obra:
                itens = sorted(
                    itens,
                    key=lambda i: (0 if i.get('codigo', '') in self._abc_codigos else 1, i.get('codigo', ''))
                )

            # Paginação
            total = len(itens)
            total_paginas = max(1, math.ceil(total / _ITENS_POR_PAGINA))
            self._pagina = max(0, min(self._pagina, total_paginas - 1))
            inicio = self._pagina * _ITENS_POR_PAGINA
            itens_pagina = itens[inicio: inicio + _ITENS_POR_PAGINA]

            # Barra de paginação
            with ui.element('div').style(
                'display: flex; align-items: center; gap: 8px; '
                'margin-bottom: 10px; flex-wrap: wrap;'
            ):
                ui.button(
                    icon='chevron_left',
                    on_click=lambda: self._ir_pagina(self._pagina - 1)
                ).props('flat dense round').bind_enabled_from(
                    self, '_pagina', backward=lambda p: p > 0
                )
                ui.label(
                    f'Página {self._pagina + 1} de {total_paginas} '
                    f'({inicio + 1}–{min(inicio + _ITENS_POR_PAGINA, total)} de {total} itens)'
                ).style('font-size: 12px; color: #666; white-space: nowrap;')
                _prox_habilitado = self._pagina < total_paginas - 1
                ui.button(
                    icon='chevron_right',
                    on_click=lambda: self._ir_pagina(self._pagina + 1)
                ).props('flat dense round').bind_enabled_from(
                    self, '_pagina', backward=lambda p, tp=total_paginas: p < tp - 1
                )

            with ui.element('table').classes('cot-table'):
                # Cabeçalho dinâmico — ui.html evita wrapper <div> dentro de <tr>
                if com_obra:
                    ui.html(
                        '<tr>'
                        '<th class="th-check"></th>'
                        '<th>Código</th><th>Descrição</th><th>Unid.</th>'
                        '<th>Qtde.</th>'
                        '<th>Fornecedor A</th><th>Valor A</th>'
                        '<th>Fornecedor B</th><th>Valor B</th>'
                        '<th>Fornecedor C</th><th>Valor C</th>'
                        '<th>Média</th><th>Observação</th>'
                        '</tr>',
                        tag='thead', sanitize=False
                    )
                else:
                    ui.html(
                        '<tr>'
                        '<th>Código</th><th>Descrição</th><th>Unid.</th>'
                        '<th>Fornecedor A</th><th>Valor A</th>'
                        '<th>Fornecedor B</th><th>Valor B</th>'
                        '<th>Fornecedor C</th><th>Valor C</th>'
                        '<th>Média</th><th>Observação</th>'
                        '</tr>',
                        tag='thead', sanitize=False
                    )

                with ui.element('tbody'):
                    for item in itens_pagina:
                        self._renderizar_linha(item, com_obra)

    def _ir_pagina(self, pagina: int):
        self._pagina = pagina
        self._renderizar_tabela()

    def _renderizar_linha(self, item: dict, com_obra: bool):
        codigo = item.get('codigo', '')
        media = item.get('media')
        media_fmt = f'R$ {media:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.') if media else ''
        marcado = codigo in self._abc_codigos

        row_classes = 'linha-marcada' if (com_obra and marcado) else ''

        with ui.element('tr').classes(row_classes):
            if com_obra:
                with ui.element('td').classes('cot-td-check'):
                    cb = ui.checkbox(value=marcado).props('dense')
                    cb.on('update:model-value', lambda e, c=codigo, i=item: self._toggle_abc(c, i, e.args))

            # Código
            with ui.element('td').classes('cot-td-text'):
                ui.label(codigo).style('font-family: monospace; font-size: 12px;')

            # Descrição
            with ui.element('td').classes('cot-td-text').style('max-width: 280px;'):
                ui.label(item.get('descricao') or '').style(
                    'white-space: nowrap; overflow: hidden; text-overflow: ellipsis; '
                    'display: block; max-width: 280px;'
                ).tooltip(item.get('descricao') or '')

            # Unidade
            with ui.element('td').classes('cot-td-text'):
                ui.label(item.get('unidade') or '')

            if com_obra:
                # Quantidade
                qty_val = self._abc_quantidades.get(codigo)
                qty_str = f'{qty_val:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.') if qty_val is not None else ''
                with ui.element('td'):
                    self._celula_quantidade(codigo, qty_str, marcado)

            # Fornecedor A
            with ui.element('td'):
                self._celula_texto(codigo, 'cot_a_fornecedor', item.get('cot_a_fornecedor') or '')

            # Valor A
            with ui.element('td'):
                self._celula_numero(codigo, 'cot_a_valor', item.get('cot_a_valor'))

            # Fornecedor B
            with ui.element('td'):
                self._celula_texto(codigo, 'cot_b_fornecedor', item.get('cot_b_fornecedor') or '')

            # Valor B
            with ui.element('td'):
                self._celula_numero(codigo, 'cot_b_valor', item.get('cot_b_valor'))

            # Fornecedor C
            with ui.element('td'):
                self._celula_texto(codigo, 'cot_c_fornecedor', item.get('cot_c_fornecedor') or '')

            # Valor C
            with ui.element('td'):
                self._celula_numero(codigo, 'cot_c_valor', item.get('cot_c_valor'))

            # Média (só leitura)
            with ui.element('td').classes('cot-td-media'):
                ui.label(media_fmt)

            # Observação
            with ui.element('td'):
                self._celula_texto(codigo, 'observacao', item.get('observacao') or '', largura=180)

    def _toggle_abc(self, codigo: str, item: dict, checked):
        """Marca ou desmarca item para a obra atual."""
        if checked:
            self._db.upsert_abc_item_manual(
                self._obra_id, codigo,
                item.get('descricao', ''), item.get('unidade', '')
            )
            self._abc_codigos.add(codigo)
        else:
            self._db.remover_abc_item(self._obra_id, codigo)
            self._abc_codigos.discard(codigo)
            self._abc_quantidades.pop(codigo, None)
        # Re-render para atualizar cor da linha e disponibilidade do campo Qtde.
        self._renderizar_tabela()

    def _celula_texto(self, codigo: str, campo: str, valor: str, largura: int = 130):
        inp = (
            ui.input(value=valor)
            .props('dense borderless')
            .style(f'width: {largura}px; min-width: {largura}px;')
        )

        def _salvar(e, _codigo=codigo, _campo=campo):
            novo = (e.sender.value or '').strip() or None
            self._db.salvar_cotacao(self._contrato_id, _codigo, {_campo: novo})

        inp.on('blur', _salvar)
        inp.on('keydown.enter', _salvar)
        return inp

    def _celula_numero(self, codigo: str, campo: str, valor):
        valor_str = f'{valor:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.') if valor is not None else ''
        inp = (
            ui.input(value=valor_str, placeholder='0,00')
            .props('dense borderless')
            .style('width: 90px; min-width: 90px;')
        )

        def _salvar(e, _codigo=codigo, _campo=campo):
            raw = (e.sender.value or '').strip().replace(',', '.')
            try:
                novo = float(raw) if raw else None
            except ValueError:
                novo = None
            self._db.salvar_cotacao(self._contrato_id, _codigo, {_campo: novo})

        inp.on('blur', _salvar)
        inp.on('keydown.enter', _salvar)
        return inp

    def _celula_quantidade(self, codigo: str, valor_str: str, marcado: bool):
        """Campo de quantidade na coluna da obra — só editável se item marcado."""
        if not marcado:
            ui.label('—').style('color: #ccc; font-size: 12px; padding: 4px 6px;')
            return

        inp = (
            ui.input(value=valor_str, placeholder='0,00')
            .props('dense borderless')
            .style('width: 80px; min-width: 80px;')
        )

        def _salvar(e, _codigo=codigo):
            raw = (e.sender.value or '').strip().replace(',', '.')
            try:
                novo = float(raw) if raw else None
            except ValueError:
                novo = None
            self._db.atualizar_abc_quantidade(self._obra_id, _codigo, novo)
            if novo is not None:
                self._abc_quantidades[_codigo] = novo
            else:
                self._abc_quantidades.pop(_codigo, None)

        inp.on('blur', _salvar)
        inp.on('keydown.enter', _salvar)
        return inp

    # ── Diálogos ──────────────────────────────────────────────────────────────

    def _dialog_importar_plo(self):
        """Upload da PLO contratual para popular todos os itens do contrato."""
        with ui.dialog() as dialog, ui.card().classes('responsive-dialog-sm').style(
            'padding: 24px; min-width: 420px;'
        ):
            ui.label('Importar PLO do Contrato').style(
                'font-size: 18px; font-weight: bold; color: #1976d2; margin-bottom: 4px;'
            )
            ui.label(
                'Importa todos os itens orçamentários do contrato. '
                'Itens existentes são atualizados; novos são adicionados.'
            ).style('font-size: 13px; color: #666; margin-bottom: 16px;')

            with ui.row().classes('items-center gap-2').style('margin-bottom: 12px;'):
                ui.html(
                    '<span class="material-icons" style="font-size:16px;color:#1976d2;">download</span>',
                    sanitize=False
                )
                link = ui.label('Baixar modelo PLO (.xlsx)').classes('cot-modelo-link')
                link.on('click', lambda: ui.download(gerar_modelo_plo(), 'modelo_plo.xlsx'))

            resultado_label = ui.label('').style('font-size: 13px; color: #555;')

            async def _on_upload(e):
                resultado_label.set_text('Processando...')
                try:
                    dados = await e.file.read()
                    res = await asyncio.to_thread(importar_plo_contrato, dados, self._contrato_id)
                    msgs = []
                    if res['importados'] > 0:
                        msgs.append(f'Novos: {res["importados"]}')
                    if res.get('atualizados', 0) > 0:
                        msgs.append(f'Atualizados: {res["atualizados"]}')
                    if res['erros']:
                        msgs.append(f'Avisos: {len(res["erros"])}')
                    if not msgs:
                        msgs = ['Nenhum item processado.']
                    resultado_label.set_text(' | '.join(msgs))
                    resultado_label.style('color: #e65100;' if res['erros'] else 'color: #2e7d32;')
                    total = res['importados'] + res.get('atualizados', 0)
                    if total > 0:
                        self._renderizar_tabela()
                    if res['erros']:
                        ui.notify('Avisos:\n' + '\n'.join(res['erros'][:5]),
                                  type='warning', timeout=8000, multi_line=True)
                    else:
                        ui.notify(f'{res["importados"]} novo(s), {res.get("atualizados", 0)} atualizado(s).', type='positive')
                except Exception as exc:
                    log_error(exc, "cotacoes_page", "importar plo")
                    resultado_label.set_text(f'Erro: {exc}')
                    resultado_label.style('color: #c62828;')

            ui.upload(
                label='Selecionar PLO (.xlsx)',
                on_upload=_on_upload,
                auto_upload=True,
                max_files=1,
            ).props('accept=".xlsx,.xls"').classes('w-full')

            with ui.row().classes('w-full justify-end gap-2').style('margin-top: 16px;'):
                ui.button('Fechar', on_click=dialog.close).props('flat')

        dialog.open()

    def _dialog_importar_plo_obra(self):
        """Upload da PLO da obra (com quantitativos) — pré-seleciona itens para ABC."""
        if not self._obra_id:
            ui.notify('Selecione uma obra antes de importar a PLO da obra.', type='warning')
            return

        with ui.dialog() as dialog, ui.card().classes('responsive-dialog-sm').style(
            'padding: 24px; min-width: 420px;'
        ):
            ui.label('Importar PLO da Obra').style(
                'font-size: 18px; font-weight: bold; color: #00897b; margin-bottom: 4px;'
            )
            ui.label(
                f'Obra: {self._obra_nome}'
            ).style('font-size: 13px; font-weight: 600; color: #444; margin-bottom: 4px;')
            ui.label(
                'Importa os itens com quantitativos específicos desta obra. '
                'Os itens importados ficam pré-selecionados (checkbox marcado) para exportação ABC.'
            ).style('font-size: 13px; color: #666; margin-bottom: 16px;')

            with ui.row().classes('items-center gap-2').style('margin-bottom: 12px;'):
                ui.html(
                    '<span class="material-icons" style="font-size:16px;color:#00897b;">download</span>',
                    sanitize=False
                )
                link = ui.label('Baixar modelo PLO (.xlsx)').classes('cot-modelo-link')
                link.on('click', lambda: ui.download(gerar_modelo_plo(), 'modelo_plo_obra.xlsx'))

            resultado_label = ui.label('').style('font-size: 13px; color: #555;')

            async def _on_upload(e):
                resultado_label.set_text('Processando...')
                try:
                    dados = await e.file.read()
                    res = await asyncio.to_thread(importar_plo_obra, dados, self._obra_id)
                    msgs = []
                    if res['importados'] > 0:
                        msgs.append(f'Novos: {res["importados"]}')
                    if res.get('atualizados', 0) > 0:
                        msgs.append(f'Atualizados: {res["atualizados"]}')
                    if res['erros']:
                        msgs.append(f'Avisos: {len(res["erros"])}')
                    if not msgs:
                        msgs = ['Nenhum item processado.']
                    resultado_label.set_text(' | '.join(msgs))
                    resultado_label.style('color: #e65100;' if res['erros'] else 'color: #2e7d32;')
                    # Recarrega cache e re-renderiza tabela para mostrar checkboxes
                    self._abc_codigos = self._db.listar_abc_codigos(self._obra_id)
                    self._abc_quantidades = self._db.listar_abc_quantidades(self._obra_id)
                    self._renderizar_tabela()
                    if res['erros']:
                        ui.notify('Avisos:\n' + '\n'.join(res['erros'][:5]),
                                  type='warning', timeout=8000, multi_line=True)
                    else:
                        ui.notify(f'{res["importados"]} novo(s), {res.get("atualizados", 0)} atualizado(s) para a obra.', type='positive')
                except Exception as exc:
                    log_error(exc, "cotacoes_page", "importar plo obra")
                    resultado_label.set_text(f'Erro: {exc}')
                    resultado_label.style('color: #c62828;')

            ui.upload(
                label='Selecionar PLO da obra (.xlsx)',
                on_upload=_on_upload,
                auto_upload=True,
                max_files=1,
            ).props('accept=".xlsx,.xls"').classes('w-full')

            with ui.row().classes('w-full justify-end gap-2').style('margin-top: 16px;'):
                ui.button('Fechar', on_click=dialog.close).props('flat')

        dialog.open()

    def _dialog_atualizar_cotacoes(self):
        """Diálogo unificado: exportar template + importar cotações preenchidas."""
        with ui.dialog() as dialog, ui.card().classes('responsive-dialog-sm').style(
            'padding: 24px; min-width: 460px;'
        ):
            ui.label('Atualizar Cotações').style(
                'font-size: 18px; font-weight: bold; color: #1976d2; margin-bottom: 16px;'
            )

            # ── Seção 1: Exportar template ────────────────────────────────────
            with ui.row().classes('items-center gap-1').style('margin-bottom: 4px;'):
                ui.label('1. Baixar planilha de cotações').style(
                    'font-size: 13px; font-weight: 600; color: #333;'
                )
                ui.icon('help_outline').style(
                    'font-size: 16px; color: #9e9e9e; cursor: default;'
                ).tooltip(
                    'Gera uma planilha Excel com todos os itens do contrato e as cotações '
                    'já cadastradas pré-preenchidas. Preencha ou atualize os valores de '
                    'fornecedor/preço e importe de volta na etapa 2.'
                )

            ui.button(
                'Baixar modelo (.xlsx)', icon='download',
                on_click=lambda: ui.download(gerar_modelo_cotacoes(), 'modelo_cotacoes.xlsx')
            ).props('outlined dense color=secondary').style('font-size: 12px; margin-bottom: 16px;')

            ui.separator()

            # ── Seção 2: Importar cotações ────────────────────────────────────
            with ui.row().classes('items-center gap-1').style('margin-top: 16px; margin-bottom: 4px;'):
                ui.label('2. Importar planilha preenchida').style(
                    'font-size: 13px; font-weight: 600; color: #333;'
                )
                ui.icon('help_outline').style(
                    'font-size: 16px; color: #9e9e9e; cursor: default;'
                ).tooltip(
                    'Importa os valores de cotação a partir de uma planilha preenchida. '
                    'Somente itens já cadastrados no contrato são atualizados. '
                    'Células vazias não apagam valores anteriores.'
                )

            resultado_label = ui.label('').style('font-size: 13px; color: #555; margin-bottom: 8px;')

            async def _on_upload(e):
                resultado_label.set_text('Processando...')
                try:
                    dados = await e.file.read()
                    res = await asyncio.to_thread(importar_template_cotacoes, dados, self._contrato_id)
                    msgs = [f'Atualizados: {res["atualizados"]}']
                    if res.get('ignorados'):
                        msgs.append(f'Ignorados: {res["ignorados"]}')
                    if res['erros']:
                        msgs.append(f'Avisos: {len(res["erros"])}')
                    resultado_label.set_text(' | '.join(msgs))
                    resultado_label.style('color: #e65100;' if res['erros'] else 'color: #2e7d32;')
                    if res['atualizados'] > 0:
                        self._renderizar_tabela()
                    if res['erros']:
                        ui.notify('Avisos:\n' + '\n'.join(res['erros'][:5]),
                                  type='warning', timeout=8000, multi_line=True)
                    else:
                        ui.notify(f'{res["atualizados"]} cotação(ões) atualizada(s).', type='positive')
                except Exception as exc:
                    log_error(exc, "cotacoes_page", "importar cotacoes")
                    resultado_label.set_text(f'Erro: {exc}')
                    resultado_label.style('color: #c62828;')

            ui.upload(
                label='Selecionar planilha de cotações (.xlsx)',
                on_upload=_on_upload,
                auto_upload=True,
                max_files=1,
            ).props('accept=".xlsx,.xls"').classes('w-full')

            with ui.row().classes('w-full justify-end').style('margin-top: 16px;'):
                ui.button('Fechar', on_click=dialog.close).props('flat')

        dialog.open()

    def _acao_exportar_template(self):
        if not self._contrato_id:
            return
        try:
            dados = exportar_template_cotacoes(self._contrato_id)
            nome = f'template_cotacoes_{self._contrato_nome[:20].strip()}.xlsx'.replace(' ', '_')
            ui.download(dados, nome)
        except Exception as exc:
            log_error(exc, "cotacoes_page", "exportar template")
            ui.notify(f'Erro ao gerar template: {exc}', type='negative')

    def _acao_exportar_abc(self):
        """Exporta ABC com os itens marcados para a obra selecionada."""
        if not self._obra_id or not self._contrato_id:
            return
        if not self._abc_codigos:
            ui.notify(
                'Nenhum item selecionado para esta obra. '
                'Importe a PLO da obra ou marque itens na tabela.',
                type='warning'
            )
            return
        try:
            dados = exportar_abc(self._obra_id, self._contrato_id)
            nome = (
                f'ABC_{self._obra_nome[:25]}.xlsx'
                .replace(' ', '_')
                .replace('—', '')
                .replace('/', '-')
            )
            ui.download(dados, nome)
            ui.notify('Planilha ABC gerada com sucesso.', type='positive')
        except Exception as exc:
            log_error(exc, "cotacoes_page", "exportar abc")
            ui.notify(f'Erro ao gerar ABC: {exc}', type='negative')
