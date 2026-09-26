"""Conexão pessoal temporária, conferência privada e publicação por obra."""
import hashlib
import re
from datetime import datetime
from email.utils import parseaddr, parsedate_to_datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo
from nicegui import ui, run
from .imap_reader import IMAPConfig, AuthFailed, sync_mail, FOLDER_LABELS, INBOX_KEY, SENT_KEY, sent_folder
from .parser import MAX_MESSAGE, OVERSIZE_HINT
from .matching import normalized, ics
from .session import register, unregister, disconnect_user, temporary_import
from .publishing import publish_message, publication_fingerprint, team_pending, UNDECIDED
from .conversations import build_conversations, topic_label
from .visual_status import conversation_status, sender_color, readings_color, insurance_color, paint
from .seguro_bridge import FontesSeguro, obra_da_conversa
from .lixeira import TRASH_DAYS

LABELS = {'revisar': 'Para conferir', 'conflito': 'Conflito', 'vinculado': 'Vinculada',
          'tecnico': 'Evento automático', 'ignorado': 'Ignorada'}
# 'todos' esconde avisos automáticos e ignorados; 'todas_auto' mostra tudo.
TEAM_LABEL = 'Já no histórico da equipe'
STATUS_OPTIONS = {'todos': 'Todas as situações', 'todas_auto': 'Todas, com avisos automáticos', **LABELS,
                  'equipe': TEAM_LABEL}
RUN_STATUS = {'concluido': 'concluída', 'parcial': 'parcial', 'falha': 'falhou',
              'interrompido': 'interrompida', 'executando': 'em andamento'}
CONNECTION = {'off': ('Nunca atualizado', 'com-status-off'),
              'sync': ('Atualizando e-mails…', 'com-status-sync'),
              'stop': ('Interrompendo…', 'com-status-stop'),
              'done': ('Atualizado em {when}', 'com-status-done'),
              'failed': ('Falha em {when}', 'com-status-stop')}
SENDER_LEGEND = [('blue', 'CAIXA'), ('green', 'MACH'), ('yellow', 'Outros'), ('gray', 'Não identificado')]
INSURANCE_CHIP = {'green': 'com-chip-green', 'yellow': 'com-chip-yellow', 'red': 'com-chip-red'}


def filter_on_tab_change(tab, current, remembered):
    """Ao trocar de aba: (filtro de Situação, filtro lembrado da Minha conferência).
    O Histórico da equipe abre em 'Vinculada'; a Minha conferência volta ao filtro que tinha."""
    if tab == 'shared':
        return 'vinculado', current
    return remembered, remembered


def display_date(value):
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is not None:
            dt = dt.astimezone(ZoneInfo('America/Sao_Paulo'))
        return dt.strftime('%d/%m/%Y %H:%M')
    except (ValueError, TypeError, OverflowError):
        return value or 'Data não informada'


def display_iso(value):
    """Datas ISO em UTC gravadas pelo MailStore (ex.: início da consulta)."""
    try:
        return datetime.fromisoformat(value).astimezone(ZoneInfo('America/Sao_Paulo')).strftime('%d/%m/%Y %H:%M')
    except (ValueError, TypeError):
        return value or ''


def sender_name(sender):
    name, address = parseaddr(sender or '')
    return name or address or 'Remetente não informado'


def communication_age(messages):
    dates = []
    for message in messages:
        try:
            dt = parsedate_to_datetime(message['sent_date'])
            if dt.tzinfo is None:
                continue
            dates.append(dt.astimezone(ZoneInfo('America/Sao_Paulo')))
        except (ValueError, TypeError, OverflowError):
            continue
    if not dates:
        return 'Última comunicação: data indisponível' if messages else 'Sem comunicação importada'
    days = (datetime.now(ZoneInfo('America/Sao_Paulo')).date() - max(dates).date()).days
    if days < 0:
        return 'Última comunicação: conferir data futura'
    if days == 0:
        return 'Última comunicação hoje'
    if days == 1:
        return 'Última comunicação há 1 dia'
    return f'Última comunicação há {days} dias'


# Tokens visuais do AgendaObras (mesmos da tela de Obras e da Biblioteca).
STYLE = """
<style>
.mail-wrap { max-width: 1280px; margin: 0 auto; width: 100%; }
.mail-body { white-space: pre-wrap; overflow-wrap: anywhere; }
.q-table td { white-space: normal; }
.com-notice-warn {
    background: #fff8e1; color: #8d5800; border-radius: 8px;
    padding: 10px 14px; font-size: 13px; font-weight: 500;
}
.com-dialog-title { font-size: 22px; font-weight: bold; color: #1976d2; }
.com-section-title { font-size: 14px; font-weight: 700; color: #1a2332; }
.com-muted { color: #6b7280; font-size: 13px; }
.com-meta { color: #7a8699; font-size: 12px; }
.com-warn-text { color: #8d5800; font-size: 12px; }
.com-btn { border-radius: 8px !important; font-weight: 600; }

/* Status da conexão (topbar) */
.com-status {
    font-size: 12px; font-weight: 700; padding: 3px 12px; border-radius: 20px;
    display: inline-flex; align-items: center; gap: 6px; white-space: nowrap;
}
.com-status::before { content: ''; width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.com-status-off { color: #7a8699; background: #f0f2f5; }
.com-status-sync { color: #1976d2; background: #e8f0fe; }
.com-status-stop { color: #8d5800; background: #fff8e1; }
.com-status-done { color: #2e7d32; background: #e8f5e9; }

/* Contadores clicáveis */
.com-counters { display: flex; flex-wrap: wrap; gap: 8px; }
.com-counter {
    display: inline-flex; align-items: baseline; gap: 6px; cursor: pointer; user-select: none;
    background: white; border: 1px solid #e8eaf0; border-radius: 20px; padding: 5px 14px;
    font-size: 12px; color: #6b7280; font-weight: 600; transition: border-color .15s, background .15s;
}
.com-counter b { font-size: 15px; color: #1a2332; }
.com-counter:hover { border-color: #c5cae9; }
.com-counter.ativo { background: #e8f0fe; border-color: #1976d2; color: #1565c0; }
.com-counter.ativo b { color: #1565c0; }
.com-counter-alert b { color: #c62828; }

/* Legenda de cores */
.com-legend { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
.com-dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
.com-dot-blue { background: #1976d2; }
.com-dot-green { background: #2e7d32; }
.com-dot-yellow { background: #f9a825; }
.com-dot-gray { background: #9e9e9e; }

/* Pastas por obra */
.com-folder {
    background: white; border-radius: 12px; border: 1px solid #e8eaf0;
    box-shadow: 0 2px 8px rgba(0,0,0,0.05); overflow: hidden;
}
.com-folder-group > .q-expansion-item__container > .q-item { color: #7a8699; font-weight: 600; font-size: 13px; }
.com-folder-icon { color: #1976d2; font-size: 22px; }
.com-folder-title { font-size: 15px; font-weight: 700; color: #1a2332; }
.com-title { font-size: 14px; font-weight: 600; color: #1a2332; }
.com-item-icon { color: #546e7a; font-size: 20px; }
.com-count {
    font-size: 11px; font-weight: 700; color: #1976d2; background: #e8f0fe;
    padding: 2px 10px; border-radius: 20px; white-space: nowrap;
}
.com-chip {
    font-size: 11px; font-weight: 700; padding: 2px 10px; border-radius: 20px;
    white-space: nowrap; background: #f0f2f5; color: #546e7a;
}
.com-chip-green { background: #e8f5e9; color: #1b5e20; }
.com-chip-yellow { background: #fff8e1; color: #8d5800; }
.com-chip-red { background: #ffebee; color: #b71c1c; }
.com-excerpt {
    background: #f8f9fb; border-left: 3px solid #c5cae9; border-radius: 6px;
    padding: 10px 12px; font-size: 13px; color: #374151;
}
.com-table { border-radius: 12px; border: 1px solid #e8eaf0; }
.com-empty {
    background: white; border: 1px dashed #d5d9e2; border-radius: 12px;
    padding: 40px 16px; text-align: center; color: #7a8699;
}
.com-help h4 { font-size: 14px; font-weight: 700; color: #1a2332; margin: 14px 0 4px; }
.com-help p, .com-help li { font-size: 13px; color: #4b5563; line-height: 1.5; margin: 0 0 4px; }
.com-help ul { padding-left: 18px; margin: 0; }

/* Toggle de visualização, igual ao Grade/Kanban da tela de Obras */
.ao-view-toggle {
    display: flex; align-items: center; background: #f0f2f5;
    border-radius: 8px; padding: 3px; gap: 2px; flex-shrink: 0;
}
.ao-view-toggle-btn {
    min-width: 34px !important; padding: 4px 10px !important; border-radius: 6px !important;
    color: #7a8699 !important; background: transparent !important; box-shadow: none !important;
}
.ao-view-toggle-btn.ao-view-toggle-btn-active {
    background: white !important; color: #1976d2 !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.12) !important;
}
</style>
"""

HELP_HTML = """
<div class="com-help">
<h4>Privacidade</h4>
<ul>
<li>Sua caixa é privada. Só as mensagens que você confirmar são publicadas para a equipe da obra.</li>
<li>A senha não é salva. A conexão existe só durante a atualização; o histórico publicado continua disponível.</li>
</ul>
<h4>Minha conferência × Histórico da equipe</h4>
<ul>
<li><b>Minha conferência</b> é a sua fila privada: vincular identifica a obra; publicar libera a mensagem para a equipe.</li>
<li><b>Histórico da equipe</b> mostra as mensagens já publicadas nas obras às quais você tem acesso.</li>
<li>Confirmar uma mensagem publica somente ela e seus anexos, não a conversa inteira.</li>
</ul>
<h4>Como ler a lista</h4>
<ul>
<li>Abra a obra → o assunto → as mensagens ou os anexos.</li>
<li>O tema é sugerido pelo assunto/conteúdo; a situação é sugerida pelo último e-mail, sem alterar o processo.</li>
<li>Datas são as do e-mail. "Última comunicação" considera os e-mails que aparecem no filtro atual.</li>
<li>A cor indica o último remetente: azul = CAIXA, verde = MACH, amarelo = outros, cinza = não identificado. <b>A cor não indica aprovação.</b></li>
</ul>
<h4>Lixeira da equipe</h4>
<ul>
<li>Administradores podem excluir um arquivo de uma conversa do Histórico da equipe. Ele sai do histórico e das caixas pessoais que têm os mesmos e-mails.</li>
<li>O arquivo fica na Lixeira por 15 dias, podendo ser restaurado; depois é excluído definitivamente e sai do servidor se nenhum outro e-mail usar o mesmo conteúdo.</li>
<li>Arquivos registrados como apólice ou boleto no controle de seguro não podem ser excluídos.</li>
</ul>
<h4>Seguros</h4>
<ul>
<li>A leitura percorre assinatura de contrato, projetos e todos os demais assuntos da obra, usando todas as mensagens publicadas e autorizadas, independentemente do filtro da lista.</li>
<li>As mensagens permanecem nas conversas originais; cada evidência mostra onde foi encontrada.</li>
<li>Seguro-garantia contratual e seguro da obra têm apólices, boletos, rodadas e validações independentes. Mensagens ambíguas podem aparecer nos dois controles para conferência.</li>
<li>Nenhum seguro é aprovado automaticamente: os OKs finais são sempre humanos.</li>
</ul>
</div>
"""


def render_mail_page(store, authorize, available_works=None, demo=False, user_email='', owner=None,
                     shared_store=None, local_pilot=False, seguro_factory=None, topbar=None, tabs_slot=None,
                     trash=None, is_admin=None, protected_files=None, user_name=''):
    """topbar/tabs_slot: containers da moldura da página onde entram o status da conexão,
    as ações e as abas. Sem eles, tudo é criado no próprio conteúdo.
    trash/is_admin/protected_files: lixeira da equipe (só admins), consultados a cada operação."""
    # authorize é chamado novamente em cada operação: uma aba antiga não mantém privilégios.
    authorize()
    active_event = None
    client = ui.context.client
    def allowed_ids():
        authorize()
        return {str(w['id']) for w in available_works()} if available_works else {w['id'] for w in store.works()}
    def work_name(wid):
        names = {str(w['id']): w['name'] for w in (available_works() if available_works else store.works())}
        return names.get(str(wid), f'obra {wid}').split(' / ')[0]
    def disconnected():
        if active_event:
            active_event.set()
    client.on_disconnect(disconnected)
    ui.add_head_html(STYLE)

    def set_connection(state):
        text, css = CONNECTION[state]
        status_chip.set_text(text)
        status_chip.classes(replace=f'com-status {css}')

    def show_last_run():
        """Fora de uma atualização não há conexão aberta: mostra o resultado da última."""
        last = store.last_run()
        if not last:
            set_connection('off')
            return
        # 'executando' fora de uma atualização ativa = consulta que não terminou (ex.: programa fechado).
        state = 'failed' if last['status'] in ('falha', 'executando') else 'done'
        text, css = CONNECTION[state]
        status_chip.set_text(text.format(when=display_iso(last['finished'] or last['started'])))
        status_chip.classes(replace=f'com-status {css}')

    def help_dialog():
        with ui.dialog() as dialog, ui.card().classes('responsive-dialog').style('padding: 20px; max-height: 90vh; overflow-y: auto;'):
            with ui.row().classes('w-full items-center justify-between'):
                ui.label('Como funciona').classes('com-dialog-title')
                ui.button(icon='close', on_click=dialog.close).props('flat dense round').style('color: #666;')
            ui.html(HELP_HTML, sanitize=False)
        dialog.open()

    def show_after_sync():
        """Após a atualização: 'Para conferir' se houver pendências; senão, todas as mensagens."""
        rows = store.conversation_rows()
        team = team_pending(rows, shared_store, allowed_ids())
        target = 'revisar' if any(r['status'] == 'revisar' and r['id'] not in team for r in rows) else 'todos'
        if view.value == 'private' and status_filter.value == target:
            content.refresh()
            return
        # Cada troca de valor já dispara content.refresh pelo on_change.
        view.set_value('private')
        status_filter.set_value(target)

    def folder_options(email):
        """Caixa de entrada e Enviados pelo significado + pastas reais lembradas desta caixa."""
        options = dict(FOLDER_LABELS)
        remembered = store.folders((email or '').strip())
        sent = sent_folder(remembered)
        for name, flags in remembered:
            if name.upper() != 'INBOX' and name != sent and '\\noselect' not in {f.lower() for f in flags}:
                options[name] = name
        return options

    def connect_dialog():
        authorize()
        with ui.dialog() as dialog, ui.card().classes('responsive-dialog-sm').style('padding: 20px;'):
            ui.label('Conectar meu e-mail').classes('com-dialog-title')
            ui.label('KingHost • conexão criptografada • somente leitura • a senha não é salva').classes('com-muted')
            email_input = ui.input('Seu e-mail', value=user_email).classes('w-full').props('outlined dense')
            password_input = ui.input('Senha do e-mail', password=True, password_toggle_button=True).classes('w-full').props('outlined dense autocomplete=off')
            auth_error = ui.label('').classes('com-warn-text')
            auth_error.set_visibility(False)
            since = ui.input('Mensagens recebidas desde', value='2026-01-01').props('type=date outlined dense').classes('w-full')
            folders = ui.select(folder_options(email_input.value), multiple=True, value=[INBOX_KEY, SENT_KEY], with_input=True,
                                label='Pastas a consultar').classes('w-full').props('outlined dense use-chips')
            def update_folders():
                options = folder_options(email_input.value)
                folders.set_options(options, value=[v for v in (folders.value or []) if v in options])
            email_input.on_value_change(update_folders)
            ui.label('Os nomes reais das pastas são identificados ao conectar.').classes('com-meta')
            ui.label('A busca usa os nomes e ICs de Identificação das obras.').classes('com-meta')
            if demo:
                ui.label('Demonstração: não digite sua senha aqui. A conexão real está desativada.').classes('com-warn-text')
                password_input.disable()
            async def submit():
                nonlocal active_event
                authorize()
                if demo or active_event is not None:
                    return
                auth_error.set_visibility(False)
                actor = authorize()
                eligible = allowed_ids()
                # Obras ainda não identificadas entram com o nome como termo de busca,
                # sem IC confirmado: as mensagens chegam "Para conferir", nunca vinculadas
                # automaticamente. O IC pode ser confirmado depois em Identificação das obras.
                if available_works:
                    known = {w['id'] for w in store.works()}
                    for work in available_works():
                        name = (work['name'] or '').strip()
                        if work['id'] not in known and name:
                            store.save_work(work['id'], name, '', [name.split(' / ')[0].strip()], False, actor)
                if not (email_input.value or '').strip() or not password_input.value:
                    ui.notify('Informe o e-mail e a senha.', type='warning')
                    return
                if not folders.value:
                    ui.notify('Selecione ao menos uma pasta para consultar.', type='warning')
                    return
                terms = set()
                for work in store.works():
                    if work['id'] not in eligible:
                        continue
                    if work['ic']:
                        terms.add(work['ic'].split('/')[0])
                    for alias in work['aliases']:
                        # A busca IMAP só aceita ASCII: pesquisa a grafia sem acento e,
                        # quando há acento, também o prefixo até ele (TUBARÃO → TUBAR),
                        # que encontra assuntos escritos com ou sem acento.
                        term = normalized(alias).strip()
                        if term and term.isascii():
                            terms.add(term)
                        prefix = re.split(r'[^\x00-\x7f]', alias.strip().upper(), maxsplit=1)[0].strip()
                        if len(prefix) >= 4 and prefix != term:
                            terms.add(prefix)
                if not terms:
                    ui.notify('Nenhuma obra disponível para pesquisar. Cadastre nomes ou IC em Identificação das obras.', type='warning')
                    return
                cfg = IMAPConfig('imap.kinghost.net', (email_input.value or '').strip(),
                                 password_input.value or '', list(folders.value or []), sorted(terms), since.value)
                password_input.value = ''
                try:
                    cfg.validate()
                except ValueError as exc:
                    cfg.password = ''
                    ui.notify(str(exc), type='warning')
                    return
                dialog.close()
                event = register(owner)
                active_event = event
                sync_button.disable()
                stop_button.set_visibility(True)
                set_connection('sync')
                try:
                    result = await run.io_bound(temporary_import, store, cfg, event)
                    authorize()
                    ui.notify(result, type='positive', timeout=8000)
                except AuthFailed:
                    # Reabre a janela com e-mail, pastas e período mantidos; só a senha em branco.
                    auth_error.set_text('O servidor recusou o acesso. Confira o e-mail e digite a senha novamente.')
                    auth_error.set_visibility(True)
                    dialog.open()
                    password_input.run_method('focus')
                except RuntimeError as exc:
                    # sync_mail só levanta textos próprios, sem dados do servidor.
                    ui.notify(f'Atualização não concluída: {exc}', type='warning', timeout=10000)
                except Exception:
                    ui.notify('Atualização não concluída. Confira o acesso e o histórico da consulta.', type='warning')
                finally:
                    cfg.password = ''
                    unregister(owner, event)
                    active_event = None
                    sync_button.enable()
                    stop_button.set_visibility(False)
                    show_last_run()
                    show_after_sync()
            dialog.on('hide', lambda: password_input.set_value(''))
            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('Cancelar', on_click=dialog.close).props('flat no-caps')
                submit_button = ui.button('Conectar e atualizar', on_click=submit).props('unelevated color=primary no-caps').classes('com-btn')
                if demo:
                    submit_button.disable()
        dialog.open()

    def stop():
        authorize()
        disconnect_user(owner)
        set_connection('stop')
        ui.notify('Interrompendo… aguardando a operação de rede em andamento (até 30 s).', type='info')

    async def upload_eml(event):
        actor = authorize()
        if not event.file.name.lower().endswith('.eml'):
            ui.notify('Selecione um arquivo .eml.', type='warning')
            return
        raw = await event.file.read()
        try:
            await run.io_bound(store.import_message, raw,
                               ('arquivo-local', 'eml', '1', hashlib.sha256(raw).hexdigest()), actor)
            authorize()
            ui.notify('Mensagem importada para conferência.', type='positive')
            content.refresh()
        except ValueError as exc:
            ui.notify(str(exc), type='warning')

    def eml_dialog():
        authorize()
        with ui.dialog() as dialog, ui.card().classes('responsive-dialog-sm').style('padding: 20px;'):
            ui.label('Importar arquivo .eml').classes('com-dialog-title')
            limit_mb = MAX_MESSAGE // 1024 // 1024
            ui.label(f'A mensagem entra na sua conferência privada. Limite de {limit_mb} MB por arquivo.').classes('com-muted')
            ui.upload(on_upload=upload_eml, auto_upload=True, multiple=True, max_file_size=MAX_MESSAGE,
                      on_rejected=lambda: ui.notify(f'Arquivo acima de {limit_mb} MB ou formato inválido. {OVERSIZE_HINT}',
                                                    type='warning', multi_line=True)).props('accept=.eml flat bordered').classes('w-full')
            with ui.row().classes('w-full justify-end'):
                ui.button('Fechar', on_click=dialog.close).props('flat no-caps')
        dialog.open()

    def mappings():
        actor = authorize()
        existing = {w['id']: w for w in store.works()}
        choices = available_works() if available_works else [{'id': w['id'], 'name': w['name']} for w in existing.values()]
        with ui.dialog() as dialog, ui.card().classes('responsive-dialog').style('padding: 20px;'):
            ui.label('Identificação das obras').classes('com-dialog-title')
            ui.label('Confirme o IC por documento ou comunicado contratual. O ano nunca é descartado.').classes('com-muted')
            options = {str(w['id']): w['name'] for w in choices}
            selected = ui.select(options, label='Obra do AgendaObras').classes('w-full').props('outlined dense')
            ic = ui.input('IC / ano', placeholder='03738/2026').classes('w-full').props('outlined dense')
            aliases = ui.input('Nomes no assunto, separados por ponto e vírgula').classes('w-full').props('outlined dense')
            confirmed = ui.checkbox('Conferi o IC desta obra; permitir vínculo automático')
            def choose(event):
                w = existing.get(event.value, {})
                ic.value = w.get('ic', '')
                aliases.value = '; '.join(w.get('aliases', [options.get(event.value, '')]))
                confirmed.value = bool(w.get('confirmed', False))
            selected.on_value_change(choose)
            def save():
                actor = authorize()
                try:
                    if selected.value not in options:
                        raise ValueError('Selecione uma obra.')
                    store.save_work(selected.value, options[selected.value], ic.value or '',
                                    [a.strip() for a in (aliases.value or '').split(';') if a.strip()],
                                    confirmed.value, actor)
                    store.reprocess(actor)
                    dialog.close()
                    work_filter.options = {'todos': 'Todas as obras', **{w['id']: w['name'] for w in store.works()}}
                    work_filter.update()
                    content.refresh()
                except ValueError as exc:
                    ui.notify(str(exc), type='warning')
            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('Cancelar', on_click=dialog.close).props('flat no-caps')
                ui.button('Salvar identificação', on_click=save).props('unelevated color=primary no-caps').classes('com-btn')
        dialog.open()

    # ── Topbar: status da conexão e ações ────────────────────────────────────
    with (topbar or ui.row().classes('w-full items-center gap-3')):
        status_chip = ui.label().tooltip('A senha não é salva. A conexão com o e-mail existe só durante a atualização.')
        show_last_run()
        ui.space()
        ui.button(icon='info_outline', on_click=help_dialog).props('flat round dense').style('color: #7a8699;').tooltip('Como funciona')
        stop_button = ui.button('Interromper', icon='link_off', on_click=stop).props('outline no-caps color=negative').classes('com-btn')
        stop_button.set_visibility(False)
        sync_button = ui.button('Conectar e-mail', icon='mail', on_click=connect_dialog).props('unelevated color=primary no-caps').classes('com-btn')
        with ui.button(icon='more_vert').props('flat round dense').style('color: #7a8699;').tooltip('Mais ações'):
            with ui.menu():
                ui.menu_item('Identificação das obras', on_click=mappings)
                ui.menu_item('Importar arquivo .eml', on_click=eml_dialog)
                ui.menu_item('Atualizar lista', on_click=lambda: content.refresh())

    # ── Abas: fila privada × histórico publicado ─────────────────────────────
    private_filter = SimpleNamespace(value='todos')
    def switch_tab():
        target, private_filter.value = filter_on_tab_change(view.value, status_filter.value, private_filter.value)
        if 'trash' in view_buttons:
            view_buttons['trash'].set_visibility(view.value == 'shared' and can_trash())
        if status_filter.value == target:
            content.refresh()
        else:
            status_filter.set_value(target)  # O on_change do filtro já refresca a lista.

    with (tabs_slot or ui.element('div')):
        view = ui.tabs(value='private', on_change=switch_tab).props(
            'dense no-caps align=left active-color=primary indicator-color=primary')
        with view:
            ui.tab(name='private', label='Minha conferência')
            if shared_store is not None:
                ui.tab(name='shared', label='Histórico da equipe')

    with ui.column().classes('mail-wrap gap-4'):
        if demo:
            ui.label('VERSÃO DE TESTES • mensagens fictícias • sem conexão com a caixa real').classes('com-notice-warn w-full')
        elif local_pilot:
            ui.label('PILOTO LOCAL • e-mails reais • histórico salvo somente neste ambiente de testes').classes('com-notice-warn w-full')

        # ── Filtros em uma linha + seletor de visualização ───────────────────
        presentation = SimpleNamespace(value='conversations')
        view_buttons = {}
        def mark_presentation(mode):
            presentation.value = mode
            for key, button in view_buttons.items():
                if key == mode:
                    button.classes(add='ao-view-toggle-btn-active')
                else:
                    button.classes(remove='ao-view-toggle-btn-active')
        def set_presentation(mode):
            mark_presentation(mode)
            content.refresh()

        with ui.row().classes('w-full items-center gap-3'):
            status_filter = ui.select(STATUS_OPTIONS, value='todos', label='Situação',
                                      on_change=lambda: content.refresh()).classes('w-56').props('outlined dense bg-color=white')
            filter_works = available_works() if available_works else store.works()
            work_filter = ui.select({'todos': 'Todas as obras', **{str(w['id']): w['name'] for w in filter_works}},
                                    value='todos', label='Obra', on_change=lambda: content.refresh()
                                    ).classes('w-64').props('outlined dense bg-color=white')
            search = ui.input(placeholder='Pesquisar assunto ou remetente', on_change=lambda: content.refresh()
                              ).classes('flex-1').props('outlined dense clearable bg-color=white').style('min-width: 200px;')
            with search.add_slot('prepend'):
                ui.icon('search').style('color: #9e9e9e;')
            modes = [('conversations', 'forum', 'Conversas por obra'), ('attachments', 'attach_file', 'Anexos'),
                     ('all', 'list', 'Todos os e-mails')]
            if trash is not None:
                modes.append(('trash', 'delete_outline', 'Lixeira da equipe'))
            with ui.element('div').classes('ao-view-toggle'):
                for mode, icon, tip in modes:
                    view_buttons[mode] = ui.button(icon=icon, on_click=lambda m=mode: set_presentation(m)
                                                   ).props('flat dense').classes('ao-view-toggle-btn').tooltip(tip)
            view_buttons['conversations'].classes(add='ao-view-toggle-btn-active')
            if 'trash' in view_buttons:
                view_buttons['trash'].set_visibility(False)  # Aparece no Histórico da equipe, para admins.

    # ── Lixeira da equipe (somente admins, no Histórico da equipe) ───────────
    rights = SimpleNamespace(trash=False)
    def can_trash():
        return trash is not None and shared_store is not None and is_admin is not None and is_admin()

    def trash_guard():
        actor = authorize()
        if not can_trash():
            raise PermissionError('Só administradores gerenciam a lixeira da equipe.')
        return actor

    def confirm_trash(file, on_sent=None):
        """on_sent: tira o arquivo só da parte da tela onde ele aparece. Sem ele, a lista é refeita
        (e as pastas abertas se fecham)."""
        with ui.dialog() as dialog, ui.card().classes('responsive-dialog-sm').style('padding: 20px;'):
            ui.label('Enviar arquivo para a lixeira?').classes('com-dialog-title')
            ui.label(' / '.join(file['names'])).classes('com-title')
            ui.label(f'O arquivo sai desta conversa no Histórico da equipe e das caixas pessoais que têm os mesmos '
                     f'e-mails. Ele pode ser restaurado na Lixeira por {TRASH_DAYS} dias; depois é excluído '
                     'definitivamente.').classes('com-meta').style('white-space: normal;')
            async def send():
                try:
                    actor = trash_guard()
                    source, *_ = shared_store.detail(file['origins'][0]['mid'])
                    if source['obra_id'] not in allowed_ids():
                        raise PermissionError('Obra não autorizada.')
                    protected = protected_files() if protected_files else frozenset()
                    # Percorre as caixas pessoais: fora da thread da interface, para não travar a tela.
                    await run.io_bound(trash.send, [o['mid'] for o in file['origins']], file['sha256'],
                                       actor, user_name, protected)
                except (ValueError, PermissionError) as exc:
                    ui.notify(str(exc), type='warning')
                    return
                dialog.close()
                ui.notify(f'Arquivo enviado para a lixeira. Pode ser restaurado por {TRASH_DAYS} dias.', type='positive')
                if on_sent:
                    on_sent()
                else:
                    content.refresh()
            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('Cancelar', on_click=dialog.close).props('flat no-caps')
                ui.button('Enviar para a lixeira', icon='delete', on_click=send).props('unelevated no-caps color=negative')
        dialog.open()

    def trash_item_guard(item):
        actor = trash_guard()
        if trash.item(item['id'])['obra_id'] not in allowed_ids():
            raise PermissionError('Obra não autorizada.')
        return actor

    async def restore_item(item):
        try:
            actor = trash_item_guard(item)
            await run.io_bound(trash.restore, item['id'], actor)
        except (ValueError, PermissionError) as exc:
            ui.notify(str(exc), type='warning')
        else:
            ui.notify('Arquivo restaurado no histórico e nas caixas pessoais.', type='positive')
        content.refresh()

    def confirm_purge(item):
        with ui.dialog() as dialog, ui.card().classes('responsive-dialog-sm').style('padding: 20px;'):
            ui.label('Excluir definitivamente?').classes('com-dialog-title')
            ui.label(' / '.join(item['names'])).classes('com-title')
            ui.label('Não será possível restaurar. O arquivo sai do servidor assim que nenhum outro e-mail '
                     'usar o mesmo conteúdo.').classes('com-meta').style('white-space: normal;')
            async def purge():
                try:
                    actor = trash_item_guard(item)
                    await run.io_bound(trash.purge, item['id'], actor)
                except (ValueError, PermissionError) as exc:
                    ui.notify(str(exc), type='warning')
                else:
                    ui.notify('Arquivo excluído definitivamente.', type='positive')
                dialog.close()
                content.refresh()
            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('Cancelar', on_click=dialog.close).props('flat no-caps')
                ui.button('Excluir definitivamente', icon='delete_forever', on_click=purge
                          ).props('unelevated no-caps color=negative')
        dialog.open()

    def render_trash():
        permitted = allowed_ids()
        items = [i for i in trash.items() if i['obra_id'] in permitted]
        ui.label(f'Lixeira da equipe • os arquivos são excluídos definitivamente {TRASH_DAYS} dias depois '
                 'de enviados.').classes('com-meta')
        if not items:
            ui.label('A lixeira está vazia.').classes('com-muted')
            return
        for item in items:
            with ui.row().classes('w-full items-center gap-2 border-t').style('padding: 8px 4px;'):
                with ui.column().classes('gap-0 flex-1').style('min-width: 0;'):
                    ui.label(' / '.join(item['names'])).classes('com-title ellipsis')
                    ui.label(f"{work_name(item['obra_id'])} • {item['subject'] or '(Sem assunto)'}").classes('com-meta ellipsis')
                    left = ('exclusão definitiva hoje' if not item['days_left'] else
                            f"{item['days_left']} dia(s) para a exclusão definitiva")
                    ui.label(f"{(item['size'] or 0) / 1024:.1f} KB • enviado por "
                             f"{item['deleted_by_name'] or item['deleted_by']} em {display_iso(item['deleted_at'])} • {left}"
                             ).classes('com-meta')
                ui.button('Restaurar', icon='restore', on_click=lambda i=item: restore_item(i)).props('outline dense no-caps')
                ui.button('Excluir definitivamente', icon='delete_forever', on_click=lambda i=item: confirm_purge(i)
                          ).props('flat dense no-caps color=negative')

    def conversation_details(group, repository, shared):
        authorize()
        with ui.dialog() as dialog, ui.card().classes('responsive-dialog-lg').style('padding: 20px; max-height: 90vh; overflow-y: auto;'):
            ui.label(group['subject']).classes('com-dialog-title')
            summary = ui.label().classes('com-meta')
            def show_summary():
                summary.set_text(f"{group['message_count']} e-mails • {len(group['files'])} arquivos distintos • {group['group_reason']}")
            show_summary()
            changed = SimpleNamespace(value=False)
            # A tabela de anexos por trás do diálogo só é refeita ao fechá-lo.
            dialog.on('hide', lambda: content.refresh() if changed.value else None)
            ui.label('Última mensagem').classes('com-section-title')
            ui.label(group['excerpt'] or 'Abra o e-mail para consultar o conteúdo.').classes('mail-body com-excerpt w-full')
            ui.button('Abrir última mensagem / conferir obra', on_click=lambda: details(group['id'], shared)).props('unelevated color=primary no-caps').classes('com-btn')
            if group['files']:
                ui.label('Anexos de toda a conversa').classes('com-section-title mt-2')
                for file in group['files']:
                    with ui.column().classes('w-full gap-1').style('border: 1px solid #e8eaf0; border-radius: 8px; padding: 10px 12px;') as card:
                        ui.label(' / '.join(file['names'])).classes('com-title')
                        ui.label(f"{file['size'] / 1024:.1f} KB • {len(file['origins'])} ocorrência(s)").classes('com-meta')
                        def download_file(f=file):
                            authorize()
                            if shared:
                                origin, *_ = repository.detail(f['origins'][0]['mid'])
                                if origin['obra_id'] not in allowed_ids():
                                    raise PermissionError('Obra não autorizada.')
                            send_attachment(repository, f['id'])
                        with ui.row().classes('gap-1'):
                            ui.button('Baixar', icon='download', on_click=download_file).props('outline dense no-caps')
                            if shared and rights.trash:
                                def trashed(f=file, c=card):
                                    c.delete()
                                    group['files'].remove(f)
                                    changed.value = True
                                    show_summary()
                                ui.button('Enviar para a lixeira', icon='delete',
                                          on_click=lambda f=file, done=trashed: confirm_trash(f, done)
                                          ).props('flat dense no-caps color=negative')
                            for origin in file['origins']:
                                ui.button(f"Origem: {display_date(origin['date'])}",
                                          on_click=lambda mid=origin['mid']: details(mid, shared)).props('flat dense no-caps')
            with ui.expansion('Mensagens anteriores e conteúdo completo').classes('w-full'):
                for message in group['messages']:
                    ui.button(f"{display_date(message['sent_date'])} — {sender_name(message['sender'])} — {message['subject']}",
                              on_click=lambda mid=message['id']: details(mid, shared)).props('flat no-caps').classes('w-full')
            with ui.row().classes('w-full justify-end'):
                ui.button('Fechar', on_click=dialog.close).props('flat no-caps')
        dialog.open()

    def send_attachment(repository, aid):
        try:
            a = repository.attachment(aid)
        except ValueError as exc:
            ui.notify(str(exc), type='warning')
            return
        ui.download.content(a['payload'], a['name'], 'application/octet-stream')

    def render_skipped():
        """E-mails não importados (acima do limite ou inválidos), em destaque no topo da lista."""
        skipped = store.skipped()
        if not skipped:
            return
        with ui.expansion(f'E-mails não importados ({len(skipped)})', icon='report_problem',
                          value=True).classes('w-full com-folder com-notice-warn'):
            ui.label(f'Não foram importados para o app. {OVERSIZE_HINT}').classes('com-meta').style('padding: 0 16px 6px;')
            for item in skipped:
                with ui.column().classes('w-full gap-0 border-t').style('padding: 6px 16px;'):
                    if item['subject'] or item['sender']:
                        size = f" • {item['size'] / 1024 / 1024:.1f} MB" if item['size'] else ''
                        ui.label(item['subject'] or '(Sem assunto)').classes('com-title')
                        ui.label(f"{sender_name(item['sender'] or '')} • {display_date(item['sent_date'])}{size}").classes('com-meta')
                    else:
                        ui.label(f"{item['folder']} • UID {item['uid']}").classes('com-title')
                    ui.label(item['note']).classes('com-meta')

    def confirm_team_links(mids):
        """Confirma na caixa pessoal o mesmo vínculo já publicado pela equipe (sem nova cópia)."""
        actor = authorize()
        try:
            for mid in mids:
                # Recalculado no clique: a tela pode estar aberta há tempo.
                msg, _, _, _ = store.detail(mid)
                wid = shared_store.published_works().get(publication_fingerprint(msg, store.fingerprint_attachments(mid)))
                if msg['status'] not in UNDECIDED or not wid or wid not in allowed_ids():
                    raise ValueError('Esta mensagem não está mais pendente de vínculo com a equipe. Atualize a lista.')
                store.review(mid, wid, actor, 'Vínculo confirmado pelo histórico da equipe.')
                # Registra na auditoria o registro compartilhado correspondente; não cria cópia.
                publish_message(store, shared_store, mid, actor, allowed_ids())
            store.reprocess(actor)
        except ValueError as exc:
            ui.notify(str(exc), type='warning')
            content.refresh()
            return False
        ui.notify('Vínculo confirmado. A mensagem já estava no histórico da equipe.', type='positive')
        content.refresh()
        return True

    def details(mid, shared=False):
        authorize()
        repository = shared_store if shared else store
        msg, attachments, audit, sources = repository.detail(mid)
        if shared and msg['obra_id'] not in allowed_ids():
            raise PermissionError('Obra não autorizada.')
        with ui.dialog() as dialog, ui.card().classes('responsive-dialog-lg').style('padding: 20px; max-height: 90vh; overflow-y: auto;'):
            ui.label(msg['subject'] or '(Sem assunto)').classes('com-dialog-title')
            ui.label(f"De: {msg['sender']} • {display_date(msg['sent_date'])}").classes('com-muted')
            ui.label(f"Para: {msg['recipients']}" + (f" • Cc: {msg['cc']}" if msg['cc'] else '')).classes('com-meta')
            if msg['reason']:
                ui.label(msg['reason']).classes('com-notice-warn w-full')
            with ui.expansion('Conteúdo da mensagem', value=True).classes('w-full'):
                ui.label(msg['body'] or '(Sem corpo de texto)').classes('mail-body text-sm')
            if attachments:
                ui.label('Anexos').classes('com-section-title')
                with ui.row().classes('gap-2'):
                    for attachment in attachments:
                        def download(aid=attachment['id']):
                            authorize()
                            if shared and msg['obra_id'] not in allowed_ids():
                                raise PermissionError('Obra não autorizada.')
                            send_attachment(repository, aid)
                        size_label = f"{attachment['size']} bytes" if attachment['size'] < 1024 else f"{attachment['size'] / 1024:.1f} KB"
                        ui.button(f"{attachment['name']} ({size_label})", icon='download', on_click=download).props('outline dense no-caps')
            permitted = allowed_ids()
            options = {w['id']: w['name'] for w in store.works() if w['id'] in permitted}
            team_work = None
            if not shared and shared_store is not None and msg['status'] in UNDECIDED:
                published = shared_store.published_works().get(publication_fingerprint(msg, store.fingerprint_attachments(mid)))
                team_work = published if published in permitted else None
            if team_work:
                ui.label(f'{TEAM_LABEL}, vinculada à obra {work_name(team_work)}. '
                         'Confirme o mesmo vínculo na sua caixa ou escolha outra decisão abaixo.'
                         ).classes('com-chip com-chip-green w-full').style('white-space: normal; padding: 8px 12px;')
            candidate = msg['obra_id'] or msg['suggestion']
            target = ui.select(options, value=candidate if candidate in options else None, label='Vincular à obra').classes('w-full').props('outlined dense')
            note = ui.input('Motivo da decisão').classes('w-full').props('outlined dense')
            if shared:
                target.set_visibility(False)
                note.set_visibility(False)
            else:
                ui.label('Ao publicar, o corpo completo e os anexos desta mensagem ficam visíveis à equipe com acesso à obra.').classes('com-warn-text')
            def decide(ignore=False):
                actor = authorize()
                try:
                    if not ignore and (not target.value or target.value not in allowed_ids()):
                        raise ValueError('Selecione a obra.')
                    store.review(mid, None if ignore else target.value, actor, note.value or '')
                    if not ignore and shared_store:
                        _, fresh = publish_message(store, shared_store, mid, actor, allowed_ids())
                        ui.notify('Informação nova publicada na obra.' if fresh else 'Esta mensagem já está no histórico. Nenhuma cópia foi acrescentada.', type='positive')
                    store.reprocess(actor)
                    dialog.close()
                    content.refresh()
                except ValueError as exc:
                    ui.notify(str(exc), type='warning')
            def confirm_team():
                if confirm_team_links([mid]):
                    dialog.close()
            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('Fechar', on_click=dialog.close).props('flat no-caps')
                if team_work:
                    ui.button('Confirmar vínculo da equipe', icon='group', on_click=confirm_team
                              ).props('unelevated color=positive no-caps').classes('com-btn')
                if not shared:
                    ui.button('Ignorar na minha fila', on_click=lambda: decide(True)).props('outline no-caps').classes('com-btn')
                    ui.button('Confirmar e publicar na obra', on_click=lambda: decide(False)).props('unelevated color=primary no-caps').classes('com-btn')
            with ui.expansion('Origem e histórico de decisões').classes('w-full'):
                for source in sources:
                    ui.label(f"{source['mailbox']} / {source['folder']} • UID {source['uid']} • validade {source['validity']}").classes('text-xs')
                for entry in audit:
                    ui.label(f"{entry['at']} • {entry['actor']} • {entry['action']}: {entry['details']}").classes('text-xs mail-body')
        dialog.open()

    def expansion_header(expansion):
        """Cabeçalho próprio da expansão: linha com título e detalhes em segundo plano."""
        slot = expansion.add_slot('header')
        with slot:
            return ui.row().classes('w-full items-center no-wrap gap-3').style('min-width: 0;')

    def render_conversation(g, wid, repository, shared):
        icon, _, situation = conversation_status(g)
        with ui.expansion().classes('w-full border-t') as conversation_folder:
            with expansion_header(conversation_folder):
                ui.icon(icon).classes('com-item-icon')
                with ui.column().classes('gap-0 flex-1').style('min-width: 0;'):
                    ui.label(topic_label(g['subject'], g.get('body', ''))).classes('com-title ellipsis')
                    ui.label(f"{situation} · {display_date(g['sent_date'])} · {sender_name(g['sender'])}").classes('com-meta ellipsis')
                team_ids = {m['team_obra'] for m in g['messages'] if m.get('team_obra')}
                if team_ids:
                    ui.label('Na equipe').classes('com-chip com-chip-green').tooltip(
                        f"{TEAM_LABEL} · {', '.join(work_name(w) for w in sorted(team_ids))}")
                ui.label(f"{g['message_count']} e-mail{'s' if g['message_count'] != 1 else ''}").classes('com-count')
                files_badge = files_count = None
                if g['files']:
                    with ui.row().classes('items-center no-wrap gap-0 com-meta') as files_badge:
                        ui.icon('attach_file').style('font-size: 15px;')
                        files_count = ui.label(str(len(g['files'])))
            paint(conversation_folder, sender_color(g.get('sender', '')))
            with ui.column().classes('w-full gap-2').style('padding: 12px 16px;'):
                ui.label(f"Assunto original: {g['subject']}").classes('com-meta')
                if team_ids:
                    with ui.row().classes('w-full items-center gap-2'):
                        ui.label(f"{TEAM_LABEL} · {', '.join(work_name(w) for w in sorted(team_ids))}"
                                 ).classes('com-chip com-chip-green')
                        team_mids = [m['id'] for m in g['messages'] if m.get('team_obra')]
                        ui.button('Confirmar vínculo da equipe', icon='group',
                                  on_click=lambda mids=team_mids: confirm_team_links(mids)
                                  ).props('unelevated dense color=positive no-caps').classes('com-btn')
                elif any(r['obra_id'] != wid for r in g['messages']):
                    ui.label('Vínculo com a obra a conferir').classes('com-chip com-chip-yellow')
                ui.label(g['excerpt'] or 'Abra a mensagem abaixo para ler o conteúdo.').classes('mail-body com-excerpt w-full')
                with ui.expansion(f"Mensagens e respostas ({g['message_count']})", icon='mail').classes('w-full'):
                    for m in g['messages']:
                        with ui.expansion(f"{display_date(m['sent_date'])} — {sender_name(m['sender'])}",
                                          caption=m['subject'], icon='chat_bubble_outline').classes('w-full border-t') as message_folder:
                            paint(message_folder, sender_color(m.get('sender', '')))
                            ui.label(m['body'] or '(Sem corpo de texto)').classes('mail-body p-2 text-sm')
                            ui.button('Conferir vínculo / ver detalhes', on_click=lambda mid=m['id']: details(mid, shared)).props('flat no-caps')
                if g['files']:
                    with ui.expansion(f"Anexos da conversa ({len(g['files'])})", icon='attach_file').classes('w-full') as files_panel:
                        def trashed(file, row):
                            """Tira só esta linha: pastas e conversas abertas continuam como estão."""
                            row.delete()
                            g['files'].remove(file)
                            if g['files']:
                                files_count.set_text(str(len(g['files'])))
                                files_panel.set_text(f"Anexos da conversa ({len(g['files'])})")
                            else:
                                files_badge.delete()
                                files_panel.delete()
                        for f in g['files']:
                            with ui.row().classes('w-full items-center gap-2 border-t').style('padding: 8px 4px;') as file_row:
                                with ui.column().classes('gap-0 flex-1').style('min-width: 0;'):
                                    ui.label(' / '.join(f['names'])).classes('com-title ellipsis')
                                    ui.label(f"{f['size'] / 1024:.1f} KB • {len(f['origins'])} ocorrência(s)").classes('com-meta')
                                def download_tree(file=f):
                                    authorize()
                                    if shared:
                                        source, *_ = repository.detail(file['origins'][0]['mid'])
                                        if source['obra_id'] not in allowed_ids():
                                            raise PermissionError('Obra não autorizada.')
                                    send_attachment(repository, file['id'])
                                ui.button(icon='download', on_click=download_tree).props('flat round dense color=primary').tooltip('Baixar arquivo')
                                ui.button(icon='mail_outline', on_click=lambda mid=f['origins'][0]['mid']: details(mid, shared)
                                          ).props('flat round dense').style('color: #7a8699;').tooltip('Abrir e-mail de origem')
                                if shared and rights.trash:
                                    ui.button(icon='delete_outline',
                                              on_click=lambda file=f, row=file_row: confirm_trash(file, lambda: trashed(file, row))
                                              ).props('flat round dense').style('color: #c62828;').tooltip('Enviar para a lixeira')

    def render_insurance(wid, conversations, repository, shared):
        from ui.components.seguro_panel import render_seguro, titulo_seguro
        from db.seguro_repo import TIPOS_SEGURO
        def guard_work(work_id=wid):
            authorize()
            if work_id not in allowed_ids():
                raise PermissionError('Obra não autorizada.')
        sources = FontesSeguro(store if local_pilot else shared_store, wid, guard_work,
                               f'piloto:{owner}' if local_pilot else 'shared', suggested=local_pilot)
        insurance_groups = [g for g in conversations if topic_label(g['subject']) == 'Seguro e garantia']
        def contact(items):
            latest = max(items, key=lambda r: r['timestamp'], default=None)
            if not latest:
                return 'nenhum e-mail identificado'
            return f"{len(items)} e-mail{'s' if len(items) != 1 else ''} · último contato {display_date(latest['source']['date'])}"
        with ui.expansion().classes('w-full border-t') as seguro_folder:
            with expansion_header(seguro_folder):
                ui.icon('verified_user').classes('com-item-icon')
                ui.label('Seguros').classes('com-title')
                with ui.row().classes('items-center gap-2 flex-1').style('min-width: 0;'):
                    overview_chips = {tipo: ui.label('Consultando…').classes('com-chip') for tipo in TIPOS_SEGURO}
                overview_contact = ui.label('').classes('com-meta gt-xs')
            if local_pilot:
                ui.label('Teste local. As decisões ficam neste piloto; não são validações oficiais.').classes('com-warn-text').style('padding: 8px 16px 0;')
            summaries = {}
            for tipo, nome in TIPOS_SEGURO.items():
                with ui.expansion().classes('w-full border-t') as type_folder:
                    with expansion_header(type_folder):
                        ui.icon('policy').classes('com-item-icon')
                        with ui.column().classes('gap-0 flex-1').style('min-width: 0;'):
                            ui.label(nome).classes('com-title ellipsis')
                            type_contact = ui.label('').classes('com-meta')
                        type_chip = ui.label('Consultando…').classes('com-chip')
                        with type_chip:
                            type_tip = ui.tooltip('')
                    def update_title(state, folder=type_folder, key=tipo, chip=type_chip, tip=type_tip, contact_label=type_contact):
                        readings = state.get('leituras', []) if state else []
                        summaries[key] = readings
                        title = titulo_seguro(state) if state else 'Situação indisponível'
                        short = title.split(' · ')[0]
                        css = INSURANCE_CHIP.get(insurance_color(state, title), '')
                        paint(folder, readings_color(readings))
                        chip.set_text(short)
                        chip.classes(replace=f'com-chip {css}')
                        tip.set_text(title)
                        contact_label.set_text(contact(readings))
                        prefix = 'Garantia' if key == 'garantia' else 'Obra'
                        overview_chips[key].set_text(f'{prefix}: {short}')
                        overview_chips[key].classes(replace=f'com-chip {css}')
                        unique = list({r['fingerprint']: r for entries in summaries.values() for r in entries}.values())
                        overview_contact.set_text(contact(unique))
                        paint(seguro_folder, readings_color(unique))
                    render_seguro(seguro_factory(wid, sources, tipo), wid, on_state=update_title)
            if insurance_groups:
                ui.label('Conversas classificadas como seguro').classes('com-section-title').style('padding: 12px 16px 4px;')
                for g in insurance_groups:
                    render_conversation(g, wid, repository, shared)

    def render_section(wid, name, conversations, repository, shared):
        total = sum(g['message_count'] for g in conversations)
        age = communication_age([m for g in conversations for m in g['messages']])
        with ui.expansion().classes('w-full com-folder') as section:
            with expansion_header(section):
                ui.icon('help_outline' if wid == 'pending' else 'folder').classes('com-folder-icon')
                ui.label(name).classes('com-folder-title ellipsis')
                if conversations:
                    ui.label(f"{len(conversations)} assunto{'s' if len(conversations) != 1 else ''}").classes('com-count')
                    ui.label(f"{total} e-mail{'s' if total != 1 else ''}").classes('com-count gt-xs')
                ui.space()
                ui.label(age).classes('com-meta gt-xs')

        # Conteúdo montado só na primeira abertura da pasta: com todas as obras
        # montadas de uma vez (seguros incluídos) a tela levava segundos para abrir.
        filled = False
        def fill(_=None):
            nonlocal filled
            if not section.value or filled:
                return
            filled = True
            with section:
                if seguro_factory and wid != 'pending':
                    render_insurance(wid, conversations, repository, shared)
                for g in conversations:
                    if not seguro_factory or topic_label(g['subject']) != 'Seguro e garantia':
                        render_conversation(g, wid, repository, shared)
                if not conversations:
                    ui.label('Nenhuma conversa neste filtro.').classes('com-muted').style('padding: 12px 16px;')
        section.on_value_change(fill)

    with ui.column().classes('mail-wrap gap-3').style('margin-top: 16px;'):
        @ui.refreshable
        def content():
            authorize()
            shared = view.value == 'shared' and shared_store is not None
            rights.trash = shared and can_trash()
            if presentation.value == 'trash':
                if rights.trash:
                    render_trash()
                    return
                mark_presentation('conversations')  # Saiu do histórico ou perdeu o perfil de admin.
            repository = shared_store if shared else store
            permitted = allowed_ids() if shared else None
            show_automatic = status_filter.value == 'todas_auto'
            all_rows = [r for r in repository.messages() if not shared or r['obra_id'] in permitted]
            rows = repository.conversation_rows(permitted)
            # Na caixa pessoal: mensagens sem decisão que a equipe já publicou (só obras permitidas).
            team = {} if shared else team_pending(rows, shared_store, allowed_ids())
            for row in rows:
                row['team_obra'] = team.get(row['id'])
            counts = {s: sum(r['status'] == s and r['id'] not in team for r in all_rows) for s in LABELS}

            # ── Contadores (clicar filtra a lista) ──
            with ui.element('div').classes('com-counters'):
                counters = [('todos', 'mensagens', len(all_rows)), ('vinculado', 'vinculadas', counts['vinculado']),
                            ('revisar', 'para conferir', counts['revisar']), ('conflito', 'conflitos', counts['conflito'])]
                if team:
                    counters.append(('equipe', 'já na equipe', len(team)))
                for key, label, number in counters:
                    css = 'com-counter'
                    if status_filter.value == key:
                        css += ' ativo'
                    if key in ('revisar', 'conflito') and number:
                        css += ' com-counter-alert'
                    with ui.element('div').classes(css).on('click', lambda k=key: status_filter.set_value(k)):
                        ui.html(f'<b>{number}</b>', sanitize=False)
                        ui.label(label)

            groups = build_conversations(rows)
            term = (search.value or '').casefold()
            def status_matches(row):
                if status_filter.value in ('todos', 'todas_auto'):
                    return True
                if status_filter.value == 'equipe':
                    return bool(row.get('team_obra'))
                return row['status'] == status_filter.value and not row.get('team_obra')
            def matches(row):
                return (status_matches(row)
                        and (work_filter.value == 'todos' or work_filter.value in (row['obra_id'], row['suggestion']))
                        and term in (row['subject'] + ' ' + row['sender']).casefold())
            hidden = sum(g['message_count'] for g in groups if g['status'] in ('tecnico', 'ignorado'))
            groups = [g for g in groups if any(matches(r) for r in g['messages'])
                      and (show_automatic or status_filter.value in ('tecnico', 'ignorado')
                           or g['status'] not in ('tecnico', 'ignorado'))]

            # ── Linha de resumo: última consulta, totais e legenda ──
            with ui.row().classes('w-full items-center gap-x-4 gap-y-1'):
                last = store.last_run()
                if last:
                    run_text = f"Última consulta {display_iso(last['started'])} · {RUN_STATUS.get(last['status'], last['status'])}"
                    if last['status'] == 'falha' and last['detail']:
                        ui.label(f"{run_text}: {last['detail']}").classes('com-warn-text')
                    else:
                        consulta = ui.label(run_text).classes('com-meta')
                        if last['detail']:
                            consulta.tooltip(last['detail'])
                else:
                    ui.label('Nenhuma consulta ao e-mail ainda').classes('com-meta')
                ui.label(f"{sum(g['message_count'] for g in groups)} e-mails em {len(groups)} conversas").classes('com-meta')
                if hidden and not show_automatic and status_filter.value not in ('tecnico', 'ignorado'):
                    ui.label(f'{hidden} avisos automáticos ocultos').classes('com-meta cursor-pointer').style(
                        'text-decoration: underline;').on('click', lambda: status_filter.set_value('todas_auto'))
                ui.space()
                if presentation.value == 'conversations':
                    with ui.element('div').classes('com-legend').tooltip('Cor pelo último remetente. A cor não indica aprovação.'):
                        for color, label in SENDER_LEGEND:
                            with ui.row().classes('items-center gap-1 no-wrap'):
                                ui.element('span').classes(f'com-dot com-dot-{color}')
                                ui.label(label).classes('com-meta')

            render_skipped()

            if presentation.value == 'attachments':
                group_map = {g['id']: g for g in groups}
                file_rows = [{'id': f"{g['id']}-{f['id']}", 'group_id': g['id'],
                              'name': ' / '.join(f['names']), 'subject': g['subject'],
                              'work_name': g['work_name'] or 'A conferir',
                              'occurrences': len(f['origins']), 'size': f"{f['size'] / 1024:.1f} KB"}
                             for g in groups for f in g['files']]
                columns = [{'name': k, 'field': k, 'label': v, 'align': 'left'} for k, v in
                           [('name', 'Arquivo'), ('subject', 'Conversa'), ('work_name', 'Obra'),
                            ('occurrences', 'Ocorrências'), ('size', 'Tamanho')]]
                table = ui.table(columns=columns, rows=file_rows, row_key='id', pagination=15).classes('w-full com-table cursor-pointer').props('flat')
                table.on('rowClick', lambda event: conversation_details(group_map[event.args[1]['group_id']], repository, shared))
                if not file_rows:
                    ui.label('Nenhum anexo neste filtro.').classes('com-muted')
            elif presentation.value == 'all':
                rows = [dict(r) for g in groups for r in g['messages'] if matches(r)]
                for row in rows:
                    row['status_label'] = TEAM_LABEL if row.get('team_obra') else LABELS[row['status']]
                    row['work_name'] = row['work_name'] or 'A conferir'
                    row['sent_date'] = display_date(row['sent_date'])
                    row['attachment_count'] = len(row['attachments'])
                columns = [{'name': key, 'label': label, 'field': key, 'align': 'left', 'sortable': key != 'sent_date'}
                           for key, label in [('subject', 'Assunto'), ('work_name', 'Obra'),
                                              ('status_label', 'Situação'), ('sent_date', 'Data do e-mail'),
                                              ('attachment_count', 'Anexos')]]
                safe_rows = [{k: r[k] for k in ('id', 'subject', 'work_name', 'status_label', 'sent_date', 'attachment_count')} for r in rows]
                table = ui.table(columns=columns, rows=safe_rows, row_key='id', pagination=15).classes('w-full com-table cursor-pointer').props('flat')
                table.on('rowClick', lambda event: details(event.args[1]['id'], shared))
                if not rows:
                    ui.label('Nenhuma mensagem neste filtro.').classes('com-muted')
            else:
                works = available_works() if available_works else store.works()
                known = {w['id']: w for w in store.works()}
                buckets = {str(w['id']): [] for w in works}
                pending = []
                for g in groups:
                    candidate = obra_da_conversa(g, list(known.values()))
                    if candidate in buckets:
                        buckets[candidate].append(g)
                    else:
                        pending.append(g)
                sections = [(str(w['id']), w['name'].split(' / ')[0], buckets[str(w['id'])]) for w in works]
                sections.sort(key=lambda s: normalized(s[1]))
                if pending:
                    sections.insert(0, ('pending', 'Obra a conferir', pending))
                if work_filter.value != 'todos':
                    for wid, name, conversations in sections:
                        if wid == work_filter.value:
                            render_section(wid, name, conversations, repository, shared)
                else:
                    active = [s for s in sections if s[2]]
                    empty = [s for s in sections if not s[2]]
                    for wid, name, conversations in active:
                        render_section(wid, name, conversations, repository, shared)
                    if not active:
                        with ui.element('div').classes('com-empty w-full'):
                            ui.icon('mark_email_unread').style('font-size: 40px; color: #c5cae9;')
                            ui.label('Nenhuma conversa neste filtro').classes('com-section-title').style('margin-top: 8px;')
                            ui.label('Conecte seu e-mail ou importe um .eml pelo menu ⋮ no topo.').classes('com-muted')
                    if empty:
                        with ui.expansion(f'Obras sem comunicação ({len(empty)})', icon='folder_open').classes('w-full com-folder-group'):
                            with ui.column().classes('w-full gap-3'):
                                for wid, name, conversations in empty:
                                    render_section(wid, name, conversations, repository, shared)
        content()
