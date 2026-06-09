"""
Página Biblioteca — visualização e gestão de cards de conhecimento.
Admins podem criar/editar/excluir cards e gerenciar tags.
Todos os usuários autenticados podem visualizar e filtrar.
"""

import datetime
import os
import re
from typing import List, Optional

from nicegui import ui

from db.biblioteca_repo import BibliotecaRepository, PASTA_UPLOADS
from services.auth_service import obter_usuario_logado
from core.error_logger import log_error
from utils.image_utils import processar_e_salvar_imagem


# ── Helpers de módulo ─────────────────────────────────────────────────────────

def _nome_arquivo(imagem_path: str) -> str:
    """Extrai apenas o nome do arquivo do caminho absoluto ou relativo."""
    return os.path.basename(imagem_path)


def _formatar_datetime(valor: Optional[str]) -> str:
    if not valor:
        return ''
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            dt = datetime.datetime.strptime(valor, fmt)
            return dt.strftime('%d/%m/%Y %H:%M') if ' ' in valor else dt.strftime('%d/%m/%Y')
        except ValueError:
            continue
    return valor


# ── Página principal ──────────────────────────────────────────────────────────

class BibliotecaPage:
    def __init__(self):
        self.repo = BibliotecaRepository()
        self.usuario = obter_usuario_logado()
        self.is_admin = bool(self.usuario.get('is_admin'))
        self._tag_ids_selecionadas: List[int] = []
        self._busca_query: str = ''
        self._cards_container = None
        self._tag_checkboxes: dict = {}
        self._tags_lista_container = None
        self._imagem_path: Optional[str] = None

        self._injetar_css()
        self._header()
        self._body()

    # ── CSS ───────────────────────────────────────────────────────────────────

    def _injetar_css(self):
        ui.add_head_html('''
        <style>
        /* Remove padding padrão do NiceGUI e trava scroll da página */
        :root { --nicegui-default-padding: 0; }
        .nicegui-content { padding: 0 !important; overflow: hidden; }

        /* Dialogs responsivos */
        .responsive-dialog {
            width: min(96vw, 900px) !important;
            max-width: 96vw !important;
        }
        .responsive-dialog-sm {
            width: min(96vw, 560px) !important;
            max-width: 96vw !important;
        }

        /* Header */
        .biblioteca-header-btn-novo {
            background: rgba(255,255,255,0.12) !important;
            color: white !important;
            font-weight: 600 !important;
            font-size: 13px !important;
            border-radius: 8px !important;
            padding: 0 14px !important;
            height: 34px !important;
            letter-spacing: 0.01em;
            border: 1px solid rgba(255,255,255,0.18) !important;
            transition: background 0.15s !important;
        }
        .biblioteca-header-btn-novo:hover {
            background: rgba(255,255,255,0.2) !important;
        }
        .biblioteca-header-user {
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
        .biblioteca-header-avatar {
            width: 28px;
            height: 28px;
            border-radius: 50%;
            background: rgba(100,181,246,0.2);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 11px;
            font-weight: 700;
            color: #90caf9;
            flex-shrink: 0;
        }

        /* Layout */
        .biblioteca-layout {
            display: flex;
            flex-direction: row;
            width: 100%;
            box-sizing: border-box;
            height: calc(100vh - 56px);
            background: #f0f2f5;
            overflow: hidden;
        }

        /* Campo de busca da sidebar */
        .bib-search-wrap {
            position: relative;
            margin-bottom: 16px;
        }
        .bib-search-wrap .q-field__control {
            border-radius: 8px !important;
            background: #f4f6f9 !important;
        }
        .bib-search-wrap .q-field__control:before {
            border-color: #e8eaf0 !important;
        }
        .bib-search-wrap .q-field__control:hover:before {
            border-color: #1976d2 !important;
        }
        .bib-search-divider {
            font-size: 11px;
            font-weight: 700;
            color: #9e9e9e;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            padding: 0 4px;
            margin-bottom: 8px;
        }

        /* Sidebar */
        .biblioteca-sidebar {
            width: 256px;
            min-width: 256px;
            background: #ffffff;
            border-right: 1px solid #e8eaf0;
            padding: 20px 16px;
            display: flex;
            flex-direction: column;
            gap: 4px;
            overflow-y: auto;
            box-shadow: 2px 0 12px rgba(0,0,0,0.04);
        }
        .biblioteca-sidebar-title {
            font-size: 11px;
            font-weight: 700;
            color: #9e9e9e;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            margin-bottom: 8px;
            padding: 0 4px;
        }
        .biblioteca-tag-item {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 7px 10px;
            border-radius: 8px;
            cursor: pointer;
            transition: background 0.15s;
            font-size: 13px;
            color: #424242;
            user-select: none;
        }
        .biblioteca-tag-item:hover {
            background: #f0f4ff;
            color: #1565c0;
        }
        .biblioteca-tag-item.ativo {
            background: #e8f0fe;
            color: #1565c0;
            font-weight: 600;
        }
        .biblioteca-tag-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #c5cae9;
            flex-shrink: 0;
            transition: background 0.15s;
        }
        .biblioteca-tag-item.ativo .biblioteca-tag-dot {
            background: #1565c0;
        }
        .biblioteca-filtros-counter {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            background: #1565c0;
            color: white;
            border-radius: 10px;
            font-size: 10px;
            font-weight: 700;
            min-width: 18px;
            height: 18px;
            padding: 0 5px;
            margin-left: 4px;
        }

        /* Área de cards */
        .biblioteca-cards {
            flex: 1;
            padding: 24px;
            overflow-y: auto;
            min-width: 0;
        }

        /* Card */
        .bib-card {
            background: white;
            border-radius: 12px;
            border: 1px solid #e8eaf0;
            padding: 18px 18px 14px 18px;
            cursor: pointer;
            transition: box-shadow 0.2s, border-color 0.2s, transform 0.15s;
            display: flex;
            flex-direction: column;
            gap: 8px;
            min-height: 140px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.05);
        }
        .bib-card:hover {
            box-shadow: 0 10px 28px rgba(0,0,0,0.12);
            border-color: #c5cae9;
            transform: translateY(-3px);
        }
        .bib-card-title {
            font-size: 15px;
            font-weight: 700;
            color: #1a2332;
            line-height: 1.35;
            margin-bottom: 2px;
        }
        .bib-card-preview {
            font-size: 13px;
            color: #6b7280;
            line-height: 1.55;
            flex: 1;
            overflow: hidden;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
        }
        .bib-card-footer {
            font-size: 11px;
            color: #c0c4ce;
            margin-top: 2px;
            display: flex;
            align-items: center;
            gap: 4px;
        }
        .biblioteca-tag-chip {
            display: inline-block;
            background: #eef2ff;
            color: #4f46e5;
            border-radius: 20px;
            padding: 2px 10px;
            font-size: 11px;
            font-weight: 600;
            margin: 2px;
            letter-spacing: 0.01em;
        }
        .biblioteca-filtrar-btn {
            display: none !important;
        }

        /* Botão limpar filtros */
        .biblioteca-limpar-btn {
            width: 100%;
            text-align: center;
            font-size: 12px;
            color: #1976d2;
            padding: 6px 0;
            border-radius: 6px;
            cursor: pointer;
            margin-top: 8px;
            transition: background 0.15s;
        }
        .biblioteca-limpar-btn:hover {
            background: #f0f4ff;
        }

        @media (max-width: 768px) {
            .biblioteca-sidebar {
                display: none !important;
            }
            .biblioteca-filtrar-btn {
                display: inline-flex !important;
            }
            .biblioteca-cards {
                padding: 12px;
            }
        }
        </style>
        ''')

    # ── Header ────────────────────────────────────────────────────────────────

    def _header(self):
        nome = self.usuario.get('nome', '')
        sobrenome = self.usuario.get('sobrenome', '')
        iniciais = (nome[:1] + sobrenome[:1]).upper() if nome or sobrenome else '?'
        nome_exibicao = f'{nome} {sobrenome}'.strip() or 'Usuário'

        with ui.header().classes('items-center').style(
            'background: #0f172a;'
            'padding: 0 20px; height: 56px; gap: 12px; flex-wrap: nowrap;'
            'box-shadow: 0 2px 10px rgba(0,0,0,0.25);'
        ):
            ui.button(
                icon='arrow_back',
                on_click=lambda: ui.navigate.to('/')
            ).props('flat round text-color=white').style('opacity: 0.7;').tooltip('Voltar ao Início')

            with ui.element('div').style(
                'display: flex; align-items: center; gap: 10px; '
                'border-left: 1px solid rgba(255,255,255,0.1); padding-left: 14px;'
            ):
                ui.label('📚').style('font-size: 18px; line-height: 1;')
                ui.label('Biblioteca').style(
                    'font-size: clamp(15px, 2vw, 18px); color: white; '
                    'font-weight: 700; letter-spacing: -0.01em;'
                )

            ui.space()

            ui.button(
                icon='filter_list',
                on_click=self._abrir_filtros_mobile
            ).classes('biblioteca-filtrar-btn').props('flat round text-color=white').tooltip('Filtrar por tags')

            if self.is_admin:
                ui.button(
                    '+ Novo Card', on_click=lambda: self._abrir_form_card(None)
                ).classes('biblioteca-header-btn-novo').style('margin-right: 6px;')

            with ui.element('div').classes('biblioteca-header-user'):
                with ui.element('div').classes('biblioteca-header-avatar'):
                    ui.label(iniciais)
                ui.label(nome_exibicao).style(
                    'max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;'
                )

            ui.button(
                icon='logout',
                on_click=lambda: ui.navigate.to('/logout')
            ).props('flat round text-color=white').style('opacity: 0.6;').tooltip('Sair')

    # ── Body ──────────────────────────────────────────────────────────────────

    def _body(self):
        with ui.element('div').classes('biblioteca-layout'):
            with ui.element('div').classes('biblioteca-sidebar'):
                self._sidebar()
            with ui.element('div').classes('biblioteca-cards'):
                self._cards_container = ui.element('div').classes('w-full')
                self._renderizar_cards()

    # ── Sidebar ───────────────────────────────────────────────────────────────

    def _sidebar(self):
        with ui.element('div').classes('bib-search-wrap'):
            busca = (
                ui.input(
                    placeholder='Buscar título ou conteúdo...',
                    on_change=lambda e: self._on_busca(e.value),
                )
                .props('outlined dense clearable')
                .classes('w-full')
            )
            busca.on('clear', lambda: self._on_busca(''))

        ui.html('<div class="bib-search-divider">FILTRAR POR TAG</div>', sanitize=False)

        tags = self.repo.listar_tags()

        self._tag_search_input = None
        if len(tags) > 10:
            self._tag_search_input = (
                ui.input(placeholder='Buscar tag...')
                .props('outlined dense clearable')
                .classes('w-full')
                .style('margin-bottom: 8px; font-size: 13px;')
            )
            self._tag_search_input.on(
                'input',
                lambda: self._filtrar_tags_sidebar(self._tag_search_input.value)
            )

        self._tags_lista_container = ui.column().classes('w-full').style('gap: 2px;')
        self._renderizar_tag_checkboxes(tags)

        ui.space()

        self._limpar_btn_container = ui.element('div')
        self._atualizar_botao_limpar()

        if self.is_admin:
            ui.separator().style('margin: 12px 0;')
            ui.button(
                icon='label', text='Gerenciar Tags', on_click=self._abrir_gerenciar_tags
            ).props('flat').style(
                'color: #757575; font-size: 12px; width: 100%; justify-content: flex-start; padding: 6px 10px; border-radius: 8px;'
            )

    def _renderizar_tag_checkboxes(self, tags: List[dict]):
        self._tags_lista_container.clear()
        self._tag_checkboxes = {}
        with self._tags_lista_container:
            if not tags:
                ui.label('Nenhuma tag cadastrada.').style('color: #bdbdbd; font-size: 12px; padding: 8px 4px;')
                return
            for tag in tags:
                tid = tag['id']
                ativo = tid in self._tag_ids_selecionadas
                classe = 'biblioteca-tag-item ativo' if ativo else 'biblioteca-tag-item'
                item = ui.element('div').classes(classe)
                self._tag_checkboxes[tid] = item
                with item:
                    ui.element('div').classes('biblioteca-tag-dot')
                    ui.label(tag['nome'])
                item.on('click', lambda t=tid: self._on_tag_toggle(t, t not in self._tag_ids_selecionadas))

    def _filtrar_tags_sidebar(self, query: str):
        q = (query or '').strip().lower()
        todas = self.repo.listar_tags()
        filtradas = [t for t in todas if q in t['nome'].lower()] if q else todas
        self._renderizar_tag_checkboxes(filtradas)

    def _atualizar_botao_limpar(self):
        self._limpar_btn_container.clear()
        with self._limpar_btn_container:
            if self._tag_ids_selecionadas:
                n = len(self._tag_ids_selecionadas)
                ui.button(
                    f'Limpar {n} filtro{"s" if n > 1 else ""}',
                    icon='close',
                    on_click=self._limpar_filtros,
                ).props('flat').style(
                    'color: #1976d2; font-size: 12px; width: 100%; justify-content: center; padding: 6px 0; border-radius: 8px;'
                )

    def _on_tag_toggle(self, tag_id: int, selecionado: bool):
        if selecionado:
            if tag_id not in self._tag_ids_selecionadas:
                self._tag_ids_selecionadas.append(tag_id)
        else:
            self._tag_ids_selecionadas = [t for t in self._tag_ids_selecionadas if t != tag_id]
        for tid, item in self._tag_checkboxes.items():
            ativo = tid in self._tag_ids_selecionadas
            item.classes(remove='ativo' if not ativo else '')
            item.classes(add='ativo' if ativo else '')
        self._atualizar_botao_limpar()
        self._renderizar_cards()

    def _limpar_filtros(self):
        self._tag_ids_selecionadas = []
        for item in self._tag_checkboxes.values():
            item.classes(remove='ativo')
        self._atualizar_botao_limpar()
        self._renderizar_cards()

    def _on_busca(self, valor: str):
        self._busca_query = (valor or '').strip().lower()
        self._renderizar_cards()

    # ── Cards grid ────────────────────────────────────────────────────────────

    def _renderizar_cards(self):
        self._cards_container.clear()
        with self._cards_container:
            tag_ids = self._tag_ids_selecionadas if self._tag_ids_selecionadas else None
            cards = self.repo.listar_cards(tag_ids)

            if self._busca_query:
                q = self._busca_query
                def _match(c: dict) -> bool:
                    if q in c.get('titulo', '').lower():
                        return True
                    conteudo_limpo = re.sub(r'<[^>]+>', '', c.get('conteudo', '') or '')
                    return q in conteudo_limpo.lower()
                cards = [c for c in cards if _match(c)]

            tem_filtros = bool(self._tag_ids_selecionadas or self._busca_query)
            if not cards:
                with ui.element('div').style(
                    'display: flex; flex-direction: column; align-items: center; justify-content: center;'
                    'padding: 64px 32px; color: #bdbdbd; gap: 12px;'
                ):
                    ui.html('<span style="font-size: 48px;">📭</span>', sanitize=False)
                    ui.label(
                        'Nenhum card encontrado' if not tem_filtros
                        else 'Nenhum resultado para a busca'
                    ).style('font-size: 16px; font-weight: 500; color: #9e9e9e;')
                    if self._tag_ids_selecionadas:
                        ui.button(
                            'Limpar filtros', on_click=self._limpar_filtros
                        ).props('flat').style('color: #1976d2; font-size: 13px;')
                return

            with ui.grid(
                columns='repeat(auto-fill, minmax(min(100%, 300px), 1fr))'
            ).classes('w-full').style('gap: 16px;'):
                for card in cards:
                    self._criar_card_widget(card)

    def _criar_card_widget(self, card: dict):
        tags = self.repo.obter_tags_card(card['id'])
        criado_em_fmt = _formatar_datetime(card.get('criado_em'))
        editado_em = card.get('editado_em')

        with ui.element('div').classes('bib-card').on(
            'click', lambda c=card: self._abrir_visualizar_card(c['id'])
        ):
            with ui.element('div').style('display: flex; align-items: flex-start; justify-content: space-between; gap: 8px;'):
                ui.html(
                    f'<span class="bib-card-title">{card["titulo"]}</span>',
                    sanitize=False
                )
                if self.is_admin:
                    ui.button(
                        icon='delete',
                        on_click=lambda c=card: self._confirmar_excluir_card(c['id'], c['titulo'])
                    ).props('flat dense round stop-propagation').style(
                        'color: #e0e0e0; flex-shrink: 0; margin: -4px -6px 0 0;'
                    ).classes('hover:text-red-500').tooltip('Excluir')

            if tags:
                chips_html = ''.join(
                    f'<span class="biblioteca-tag-chip">{t["nome"]}</span>'
                    for t in tags
                )
                ui.html(f'<div style="margin: 2px 0;">{chips_html}</div>', sanitize=False)

            conteudo_txt = card.get('conteudo', '') or ''
            conteudo_limpo = re.sub(r'<[^>]+>', '', conteudo_txt).strip()
            if conteudo_limpo:
                ui.html(
                    f'<p class="bib-card-preview">{conteudo_limpo[:180]}</p>',
                    sanitize=False
                )

            footer_txt = f'👤 {card.get("criado_por", "?")}  ·  {criado_em_fmt}'
            if editado_em:
                footer_txt += f'  ·  ✏️ {_formatar_datetime(editado_em)}'
            ui.html(
                f'<div class="bib-card-footer">{footer_txt}</div>',
                sanitize=False
            )

    # ── Visualizar card (fullscreen-like dialog) ──────────────────────────────

    def _abrir_visualizar_card(self, card_id: int):
        card = self.repo.obter_card(card_id)
        if not card:
            ui.notification('Card não encontrado.', type='warning')
            return
        tags = self.repo.obter_tags_card(card_id)

        with ui.dialog().props('persistent') as dlg, ui.card().classes(
            'responsive-dialog'
        ).style('max-height: 90vh; overflow-y: auto; padding: 20px;'):

            with ui.row().classes('w-full items-center justify-between').style(
                'margin-bottom: 8px;'
            ):
                ui.label(card['titulo']).style(
                    'font-size: 22px; font-weight: bold; color: #1976d2;'
                )
                ui.button('✕', on_click=dlg.close).props('flat dense round').style(
                    'color: #666;'
                )

            if tags:
                chips_html = ''.join(
                    f'<span class="biblioteca-tag-chip">{t["nome"]}</span>'
                    for t in tags
                )
                ui.html(f'<div style="line-height: 2; margin-bottom: 8px;">{chips_html}</div>', sanitize=False)

            ui.separator()

            if card.get('conteudo'):
                ui.html(card['conteudo'], sanitize=False).style('margin: 12px 0; line-height: 1.7;')
            else:
                ui.label('Sem conteúdo.').style(
                    'color: #999; font-style: italic; margin: 12px 0;'
                )

            if card.get('imagem_path'):
                ui.html(
                    f'<img src="/uploads/{_nome_arquivo(card["imagem_path"])}"'
                    ' style="max-width:100%; border-radius:6px; margin-top:12px;" />',
                    sanitize=False,
                )

            ui.separator()

            criado_em_fmt = _formatar_datetime(card.get('criado_em'))
            editado_em = card.get('editado_em')
            partes = [f'Criado por {card.get("criado_por", "?")} em {criado_em_fmt}']
            if editado_em:
                partes.append(f'Editado em {_formatar_datetime(editado_em)}')
            ui.label(' · '.join(partes)).style(
                'font-size: 12px; color: #999; margin-top: 8px;'
            )

            if self.is_admin:
                with ui.row().classes('w-full justify-end gap-2').style('margin-top: 12px;'):
                    ui.button(
                        '✏️ Editar',
                        on_click=lambda: [dlg.close(), self._abrir_form_card(card_id)]
                    ).props('outline').style('color: #1976d2;')
                    ui.button(
                        '🗑️ Excluir',
                        on_click=lambda: [
                            dlg.close(),
                            self._confirmar_excluir_card(card_id, card['titulo'])
                        ]
                    ).style('background-color: #f44336; color: white;')

        dlg.open()

    # ── Formulário criação / edição ───────────────────────────────────────────

    def _abrir_form_card(self, card_id: Optional[int]):
        is_edit = card_id is not None
        card = self.repo.obter_card(card_id) if is_edit else None
        card_tags_atuais = (
            {t['id'] for t in self.repo.obter_tags_card(card_id)} if is_edit else set()
        )
        all_tags = self.repo.listar_tags()

        self._imagem_path = None

        with ui.dialog().props('persistent') as dlg, ui.card().classes(
            'responsive-dialog'
        ).style('max-height: 90vh; overflow-y: auto; padding: 20px;'):

            titulo_header = '✏️ Editar Card' if is_edit else '➕ Novo Card'
            with ui.row().classes('w-full items-center justify-between').style(
                'margin-bottom: 12px;'
            ):
                ui.label(titulo_header).style(
                    'font-size: 22px; font-weight: bold; color: #1976d2;'
                )
                ui.button('✕', on_click=dlg.close).props('flat dense round').style(
                    'color: #666;'
                )

            titulo_input = (
                ui.input('Título *', value=card['titulo'] if card else '')
                .props('outlined dense')
                .classes('w-full')
                .style('margin-bottom: 12px;')
            )

            # Tags
            tag_opcoes = {tag['id']: tag['nome'] for tag in all_tags}
            tag_select = ui.select(
                tag_opcoes,
                label='Tags',
                multiple=True,
                value=list(card_tags_atuais),
            ).classes('w-full').props('outlined use-chips')

            # Conteúdo rich text
            ui.label('Conteúdo').style(
                'font-size: 13px; font-weight: 500; color: #555; margin-bottom: 4px;'
            )
            editor = ui.editor(
                value=card.get('conteudo', '') if card else ''
            ).classes('w-full').style('min-height: 200px; margin-bottom: 12px;')

            # Upload de imagem
            ui.label('Imagem (opcional)').style(
                'font-size: 13px; font-weight: 500; color: #555; margin-bottom: 4px;'
            )
            imagem_status = ui.label('').style('font-size: 12px; color: #666; margin-bottom: 4px;')
            if is_edit and card and card.get('imagem_path'):
                imagem_status.set_text('Imagem atual mantida — envie uma nova para substituir.')

            async def on_upload(e):
                dados_originais = await e.file.read()
                try:
                    caminho = processar_e_salvar_imagem(dados_originais, PASTA_UPLOADS)
                    self._imagem_path = caminho
                    tamanho_kb = os.path.getsize(caminho) // 1024
                    original_kb = len(dados_originais) // 1024
                    imagem_status.set_text(
                        f'Imagem processada: {e.file.name} '
                        f'({original_kb} KB → {tamanho_kb} KB)'
                    )
                except Exception as ex:
                    log_error(ex, 'ui.pages.biblioteca', f'on_upload: {e.file.name}')
                    ui.notify(f'Erro ao processar imagem: {ex}', type='negative')

            ui.upload(
                label='Selecionar imagem',
                on_upload=on_upload,
                auto_upload=True,
                max_files=1,
            ).props('accept="image/*"').classes('w-full').style('margin-bottom: 12px;')

            def salvar():
                titulo = (titulo_input.value or '').strip()
                if not titulo:
                    ui.notify('⚠️ O título é obrigatório.', type='warning')
                    return

                tag_ids_sel = tag_select.value or []
                if not tag_ids_sel:
                    ui.notify('⚠️ Selecione ao menos uma tag.', type='warning')
                    return

                if not all(tid in tag_opcoes for tid in tag_ids_sel):
                    ui.notify('⚠️ Uma ou mais tags selecionadas são inválidas.', type='warning')
                    return

                conteudo = editor.value or ''

                try:
                    if is_edit:
                        self.repo.editar_card(
                            card_id, titulo, conteudo, self._imagem_path
                        )
                        self.repo.vincular_tags_card(card_id, tag_ids_sel)
                    else:
                        nome_u = f'{self.usuario.get("nome", "")} {self.usuario.get("sobrenome", "")}'.strip()
                        novo_id = self.repo.criar_card(
                            titulo, conteudo, self._imagem_path, nome_u
                        )
                        self.repo.vincular_tags_card(novo_id, tag_ids_sel)

                    ui.notify('Card salvo com sucesso!', type='positive')
                    dlg.close()
                    self._renderizar_cards()
                except Exception as ex:
                    log_error(ex, 'ui.pages.biblioteca', f'salvar card: {titulo}')
                    ui.notify(f'Erro ao salvar: {ex}', type='negative')

            with ui.row().classes('w-full justify-end gap-2').style('margin-top: 8px;'):
                ui.button('Cancelar', on_click=dlg.close).props('flat').style('color: #666;')
                ui.button(
                    '💾 Salvar', on_click=salvar
                ).style('background-color: #1976d2; color: white; font-weight: bold;')

        dlg.open()

    # ── Confirmação de exclusão ───────────────────────────────────────────────

    def _confirmar_excluir_card(self, card_id: int, titulo: str):
        with ui.dialog().props('persistent') as dlg, ui.card().classes(
            'responsive-dialog-sm'
        ).style('padding: 20px;'):
            ui.label('🗑️ Excluir Card').style(
                'font-size: 20px; font-weight: bold; color: #f44336; margin-bottom: 8px;'
            )
            ui.label(
                f'Deseja excluir o card "{titulo}"? Esta ação não pode ser desfeita.'
            ).style('font-size: 14px; color: #555; margin-bottom: 16px;')

            def confirmar():
                try:
                    self.repo.excluir_card(card_id)
                    ui.notification('Card excluído.', type='positive', timeout=2)
                    dlg.close()
                    self._renderizar_cards()
                except Exception as ex:
                    log_error(ex, 'ui.pages.biblioteca', f'excluir card id={card_id}')
                    ui.notification(f'Erro ao excluir: {ex}', type='negative')

            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('Cancelar', on_click=dlg.close).props('flat').style('color: #666;')
                ui.button(
                    'Excluir', on_click=confirmar
                ).style('background-color: #f44336; color: white; font-weight: bold;')

        dlg.open()

    # ── Gerenciar Tags ────────────────────────────────────────────────────────

    def _abrir_gerenciar_tags(self):
        with ui.dialog().props('persistent') as dlg, ui.card().classes(
            'responsive-dialog-sm'
        ).style('max-height: 90vh; overflow-y: auto; padding: 20px;'):

            with ui.row().classes('w-full items-center justify-between').style(
                'margin-bottom: 12px;'
            ):
                ui.label('🏷️ Gerenciar Tags').style(
                    'font-size: 20px; font-weight: bold; color: #1976d2;'
                )
                ui.button('✕', on_click=dlg.close).props('flat dense round').style(
                    'color: #666;'
                )

            nova_tag_input = (
                ui.input('Nova tag')
                .props('outlined dense')
                .classes('w-full')
                .style('margin-bottom: 8px;')
            )

            lista_tags_container = ui.column().classes('w-full gap-1')

            def renderizar_lista():
                lista_tags_container.clear()
                tags = self.repo.listar_tags()
                with lista_tags_container:
                    if not tags:
                        ui.label('Nenhuma tag cadastrada.').style(
                            'color: #999; font-size: 13px;'
                        )
                        return
                    for tag in tags:
                        with ui.row().classes('w-full items-center justify-between').style(
                            'padding: 4px 0; border-bottom: 1px solid #f0f0f0;'
                        ):
                            ui.label(tag['nome']).style('font-size: 14px;')
                            with ui.row().classes('gap-1'):
                                ui.button(
                                    icon='edit',
                                    on_click=lambda t=tag: abrir_renomear(t)
                                ).props('flat dense round').style('color: #1976d2;').tooltip('Renomear')
                                ui.button(
                                    icon='delete',
                                    on_click=lambda t=tag: excluir_tag(t['id'])
                                ).props('flat dense round').style('color: #f44336;').tooltip('Excluir')

            def criar_tag():
                nome = (nova_tag_input.value or '').strip()
                if not nome:
                    ui.notification('Informe o nome da tag.', type='warning')
                    return
                try:
                    self.repo.criar_tag(nome)
                    nova_tag_input.set_value('')
                    renderizar_lista()
                    ui.notification('Tag criada.', type='positive', timeout=2)
                    # Atualiza sidebar
                    self._renderizar_tag_checkboxes(self.repo.listar_tags())
                except Exception as ex:
                    log_error(ex, 'ui.pages.biblioteca', f'criar_tag: {nome}')
                    ui.notification(
                        'Erro ao criar tag (talvez já exista).', type='negative'
                    )

            def excluir_tag(tag_id: int):
                try:
                    self.repo.excluir_tag(tag_id)
                    renderizar_lista()
                    self._renderizar_tag_checkboxes(self.repo.listar_tags())
                    ui.notification('Tag excluída.', type='positive', timeout=2)
                except Exception as ex:
                    log_error(ex, 'ui.pages.biblioteca', f'excluir_tag id={tag_id}')
                    ui.notification('Erro ao excluir tag.', type='negative')

            def abrir_renomear(tag: dict):
                with ui.dialog().props('persistent') as rename_dlg, ui.card().classes(
                    'responsive-dialog-sm'
                ).style('padding: 20px;'):
                    ui.label(f'Renomear tag "{tag["nome"]}"').style(
                        'font-size: 16px; font-weight: bold; margin-bottom: 10px;'
                    )
                    rename_input = (
                        ui.input('Novo nome', value=tag['nome'])
                        .props('outlined dense')
                        .classes('w-full')
                        .style('margin-bottom: 12px;')
                    )

                    def salvar_rename():
                        novo_nome = (rename_input.value or '').strip()
                        if not novo_nome:
                            ui.notification('Informe o novo nome.', type='warning')
                            return
                        try:
                            self.repo.renomear_tag(tag['id'], novo_nome)
                            rename_dlg.close()
                            renderizar_lista()
                            self._renderizar_tag_checkboxes(self.repo.listar_tags())
                            ui.notification('Tag renomeada.', type='positive', timeout=2)
                        except Exception as ex:
                            log_error(ex, 'ui.pages.biblioteca', f'renomear_tag id={tag["id"]}')
                            ui.notification('Erro ao renomear tag.', type='negative')

                    with ui.row().classes('w-full justify-end gap-2'):
                        ui.button('Cancelar', on_click=rename_dlg.close).props('flat').style(
                            'color: #666;'
                        )
                        ui.button(
                            'Salvar', on_click=salvar_rename
                        ).style('background-color: #1976d2; color: white;')

                rename_dlg.open()

            ui.button(
                '+ Criar Tag', on_click=criar_tag
            ).style(
                'background-color: #1976d2; color: white; margin-bottom: 12px;'
            )
            ui.separator()
            renderizar_lista()

        dlg.open()

    # ── Filtro mobile ─────────────────────────────────────────────────────────

    def _abrir_filtros_mobile(self):
        tags = self.repo.listar_tags()

        with ui.dialog().props('persistent') as dlg, ui.card().classes(
            'responsive-dialog-sm'
        ).style('max-height: 80vh; overflow-y: auto; padding: 20px;'):
            with ui.row().classes('w-full items-center justify-between').style(
                'margin-bottom: 8px;'
            ):
                ui.label('Filtrar por Tag').style(
                    'font-size: 18px; font-weight: bold; color: #1976d2;'
                )
                ui.button('✕', on_click=dlg.close).props('flat dense round').style(
                    'color: #666;'
                )

            mobile_checkboxes: dict = {}
            with ui.column().classes('w-full gap-1'):
                for tag in tags:
                    mobile_checkboxes[tag['id']] = ui.checkbox(
                        tag['nome'],
                        value=(tag['id'] in self._tag_ids_selecionadas)
                    ).style('font-size: 14px;')

            def limpar():
                for cb in mobile_checkboxes.values():
                    cb.set_value(False)

            def aplicar():
                self._tag_ids_selecionadas = [
                    tid for tid, cb in mobile_checkboxes.items() if cb.value
                ]
                dlg.close()
                self._renderizar_cards()

            with ui.row().classes('w-full justify-end gap-2').style('margin-top: 12px;'):
                ui.button('Limpar', on_click=limpar).props('flat').style('color: #666;')
                ui.button(
                    'Aplicar', on_click=aplicar
                ).style('background-color: #1976d2; color: white;')

        dlg.open()
