"""
Página Comunicações — e-mails das obras (caixa pessoal + histórico da equipe)
e controle de seguros alimentado pelas mensagens publicadas.
O conteúdo vem de comunicacoes/page.py; aqui fica a moldura do AgendaObras
(sidebar lateral, mini-header mobile e topbar), igual à tela de Obras.
"""

import datetime

from nicegui import app, ui

from comunicacoes.page import render_mail_page
from comunicacoes.runtime import authorize_user, available_works, get_shared_store, get_store
from comunicacoes.seguro_bridge import SeguroComEmails
from core.config import VERSION
from db.connection import CAMINHO_DB
from services.auth_service import obter_usuario_logado
from services.seguro_service import SeguroService

URL_MANUAL = 'https://docs.google.com/presentation/d/1paRtae89yfmLcyJaWgQrtZFM3FKy1MsOEauxMzdylPA/edit?usp=sharing'


class ComunicacoesPage:
    def __init__(self):
        self.usuario = obter_usuario_logado()
        self.owner = app.storage.user.get('user_id')

        self._injetar_css()
        self._sidebar()
        self._body()

    # ── CSS (mesmos tokens de agenda_obras.configurar_layout_responsivo) ──────

    def _injetar_css(self):
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

            @media (min-width: 1024px) {
                .ao-mobile-header { display: none !important; }
                .q-page-container { padding-top: 0 !important; }
            }

            .q-drawer__content {
                display: flex !important;
                flex-direction: column !important;
                align-items: stretch !important;
                width: 100% !important;
                gap: .5rem;
            }
            .q-drawer__content > div,
            .q-drawer__content > * {
                width: 100% !important;
                box-sizing: border-box !important;
            }
            .ao-nav-section-title {
                font-size: 10px;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.1em;
                color: rgba(255,255,255,0.3);
                padding: 14px 20px 4px;
                display: block;
            }
            .ao-nav-list {
                display: flex !important;
                flex-direction: column !important;
                width: 100%;
                box-sizing: border-box;
            }
            .ao-nav-item {
                display: flex !important;
                align-items: center;
                gap: 10px;
                padding: 9px 16px;
                margin: 1px 8px;
                border-radius: 8px;
                color: rgba(255,255,255,0.65);
                font-size: 13.5px;
                font-weight: 500;
                cursor: pointer;
                transition: background 0.15s, color 0.15s;
                user-select: none;
                width: calc(100% - 16px);
                box-sizing: border-box;
                flex-shrink: 0;
            }
            .ao-nav-item:hover {
                background: rgba(255,255,255,0.08);
                color: rgba(255,255,255,0.95);
            }
            .ao-nav-item.ao-nav-active {
                background: rgba(25,118,210,0.22);
                color: #90caf9;
            }
            .ao-nav-icon {
                font-size: 18px !important;
                flex-shrink: 0;
                opacity: 0.85;
            }
            .ao-sidebar-avatar {
                width: 32px;
                height: 32px;
                border-radius: 50%;
                background: rgba(100,181,246,0.15);
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 13px;
                font-weight: 700;
                color: #90caf9;
                flex-shrink: 0;
            }
            .ao-user-section {
                border-top: 1px solid rgba(255,255,255,0.07);
                padding: 12px;
                display: flex !important;
                align-items: center;
                gap: 8px;
                width: 100%;
                box-sizing: border-box;
                flex-shrink: 0;
            }

            .nicegui-content {
                padding: 0 !important;
                background: #f0f2f5 !important;
                min-height: 100vh;
            }
            .ao-content-wrap { min-height: 100vh; }
            .ao-content-topbar {
                background: white;
                border-bottom: 1px solid #e8eaf0;
                padding: 16px 24px;
                display: flex;
                align-items: center;
                gap: 14px;
            }
            .ao-obras-badge {
                font-size: 12px;
                font-weight: 700;
                color: #1976d2;
                background: #e8f0fe;
                padding: 3px 12px;
                border-radius: 20px;
                letter-spacing: 0.01em;
            }
            .ao-status-tabs-wrap {
                background: white;
                border-bottom: 1px solid #e8eaf0;
                padding: 0 24px;
            }
            .ao-comunicacoes-actions {
                flex: 1;
                display: flex;
                align-items: center;
                gap: 8px;
                min-width: 0;
            }
            .ao-comunicacoes-body { padding: 20px 24px; }
            @media (max-width: 768px) {
                .ao-comunicacoes-body { padding: 12px; }
                .ao-content-topbar { padding: 12px 16px; flex-wrap: wrap; }
                .ao-status-tabs-wrap { padding: 0 8px; }
            }
        </style>
        ''')

    # ── Sidebar (mesma estrutura da tela de Obras) ────────────────────────────

    def _nav_item(self, icone: str, texto: str, destino: str = None, ativo: bool = False, nova_aba: bool = False):
        classes = 'ao-nav-item ao-nav-active' if ativo else 'ao-nav-item'
        item = ui.element('div').classes(classes)
        if destino and not ativo:
            item.on('click', lambda: ui.navigate.to(destino, new_tab=nova_aba))
        with item:
            ui.html(f'<span class="material-icons ao-nav-icon">{icone}</span>', sanitize=False)
            ui.label(texto)

    def _sidebar(self):
        nome = self.usuario.get('nome', '')
        sobrenome = self.usuario.get('sobrenome', '')
        iniciais = (nome[:1] + sobrenome[:1]).upper() if nome or sobrenome else '?'
        nome_exibicao = f'{nome} {sobrenome}'.strip() or 'Usuário'

        # Mini-header visível apenas em mobile
        with ui.header().classes('items-center ao-mobile-header').style(
            'background: #0f172a; height: 52px; padding: 0 14px; gap: 10px; '
            'flex-wrap: nowrap; box-shadow: 0 2px 8px rgba(0,0,0,0.25);'
        ):
            ui.button(
                icon='menu', on_click=lambda: nav_drawer.toggle()
            ).props('flat round text-color=white').tooltip('Abrir menu')
            ui.label('🏗️ AgendaObras').style(
                'color: white; font-weight: 700; font-size: 18px; flex: 1;'
            )

        with ui.left_drawer(
            fixed=True, top_corner=True, bottom_corner=True
        ).style(
            'background: #0f172a; padding: 0; '
            'display: flex; flex-direction: column; align-items: stretch;'
        ).props('width=240 breakpoint=1024 show-if-above') as nav_drawer:

            with ui.element('div').style(
                'padding: 24px 18px 18px; '
                'border-bottom: 1px solid rgba(255,255,255,0.07);'
                'flex-shrink: 0; width: 100%; box-sizing: border-box;'
            ):
                ui.label('🏗️ AgendaObras').style(
                    'color: white; font-size: 24px; font-weight: 700; '
                    'letter-spacing: -0.03em; line-height: 1.2; display: block;'
                )
                ui.label('Rastreador de Demandas').style(
                    'color: rgba(255,255,255,0.35); font-size: 14px; '
                    'margin-top: 4px; display: block; letter-spacing: 0.01em;'
                )

            with ui.element('div').style(
                'flex: 1; overflow-y: auto; padding: 4px 0; '
                'display: flex; flex-direction: column; width: 100%; box-sizing: border-box;'
            ):
                with ui.element('div').classes('ao-nav-list'):
                    ui.html('<div class="ao-nav-section-title">Menu</div>', sanitize=False)
                    self._nav_item('home', 'Obras', '/')
                    self._nav_item('mail', 'Comunicações', ativo=True)
                    self._nav_item('menu_book', 'Biblioteca', '/biblioteca')
                    self._nav_item('help_outline', 'Manual', URL_MANUAL, nova_aba=True)

            with ui.element('div').classes('ao-user-section'):
                with ui.element('div').classes('ao-sidebar-avatar'):
                    ui.label(iniciais)
                with ui.element('div').style('flex: 1; min-width: 0;'):
                    ui.label(nome_exibicao).style(
                        'color: rgba(255,255,255,0.88); font-size: 13px; font-weight: 500; '
                        'overflow: hidden; text-overflow: ellipsis; white-space: nowrap; '
                        'display: block;'
                    )
                    ui.label(self.usuario.get('email', '')).style(
                        'color: rgba(255,255,255,0.3); font-size: 11px; display: block; '
                        'overflow: hidden; text-overflow: ellipsis; white-space: nowrap;'
                    )
                ui.button(
                    icon='logout',
                    on_click=lambda: ui.navigate.to('/logout')
                ).props('flat round').style(
                    'color: rgba(255,255,255,0.4); flex-shrink: 0;'
                ).tooltip('Sair')

            ui.label(f'AgendaObras v{VERSION} | © {datetime.datetime.now().year}').style(
                'color: rgba(255,255,255,0.18); font-size: 10px; text-align: center; '
                'padding: 8px 0 10px; flex-shrink: 0;'
            )

    # ── Conteúdo ──────────────────────────────────────────────────────────────

    def _body(self):
        owner = self.owner
        with ui.element('div').classes('ao-content-wrap w-full'):
            with ui.element('div').classes('ao-content-topbar'):
                ui.label('Comunicações').style('font-size: 20px; font-weight: 700; color: #1a2332;')
                # Status da conexão e ações são inseridos aqui por render_mail_page.
                topbar = ui.element('div').classes('ao-comunicacoes-actions')

            # Abas Minha conferência / Histórico da equipe, como as abas de status de Obras.
            tabs_slot = ui.element('div').classes('ao-status-tabs-wrap')

            with ui.element('div').classes('ao-comunicacoes-body'):
                try:
                    authorize_user(owner)
                except PermissionError:
                    with ui.column().classes('items-center w-full').style('padding-top: 48px; gap: 12px;'):
                        ui.label('Entre novamente para acessar suas comunicações.').style(
                            'font-size: 15px; color: #6b7280;'
                        )
                        ui.button('Voltar às Obras', on_click=lambda: ui.navigate.to('/')).props(
                            'unelevated color=primary'
                        ).style('border-radius: 8px; font-weight: 600;')
                    return

                def seguro_factory(wid, fontes, tipo='obra'):
                    return SeguroComEmails(SeguroService(CAMINHO_DB, tipo=tipo), int(wid), fontes)

                render_mail_page(
                    get_store(owner),
                    lambda: authorize_user(owner),
                    lambda: available_works(owner),
                    user_email=self.usuario.get('email', ''),
                    owner=owner,
                    shared_store=get_shared_store(),
                    seguro_factory=seguro_factory,
                    topbar=topbar,
                    tabs_slot=tabs_slot,
                )
