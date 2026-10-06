"""
Mixin da aba Arquivos do card de obra (CCT, orçamento e aditivos).
Ver e baixar: ADM, Financeiro e coordenador da obra. Enviar, anexar das Comunicações, corrigir e
excluir: Financeiro e coordenador da obra. Permissões conferidas no servidor (services.obra_arquivos).
"""
from pathlib import Path

from nicegui import ui, run

from core.error_logger import log_error
from db.obra_arquivos_repo import ObraArquivosRepository, TIPOS
from services import obra_arquivos as arquivos
from services.financeiro_service import pode_editar_arquivos, pode_ver_financeiro
from ui.components.omie_financeiro import apagar_ao_fechar
from utils.formatters import formatar_data_hora_local as _data_local

ICONES_TIPO = {'cct': 'gavel', 'orcamento': 'request_quote', 'aditivo': 'post_add'}


def _tamanho(n):
    n = n or 0
    if n >= 1024 * 1024:
        return f'{n / 1024 / 1024:.1f} MB'.replace('.', ',')
    return f'{max(1, round(n / 1024))} KB'


class ObraArquivosMixin:

    @property
    def arquivos_repo(self):
        if getattr(self, '_arquivos_repo', None) is None:
            self._arquivos_repo = ObraArquivosRepository(self.db.db_name)
        return self._arquivos_repo

    def _usuario_arquivos(self):
        return getattr(self, '_usuario_fin', None) or self._usuario_omie()

    def pode_ver_arquivos(self, obra):
        return pode_ver_financeiro(self._usuario_arquivos(), obra)

    def renderizar_aba_arquivos(self, obra):
        """Conteúdo da aba Arquivos (montado quando a aba é aberta)."""
        enviar = pode_editar_arquivos(self._usuario_arquivos(), obra)

        @ui.refreshable
        def conteudo():
            try:
                grupos = arquivos.listar(self.arquivos_repo, obra, self._usuario_omie())
            except PermissionError as e:
                ui.label(str(e)).style('font-size: 12px; color: #999;')
                return
            except Exception as e:
                log_error(e, 'obra_arquivos', f"Listar arquivos - obra {obra['id']}")
                ui.label('Arquivos indisponíveis no momento.').style('font-size: 12px; color: #999;')
                return
            if enviar:
                with ui.row().classes('w-full gap-1'):
                    ui.button('Enviar', icon='upload',
                              on_click=lambda: self._dialogo_enviar_arquivo(obra, conteudo.refresh)).props(
                        'flat dense no-caps size=sm color=primary')
                    ui.button('Das Comunicações', icon='mail',
                              on_click=lambda: self._dialogo_anexar_comunicacoes(obra, conteudo.refresh)).props(
                        'flat dense no-caps size=sm color=primary').tooltip(
                        'Anexar um arquivo dos e-mails desta obra no Histórico da equipe')
            for tipo, rotulo in TIPOS.items():
                versoes = grupos[tipo]
                with ui.expansion(f'{rotulo} · {len(versoes)}', icon=ICONES_TIPO[tipo]).classes('w-full').props('dense'):
                    if not versoes:
                        ui.label('Nenhum arquivo enviado.').style('font-size: 12px; color: #999;')
                    for numero, arquivo in zip(range(len(versoes), 0, -1), versoes):
                        self._linha_arquivo(obra, arquivo, numero, conteudo.refresh if enviar else None)
            ui.label('Arquivos a conferir: enviar um aditivo não altera o valor da obra.').style(
                'font-size: 10px; color: #999;')

        conteudo()

    def _linha_arquivo(self, obra, arquivo, numero, ao_alterar=None):
        """ao_alterar (quem pode editar): mostra corrigir e excluir e recarrega a lista depois."""
        with ui.row().classes('w-full items-center no-wrap gap-1').style('border-bottom: 1px solid #f0f0f0;'):
            with ui.column().classes('gap-0').style('flex: 1; min-width: 0;'):
                ui.label(arquivo['nome']).style('font-size: 12px; font-weight: 600; color: #1a2332; overflow: hidden; '
                                                'text-overflow: ellipsis; white-space: nowrap;').tooltip(arquivo['nome'])
                origem = ' · das Comunicações' if arquivo['origem'] == 'comunicacoes' else ''
                ui.label(f"v{numero} · {_data_local(arquivo['enviado_em'])} · {arquivo['enviado_por_nome'] or '—'}"
                         f"{origem} · {_tamanho(arquivo['bytes'])}").style('font-size: 10px; color: #888;')
            ui.badge('A conferir', color='orange').props('outline')
            ui.button(icon='download', on_click=lambda a=arquivo: self._baixar_arquivo(obra, a['id'])).props(
                'flat dense round size=sm').tooltip('Baixar')
            if ao_alterar:
                ui.button(icon='edit', on_click=lambda a=arquivo: self._dialogo_corrigir_arquivo(obra, a, ao_alterar)).props(
                    'flat dense round size=sm').tooltip('Corrigir nome ou tipo')
                ui.button(icon='delete_outline',
                          on_click=lambda a=arquivo: self._dialogo_excluir_arquivo(obra, a, ao_alterar)).props(
                    'flat dense round size=sm color=negative').tooltip('Excluir')

    def _dialogo_corrigir_arquivo(self, obra, arquivo, ao_terminar):
        sufixo = Path(arquivo['nome']).suffix
        with apagar_ao_fechar(ui.dialog()) as dialog, ui.card().style('min-width: min(480px, 92vw);'):
            ui.label('Corrigir arquivo').style('font-size: 18px; font-weight: 700;')
            nome = ui.input('Nome', value=arquivo['nome'][:-len(sufixo)] if sufixo else arquivo['nome']).props(
                f'outlined dense suffix="{sufixo}"').classes('w-full')
            tipo = ui.select(TIPOS, value=arquivo['tipo'], label='Tipo').props('outlined dense').classes('w-full')
            ui.label('O conteúdo não muda; a alteração fica no histórico.').style('font-size: 12px; color: #777;')

            async def salvar():
                try:
                    mudou = await run.io_bound(arquivos.corrigir, self.arquivos_repo, obra, arquivo['id'],
                                               nome.value, tipo.value, self._usuario_omie())
                except (PermissionError, ValueError) as e:
                    ui.notify(str(e), type='warning')
                    return
                if mudou:
                    ui.notify('Arquivo corrigido.', type='positive')
                dialog.close()
                ao_terminar()

            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('Cancelar', on_click=dialog.close).props('flat no-caps')
                ui.button('Salvar', icon='save', on_click=salvar).props('unelevated no-caps')
        dialog.open()

    def _dialogo_excluir_arquivo(self, obra, arquivo, ao_terminar):
        with apagar_ao_fechar(ui.dialog()) as dialog, ui.card():
            ui.label('Excluir este arquivo?').style('font-size: 16px; font-weight: 700;')
            ui.label(f"{arquivo['nome']} ({TIPOS[arquivo['tipo']]})").style('font-size: 13px; color: #555;')
            ui.label('Ele sai da lista da obra. A exclusão fica no histórico; enviar o mesmo arquivo de novo o traz '
                     'de volta.').style('font-size: 12px; color: #777;')

            async def confirmar():
                try:
                    await run.io_bound(arquivos.excluir, self.arquivos_repo, obra, arquivo['id'], self._usuario_omie())
                except (PermissionError, ValueError) as e:
                    ui.notify(str(e), type='warning')
                    return
                ui.notify('Arquivo excluído.', type='positive')
                dialog.close()
                ao_terminar()

            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('Cancelar', on_click=dialog.close).props('flat no-caps')
                ui.button('Excluir', on_click=confirmar).props('unelevated no-caps color=negative')
        dialog.open()

    async def _baixar_arquivo(self, obra, arquivo_id):
        try:
            nome, conteudo = await run.io_bound(arquivos.baixar, self.arquivos_repo, obra, arquivo_id,
                                                self._usuario_omie())
        except (PermissionError, ValueError) as e:
            ui.notify(str(e), type='warning')
            return
        ui.download.content(conteudo, nome, 'application/octet-stream')

    def _dialogo_enviar_arquivo(self, obra, ao_terminar):
        with apagar_ao_fechar(ui.dialog()) as dialog, ui.card().style('min-width: min(480px, 92vw);'):
            ui.label(f"Enviar arquivo · {obra['nome_contrato']}").style('font-size: 18px; font-weight: 700;')
            tipo = ui.select(TIPOS, value='orcamento', label='Tipo').props('outlined dense').classes('w-full')
            ajuda = ui.label('').style('font-size: 12px; color: #777;')

            def atualizar_ajuda():
                aceitos = ', '.join(e.lstrip('.').upper() for e in arquivos.FORMATOS[tipo.value])
                ajuda.set_text(f'Aceitos: {aceitos} · até 20 MB. O arquivo fica "A conferir"; os anteriores são mantidos.')
            tipo.on_value_change(lambda _: atualizar_ajuda())
            atualizar_ajuda()

            async def recebido(e):
                conteudo = await e.file.read()
                try:
                    arquivo = await run.io_bound(arquivos.enviar, self.arquivos_repo, obra, tipo.value, e.file.name,
                                                 conteudo, self._usuario_omie())
                except (PermissionError, ValueError) as erro:
                    ui.notify(str(erro), type='warning')
                    return
                except Exception as erro:
                    log_error(erro, 'obra_arquivos', f"Enviar arquivo - obra {obra['id']}")
                    ui.notify('Não foi possível guardar o arquivo.', type='negative')
                    return
                ui.notify(f"{arquivo['nome']} enviado como {TIPOS[arquivo['tipo']]}.", type='positive')
                dialog.close()
                ao_terminar()

            ui.upload(on_upload=recebido, auto_upload=True, max_files=1, max_file_size=arquivos.LIMITE_BYTES,
                      on_rejected=lambda: ui.notify('Arquivo acima de 20 MB.', type='warning')).props(
                'accept=".pdf,.xlsx,.xls,.csv" flat bordered').classes('w-full')
            with ui.row().classes('w-full justify-end'):
                ui.button('Fechar', on_click=dialog.close).props('flat no-caps')
        dialog.open()

    async def _dialogo_anexar_comunicacoes(self, obra, ao_terminar):
        try:
            anexos = await run.io_bound(arquivos.anexos_comunicacoes, self.arquivos_repo, obra, self._usuario_omie())
        except (PermissionError, ValueError) as e:
            ui.notify(str(e), type='warning')
            return
        except Exception as e:
            log_error(e, 'obra_arquivos', f"Anexos das Comunicações - obra {obra['id']}")
            ui.notify('Não foi possível ler as Comunicações desta obra.', type='warning')
            return
        with apagar_ao_fechar(ui.dialog()) as dialog, ui.card().style(
                'width: min(760px, 96vw); max-height: 90vh; overflow: auto;'):
            ui.label(f"Anexar das Comunicações · {obra['nome_contrato']}").style('font-size: 18px; font-weight: 700;')
            ui.label('Anexos (PDF, planilhas e CSV) dos e-mails vinculados a esta obra no Histórico da equipe. '
                     'Caixas pessoais não aparecem aqui.').style('font-size: 12px; color: #777;')
            tipo = ui.select(TIPOS, value='orcamento', label='Guardar como').props('outlined dense').classes('w-full')
            if not anexos:
                ui.label('Nenhum anexo nos e-mails desta obra.').style('color: #999; padding: 12px 0;')

            async def anexar(anexo):
                try:
                    arquivo = await run.io_bound(arquivos.anexar_de_comunicacoes, self.arquivos_repo, obra,
                                                 tipo.value, anexo['id'], self._usuario_omie())
                except (PermissionError, ValueError) as e:
                    ui.notify(str(e), type='warning')
                    return
                except Exception as e:
                    log_error(e, 'obra_arquivos', f"Anexar das Comunicações - obra {obra['id']}")
                    ui.notify('Não foi possível anexar o arquivo.', type='negative')
                    return
                ui.notify(f"{arquivo['nome']} anexado como {TIPOS[arquivo['tipo']]}.", type='positive')
                dialog.close()
                ao_terminar()

            for anexo in anexos:
                with ui.row().classes('w-full items-center no-wrap gap-2').style(
                        'border-bottom: 1px solid #eee; padding: 4px 0;'):
                    with ui.column().classes('gap-0').style('flex: 1; min-width: 0;'):
                        ui.label(anexo['nome']).style('font-size: 13px; font-weight: 600;')
                        ui.label(f"{anexo['assunto']} · {anexo['data']} · {_tamanho(anexo['bytes'])}").style(
                            'font-size: 11px; color: #888; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;')
                    if anexo['ja_na_obra']:
                        ui.label('Já está na obra').style('font-size: 11px; color: #2e7d32;')
                    else:
                        ui.button('Anexar', icon='attach_file', on_click=lambda a=anexo: anexar(a)).props(
                            'outline dense no-caps size=sm')
            with ui.row().classes('w-full justify-end'):
                ui.button('Fechar', on_click=dialog.close).props('flat no-caps')
        dialog.open()
