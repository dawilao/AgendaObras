"""
Mixin com o componente de Kanban de obras (agrupamento visual por status).
"""

from nicegui import ui
from utils.obras_helper import ObrasHelper, KANBAN_COLUNAS


class ObraKanbanMixin:
    def renderizar_kanban(self, obras_info):
        """Renderiza o board kanban a partir de obras_info pré-computado
        (lista de dicts: obra, checklist, cor, icone, status_texto)."""
        grupos = {chave: [] for chave, *_ in KANBAN_COLUNAS}
        for info in obras_info:
            bucket = ObrasHelper.obter_bucket_kanban(info['status_texto'])
            grupos[bucket].append(info)

        with ui.element('div').classes('ao-kanban-board w-full'):
            for chave, titulo, cor, icone_coluna in KANBAN_COLUNAS:
                itens = grupos[chave]
                with ui.element('div').classes('ao-kanban-column'):
                    with ui.element('div').classes('ao-kanban-column-header').style(
                        f'border-bottom-color: {cor};'
                    ):
                        with ui.row().classes('items-center gap-1'):
                            ui.icon(icone_coluna).style(f'color: {cor}; font-size: 16px;')
                            ui.label(titulo).style('font-size: 13px; font-weight: 700; color: #1a2332;')
                        ui.label(str(len(itens))).classes('ao-kanban-column-count')

                    with ui.element('div').classes('ao-kanban-column-body'):
                        if not itens:
                            ui.label('Nenhuma obra').classes('ao-kanban-column-empty')
                        else:
                            for info in itens:
                                self._criar_card_kanban(info)

    def _criar_card_kanban(self, info):
        obra = info['obra']
        cor = info['cor']
        progresso = self.helper.calcular_progresso(info['checklist'])
        with ui.element('div').classes('ao-kanban-card').style(
            f'border-left: 3px solid {cor};'
        ).on('click', lambda o=obra: self.abrir_detalhes_obra(o['id'])):
            ui.label(obra['nome_contrato']).classes('ao-kanban-card-title')
            ui.label(obra['cliente']).classes('ao-kanban-card-cliente')
            with ui.row().classes('w-full items-center gap-2').style('margin-top: 6px;'):
                ui.linear_progress(progresso / 100, show_value=False).style('height: 6px; flex: 1;')
                ui.label(f'{progresso}%').style(f'font-size: 11px; font-weight: 700; color: {cor};')
            with ui.row().classes('items-center gap-1').style('margin-top: 3px;'):
                ui.icon(info['icone']).style(f'color: {cor}; font-size: 12px;')
                ui.label(info['status_texto']).style(f'font-size: 10px; color: {cor}; font-weight: 600;')
