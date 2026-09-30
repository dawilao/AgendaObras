"""Conexão pessoal temporária, conferência privada e publicação por obra."""
import os
import hashlib
import re
import time
from datetime import datetime
from email.utils import parseaddr, parsedate_to_datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo
from nicegui import ui, run
from .imap_reader import IMAPConfig, AuthFailed, sync_mail, FOLDER_LABELS, INBOX_KEY, SENT_KEY, sent_folder
from .parser import MAX_MESSAGE, OVERSIZE_HINT
from .matching import normalized, ics
from .session import register, unregister, disconnect_user, temporary_import
from .publishing import (publish_message, publication_fingerprint, team_pending, UNDECIDED, publish_identified,
                         adopt_team_links)
from .refino_dia3 import work_codes
from .store import PROTECTED_DOMAINS
from .conversations import build_conversations, topic_label, timestamp
from .visual_status import conversation_status, sender_color, readings_color, insurance_color, paint
from .seguro_bridge import FontesSeguro, obra_da_conversa
from .lixeira import TRASH_DAYS
from .encaixe import (encaixar, contadores, categoria, sender_address, avisos_por_obra, cor_uf, TOPIC_ICONS, SITUACAO,
                      SITUACAO_A_CONFERIR)
from utils.obras_helper import GRADE_TABS

LABELS = {'revisar': 'Para conferir', 'conflito': 'Conflito', 'vinculado': 'Vinculada',
          'tecnico': 'Evento automático', 'ignorado': 'Ignorada', 'spam': 'Provável spam'}
# Caixa pessoal: Provável spam e Lixeira ficam fora das pastas das obras
# (salvo em "Todas, com avisos automáticos").
SEPARATED = ('spam', 'trash')
SENDER_BORDER = {'blue': '#1976d2', 'green': '#2e7d32', 'yellow': '#f9a825', 'gray': '#9e9e9e'}
# 'todos' esconde avisos automáticos e ignorados; 'todas_auto' mostra tudo.
TEAM_LABEL = 'Já no histórico da equipe'
# Histórico da equipe: situações gravadas nas mensagens publicadas.
STATUS_OPTIONS = {'todos': 'Todas as situações', 'todas_auto': 'Todas, com avisos automáticos',
                  **{k: v for k, v in LABELS.items() if k != 'spam'}, 'equipe': TEAM_LABEL}
# Meu e-mail: um único filtro; os contadores são atalhos para estas mesmas opções.
# Vinculada = confirmada pelo OK do coordenador; Pré-vinculada = na pasta da obra, aguardando o OK.
CATEGORY_LABELS = {'confirmed': 'Vinculada', 'placed': 'Pré-vinculada', 'unassigned': 'Sem obra definida',
                   'spam': 'Provável spam', 'trash': 'Na lixeira'}
PRIVATE_OPTIONS = {'todos': 'Todas as situações', 'mine': 'Aguardando meu OK', 'confirmed': 'Vinculadas', 'placed': 'Pré-vinculadas',
                   'unassigned': 'Sem obra definida', 'conflito': 'Conflitos', 'equipe': TEAM_LABEL,
                   'spam': 'Provável spam', 'trash': 'Lixeira', 'tecnico': 'Eventos automáticos',
                   'todas_auto': 'Todas, com avisos automáticos'}
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
    """Ao trocar de aba: (filtro de Situação, filtro lembrado da Meu e-mail).
    O Histórico da equipe abre em 'Vinculada'; a Meu e-mail volta ao filtro que tinha."""
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
/* Pasta-mãe: pastinha na cor da UF com a sigla por cima */
.com-uf { position: relative; width: 38px; height: 34px; flex-shrink: 0; }
.com-uf .q-icon { font-size: 38px; }
.com-uf-label {
    position: absolute; left: 0; right: 0; top: 13px; text-align: center;
    font-size: 11px; font-weight: 800; color: white; letter-spacing: .02em;
}
.com-uf-label.com-uf-long { font-size: 8px; top: 15px; }
.com-ok-btn { border-radius: 8px !important; padding: 0 8px !important; min-height: 34px; }
.com-ok-btn .com-ok-main { font-size: 17px; font-weight: 800; line-height: 1; }
.com-ok-btn .com-ok-sub { font-size: 9px; line-height: 1.1; font-weight: 600; }
.com-mail-card {
    background: white; border: 1px solid #e8eaf0; border-left-width: 3px;
    border-radius: 8px; padding: 8px 12px; min-width: 0;
}
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
<li>Sua caixa é privada. No modo automático, mensagens com obra identificada com segurança são compartilhadas. Casos duvidosos exigem conferência; no modo manual, cada mensagem exige confirmação.</li>
<li>A senha não é salva. A conexão existe só durante a atualização; o histórico publicado continua disponível.</li>
</ul>
<h4>Meu e-mail × Histórico da equipe</h4>
<ul>
<li><b>Meu e-mail</b> mantém suas mensagens, inclusive as já compartilhadas. O filtro Para conferir mostra as pendências.</li>
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
<h4>Pré-vínculo e OK do coordenador</h4>
<ul>
<li>Em <b>Meu e-mail</b>, cada mensagem vai primeiro para a pasta provável da obra, pelo IC, número do contrato e pela conversa. Cidade igual não basta: obras da mesma cidade com ICs diferentes ficam separadas.</li>
<li><b>Pré-vinculada</b> = e-mail na pasta da obra aguardando conferência. Passa a <b>Vinculada</b> só com o <b>OK do coordenador</b> (cinza → verde), que também publica a mensagem no Histórico da equipe.</li>
<li>O OK pode ser dado pelo coordenador da obra ou por um administrador. Se a obra estiver errada, use <b>Realocar obra</b> ou envie à lixeira.</li>
<li>Confirmar o vínculo não aprova apólice, boleto nem etapa da obra.</li>
<li>Os contadores e o campo Situação são o mesmo filtro: clicar num contador seleciona a situação; clicar de novo volta a mostrar todas.</li>
<li>O <b>OK da conversa</b> confirma de uma vez as mensagens pré-vinculadas àquela obra; mensagens encaixadas em outra obra não são tocadas.</li>
<li><b>Aguardando meu OK</b> mostra só as obras em que você confirma o vínculo, com as pastas já abertas. Depois de cada OK, a tela segue para o próximo pendente.</li>
<li>Quando outro coordenador já confirmou o mesmo e-mail, ele entra como Vinculada na sua caixa automaticamente.</li>
<li><b>Realocar obra</b> pode ensinar o sistema: marque "Usar para identificar esta obra" para gravar o nome (e o IC do assunto) em Identificação das obras.</li>
</ul>
<h4>Provável spam e Lixeira pessoal</h4>
<ul>
<li>Mensagens sem relação com obras ou processos da CAIXA ficam em <b>Provável spam</b>, fora das pastas das obras.</li>
<li>A Lixeira pessoal é recuperável. Nenhum e-mail é apagado da caixa original (KingHost).</li>
<li><b>Não é spam</b> / <b>Restaurar</b> devolvem o e-mail à identificação automática: ele não volta ao spam e se encaixa sozinho quando a obra for identificada.</li>
<li><b>Sempre spam deste remetente</b> manda os próximos e-mails desse endereço para Provável spam (nunca CAIXA ou MACH, e nunca um e-mail com IC da obra). As regras podem ser removidas na própria lista.</li>
</ul>
<h4>Situação das obras</h4>
<ul>
<li>Todos / Em Andamento / Atrasado / Concluído seguem o cadastro da aba Obras; a situação não é deduzida dos e-mails. Os contadores consideram todo o acervo.</li>
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
                     trash=None, is_admin=None, protected_files=None, user_name='',
                     works_meta=None, confirmable=None):
    """topbar/tabs_slot: containers da moldura da página onde entram o status da conexão,
    as ações e as abas. Sem eles, tudo é criado no próprio conteúdo.
    trash/is_admin/protected_files: lixeira da equipe (só admins), consultados a cada operação.
    works_meta: {id da obra: ic, uf, contrato, status_texto, bucket} do cadastro de Obras.
    confirmable(): obras em que o usuário dá o OK do coordenador; sem ele, o OK fica só para leitura."""
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

    automatic_sharing = os.environ.get('AGENDA_MAIL_AUTO_PUBLISH', '0') == '1'

    def share_identified():
        if not automatic_sharing or shared_store is None:
            return
        actor = authorize()
        result = publish_identified(store, shared_store, actor, allowed_ids())
        ui.notify(f"{result['new']} mensagens novas na equipe; {result['pending']} conflitos de publicação.", type='info')

    def show_after_sync():
        # A atualização não troca a aba nem o filtro escolhido pelo usuário.
        content.refresh()

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
            ui.label('Atualizar meu e-mail').classes('com-dialog-title')
            ui.label('Uma conexão para as duas abas. O histórico da equipe não tem uma conexão separada.').classes('com-muted')
            if automatic_sharing:
                ui.label('Obra identificada com segurança: mensagem e anexos compartilhados automaticamente com a equipe autorizada. Casos duvidosos ficam para conferir.').classes('com-warn-text')
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
                try:
                    event = register(owner)
                except RuntimeError as exc:
                    cfg.password = ''
                    ui.notify(str(exc), type='warning')
                    return
                active_event = event
                sync_button.disable()
                stop_button.set_visibility(True)
                set_connection('sync')
                try:
                    result = await run.io_bound(temporary_import, store, cfg, event)
                    authorize()
                    share_identified()
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
                    await adopt_from_team()
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
            share_identified()
            ui.notify('Mensagem importada. Confira a situação na lista.', type='positive')
            content.refresh()
        except ValueError as exc:
            ui.notify(str(exc), type='warning')

    def eml_dialog():
        authorize()
        with ui.dialog() as dialog, ui.card().classes('responsive-dialog-sm').style('padding: 20px;'):
            ui.label('Importar arquivo .eml').classes('com-dialog-title')
            limit_mb = MAX_MESSAGE // 1024 // 1024
            ui.label(f'Identificação segura compartilha com a equipe no modo automático; dúvidas ficam para conferir. Limite de {limit_mb} MB por arquivo.').classes('com-muted')
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
                    share_identified()
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
        ui.label('Conexão única • Meu e-mail e Histórico da equipe').classes('com-meta')
        ui.space()
        ui.button(icon='info_outline', on_click=help_dialog).props('flat round dense').style('color: #7a8699;').tooltip('Como funciona')
        stop_button = ui.button('Interromper', icon='link_off', on_click=stop).props('outline no-caps color=negative').classes('com-btn')
        stop_button.set_visibility(False)
        sync_button = ui.button('Atualizar meu e-mail', icon='mail', on_click=connect_dialog).props('unelevated color=primary no-caps').classes('com-btn')
        with ui.button(icon='more_vert').props('flat round dense').style('color: #7a8699;').tooltip('Mais ações'):
            with ui.menu():
                ui.menu_item('Identificação das obras', on_click=mappings)
                ui.menu_item('Importar arquivo .eml', on_click=eml_dialog)
                ui.menu_item('Atualizar lista', on_click=lambda: full_refresh())

    # ── Abas: fila privada × histórico publicado ─────────────────────────────
    private_filter = SimpleNamespace(value='todos')
    def switch_tab():
        target, private_filter.value = filter_on_tab_change(view.value, status_filter.value, private_filter.value)
        if 'trash' in view_buttons:
            view_buttons['trash'].set_visibility(view.value == 'shared' and can_trash())
        # Cada aba tem suas situações: Meu e-mail usa as do pré-vínculo; o Histórico, as publicadas.
        options = STATUS_OPTIONS if view.value == 'shared' else PRIVATE_OPTIONS
        target = target if target in options else 'todos'
        changed = status_filter.value != target
        status_filter.set_options(options, value=target)  # Valor novo: o on_change já refresca a lista.
        if not changed:
            content.refresh()

    with (tabs_slot or ui.element('div')):
        view = ui.tabs(value='private', on_change=switch_tab).props(
            'dense no-caps align=left active-color=primary indicator-color=primary')
        with view:
            ui.tab(name='private', label='Meu e-mail')
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
            status_filter = ui.select(PRIVATE_OPTIONS, value='todos', label='Situação',
                                      on_change=lambda: content.refresh()).classes('w-56').props('outlined dense bg-color=white')
            filter_works = available_works() if available_works else store.works()
            work_filter = ui.select({'todos': 'Todas as obras', **{str(w['id']): w['name'] for w in filter_works}},
                                    value='todos', label='Obra', on_change=lambda: content.refresh()
                                    ).classes('w-64').props('outlined dense bg-color=white')
            search = ui.input(placeholder='Pesquisar assunto, remetente, conteúdo ou anexo', on_change=lambda: content.refresh()
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

        # ── Situação das obras, como as abas da tela de Obras ────────────────
        situation = SimpleNamespace(value='todos')
        if works_meta is not None:
            with ui.column().classes('w-full gap-0'):
                situation = ui.tabs(value='todos', on_change=lambda: content.refresh()).props(
                    'dense no-caps align=left active-color=primary indicator-color=primary')
                with situation:
                    for code, label in GRADE_TABS:
                        ui.tab(name=code, label=label)
                ui.label('Situação do cadastro de Obras. Os contadores consideram todo o acervo.').classes('com-meta')

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

    def skipped_item(item):
        with ui.column().classes('w-full gap-0 border-t').style('padding: 6px 16px;'):
            if item['subject'] or item['sender']:
                size = f" • {item['size'] / 1024 / 1024:.1f} MB" if item['size'] else ''
                ui.label(item['subject'] or '(Sem assunto)').classes('com-title')
                ui.label(f"{sender_name(item['sender'] or '')} • {display_date(item['sent_date'])}{size}").classes('com-meta')
            else:
                ui.label(f"{item['folder']} • UID {item['uid']}").classes('com-title')
            ui.label(item['note']).classes('com-meta')

    def render_skipped(skipped):
        """E-mails não importados (acima do limite ou inválidos) sem obra identificada, no topo da lista.
        Os que têm obra identificável aparecem dentro da pasta da obra."""
        if not skipped:
            return
        with ui.expansion(f'E-mails não importados ({len(skipped)})', icon='report_problem',
                          value=True).classes('w-full com-folder com-notice-warn'):
            ui.label(f'Não foram importados para o app. {OVERSIZE_HINT}').classes('com-meta').style('padding: 0 16px 6px;')
            for item in skipped:
                skipped_item(item)

    def render_folder_notices(items):
        with ui.column().classes('w-full gap-0 com-notice-warn').style('padding: 8px 0; border-radius: 0;'):
            ui.label(f'⚠ E-mails desta obra não importados ({len(items)}) · conteúdo e anexos ainda não analisados. '
                     'Este aviso não confirma etapa nem aprovação.').classes('com-warn-text').style('padding: 0 16px 4px;')
            for item in items:
                skipped_item(item)

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
            share_identified()
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
            if not shared and shared_store is not None:
                shared_wid = shared_store.published_works().get(publication_fingerprint(msg, store.fingerprint_attachments(mid)))
                if shared_wid in permitted:
                    ui.label('Já disponível à equipe • a mensagem continua no seu e-mail.').classes('com-chip com-chip-green')
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
                    share_identified()
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

    # ── Pré-vínculo por obra (Meu e-mail): OK do coordenador, realocar, spam, lixeira ──
    # matches: pré-vínculo calculado na última montagem da lista.
    # confirmable: obras em que o usuário dá o OK (lido uma vez por montagem; relido no clique).
    # totals: números dos contadores que não vêm do pré-vínculo (mensagens, conflitos, equipe).
    # key/meta/meta_at: caches para trocar de filtro sem reclassificar tudo nem reler as obras.
    # busy: mensagens com OK em gravação (ignora o segundo clique).
    # ok_buttons: {mensagem: [botão OK visível]} para pintar de verde no lugar, sem refazer a lista.
    # ok_order: botões OK na ordem da tela, para "Próximo pendente".
    # auto_open: fila "Aguardando meu OK" abre pastas e conversas; auto_budget limita quantas pastas
    # abrem de uma vez (cada uma monta Seguros) e sections guarda as demais para "Próximo pendente".
    placement = SimpleNamespace(matches={}, confirmable=None, totals={}, key=None, meta=None, meta_at=0.0,
                                busy=set(), ok_buttons={}, ok_order=[], auto_open=False, auto_budget=0,
                                sections=[], spam_senders=[])
    OK_NOTE = 'OK do coordenador: vínculo confirmado.'
    AUTO_OPEN_LIMIT = 3

    def alive():
        """A página ainda existe? Aba fechada durante uma gravação: nada de aviso nem refresh."""
        return not status_filter.is_deleted

    def placement_matches(rows, works):
        """Reclassifica só quando algo mudou nas mensagens, no cadastro das obras ou nas regras de spam."""
        senders = store.spam_senders()
        key = (tuple((r['id'], r['status'], r['obra_id'], r['suggestion'], r['reviewed'], r['reason'],
                      r.get('not_spam')) for r in rows), repr(works), tuple(senders))
        if key != placement.key:
            placement.matches, placement.key = encaixar(rows, works, senders), key
        placement.spam_senders = senders
        return placement.matches

    def current_meta(force=False):
        """Situação das obras (lê os checklists): relida a cada 2 min ou em 'Atualizar lista'."""
        if works_meta is None:
            return None
        if force or placement.meta is None or time.monotonic() - placement.meta_at > 120:
            placement.meta, placement.meta_at = works_meta(), time.monotonic()
        return placement.meta

    async def adopt_from_team(refresh=False):
        """OK de outro coordenador (publicação humana) já vale na minha caixa: sem clique repetido."""
        if shared_store is None:
            return 0
        actor = authorize()
        try:
            adopted = await run.io_bound(adopt_team_links, store, shared_store, actor, allowed_ids())
        except (ValueError, PermissionError):
            return 0
        if adopted and alive():
            ui.notify(f'{adopted} e-mail(s) já confirmado(s) por outro coordenador: incluídos em Vinculadas.', type='info')
            if refresh:
                content.refresh()
        return adopted

    async def full_refresh():
        placement.key = None
        current_meta(force=True)
        await adopt_from_team()
        content.refresh()

    def pick_status(key):
        """Contador = atalho do campo Situação; clicar no contador ativo volta a mostrar todas."""
        status_filter.set_value('todos' if status_filter.value == key else key)  # on_change refresca a lista.

    # Pastas abertas sobrevivem ao refresh da lista: conferir o próximo e-mail sem reabrir tudo.
    opened = set()

    def kept_open(expansion, key):
        expansion.on_value_change(lambda e: opened.add(key) if e.value else opened.discard(key))
        return expansion

    def start_open(key, section=False):
        """Aberta se já estava aberta ou se a fila "Aguardando meu OK" está ativa. Na fila, só as
        primeiras pastas abrem sozinhas; as demais abrem pelo "Próximo pendente"."""
        if key in opened:
            return True
        if not placement.auto_open:
            return False
        if not section:
            return True
        placement.auto_budget -= 1
        return placement.auto_budget >= 0

    def may_confirm(wid, fresh=False):
        if confirmable is None or not wid:
            return False
        if fresh or placement.confirmable is None:
            placement.confirmable = set(confirmable())
        return wid in placement.confirmable

    def awaiting_me(match):
        return categoria(match) == 'placed' and may_confirm(match['work'])

    def ok_look(button, tip, confirmed, allowed, many=0):
        button.props(remove='color').props(f"color={'positive' if confirmed else 'grey-6'}")
        what = f'as {many} mensagens pré-vinculadas desta conversa' if many > 1 else 'o vínculo com esta obra'
        tip.set_text(('Vínculo confirmado pelo coordenador' if not many else 'Conversa confirmada pelo coordenador')
                     if confirmed else f'OK do coordenador: confirmar {what}' if allowed else
                     'Aguardando OK do coordenador da obra ou de um administrador')

    def ok_button(mids, wid, sub, many=0):
        """Botão OK (cinza → verde). mids: mensagens que ele confirma, todas da obra wid."""
        confirmed = all(placement.matches[mid].get('coordinator_ok') for mid in mids)
        allowed = confirmed or may_confirm(wid)
        with ui.button().props('flat dense no-caps').classes('com-ok-btn') as button:
            with ui.column().classes('items-center gap-0'):
                ui.label('OK').classes('com-ok-main')
                sub_label = ui.label(sub).classes('com-ok-sub')
            tip = ui.tooltip('')
        ok_look(button, tip, confirmed, allowed, many)
        entry = SimpleNamespace(button=button, tip=tip, mids=list(mids), sub=sub_label, many=many)
        for mid in mids:
            placement.ok_buttons.setdefault(mid, []).append(entry)
        placement.ok_order.append(entry)
        if not confirmed and allowed:
            button.on('click.stop', lambda: confirm_messages(entry.mids, wid))
        return button

    def repaint_ok(mids):
        for entry in {id(e): e for mid in mids for e in placement.ok_buttons.get(mid, [])}.values():
            if entry.button.is_deleted:
                continue
            left = sum(not placement.matches[mid].get('coordinator_ok') for mid in entry.mids)
            if entry.many:
                entry.sub.set_text(f'conversa · {left}' if left else 'conversa')
            if not left:
                ok_look(entry.button, entry.tip, True, True, entry.many)

    def next_pending():
        for entry in placement.ok_order:
            pending = [mid for mid in entry.mids if not placement.matches.get(mid, {}).get('coordinator_ok', True)]
            if pending and not entry.button.is_deleted and may_confirm(placement.matches[pending[0]]['work']):
                return entry
        return None

    async def scroll_to_next():
        """Leva ao próximo botão OK que espera a confirmação deste usuário; se ele estiver numa pasta
        ainda fechada, abre a próxima pasta da fila (montada só agora)."""
        entry = next_pending()
        while entry is None:
            closed = next((s for s in placement.sections if not s.is_deleted and not s.value), None)
            if closed is None:
                ui.notify('Nenhum e-mail aguardando o seu OK nesta lista.', type='info')
                return
            closed.value = True  # on_value_change monta a pasta e registra os botões OK.
            entry = next_pending()
        ui.run_javascript(f'getHtmlElement({entry.button.id}).scrollIntoView({{behavior: "smooth", block: "center"}})')

    async def confirm_messages(mids, wid):
        """OK do coordenador para uma ou mais mensagens da mesma obra, sem refazer a lista (as pastas
        continuam abertas). Banco em thread: no servidor, um só processo atende todos."""
        pending = [mid for mid in mids if mid not in placement.busy
                   and placement.matches[mid]['bucket'] in ('work', 'pending')
                   and not placement.matches[mid].get('coordinator_ok') and placement.matches[mid].get('work') == wid]
        if not pending:
            return
        actor = authorize()
        permitted = allowed_ids()
        if wid not in permitted or not may_confirm(wid, fresh=True):
            ui.notify('Só o coordenador da obra ou um administrador confirma o vínculo.', type='warning')
            return
        def save():
            done, problems = [], []
            for mid in pending:
                try:
                    store.review(mid, wid, actor, OK_NOTE)
                except ValueError as exc:  # Ex.: mensagem alterada em outra aba.
                    problems.append(f'não confirmado: {exc}')
                    continue
                done.append(mid)
                if shared_store is not None:
                    try:
                        publish_message(store, shared_store, mid, actor, permitted)
                    except (ValueError, PermissionError) as exc:
                        problems.append(f'vinculado na sua caixa, mas não publicado na equipe: {exc}')
            # Só as respostas às confirmadas: reprocessar a caixa inteira a cada OK pesava no servidor.
            store.reprocess_replies(actor, done)
            return done, problems
        placement.busy.update(pending)
        try:
            done, problems = await run.io_bound(save)
        finally:
            placement.busy.difference_update(pending)
        if not alive():
            return
        for mid in done:
            if mid in placement.matches:  # A lista pode ter mudado (ex.: troca de aba) durante a gravação.
                placement.matches[mid] = dict(placement.matches[mid], bucket='work', safe=True,
                                              coordinator_ok=True, reason=OK_NOTE)
        repaint_ok(done)
        placement_counters.refresh()
        share_identified()
        if problems:
            ui.notify(' · '.join(dict.fromkeys(problems)), type='warning', multi_line=True)
        if done:
            ui.notify(f'{len(done)} vínculo(s) confirmado(s). Incluído(s) em Vinculadas.', type='positive')
            if placement.auto_open:
                await scroll_to_next()

    async def placement_action(operation, message):
        """operation(actor) só mexe no banco; roda em thread para não travar os outros usuários."""
        actor = authorize()
        try:
            await run.io_bound(operation, actor)
        except (ValueError, PermissionError) as exc:
            if alive():
                ui.notify(str(exc), type='warning')
            return
        if alive():
            ui.notify(message, type='positive')
            content.refresh()

    # As ações devolvem a corrotina: o NiceGUI a aguarda quando chamada pelo on_click.
    def to_trash(mids):
        return placement_action(lambda actor: [store.review(mid, None, actor, 'Enviado à lixeira pessoal.') for mid in mids],
                                f'{len(mids)} e-mail(s) na lixeira pessoal. Podem ser restaurados; nada foi apagado na caixa original.')

    def to_spam(mid):
        return placement_action(lambda actor: store.mark_spam(mid, actor), 'E-mail movido para Provável spam.')

    def restore(mids):
        """Sai do spam/lixeira e volta à classificação automática (sem voltar ao spam)."""
        return placement_action(lambda actor: store.restore(mids, actor),
                                f'{len(mids)} e-mail(s) restaurado(s). Confira o pré-vínculo na pasta da obra.')

    def always_spam(address):
        return placement_action(lambda actor: store.add_spam_sender(address, actor),
                                f'Próximos e-mails de {address} irão direto para Provável spam.')

    def stop_spam_rule(address):
        return placement_action(lambda actor: store.remove_spam_sender(address, actor),
                                f'Regra removida: {address} volta a ser classificado normalmente.')

    def relocate_dialog(mid, current=None, subject=''):
        authorize()
        permitted = allowed_ids()
        works = {w['id']: w for w in store.works() if w['id'] in permitted}
        codes = sorted(work_codes(subject))
        with ui.dialog() as dialog, ui.card().classes('responsive-dialog-sm').style('padding: 20px;'):
            ui.label('Realocar obra').classes('com-dialog-title')
            ui.label('O e-mail vai para a pasta escolhida e continua aguardando o OK do coordenador.').classes('com-muted')
            options = {wid: f"{w['name'].split(' / ')[0]} · IC {w['ic'] or 'não cadastrado'}" for wid, w in works.items()}
            choice = ui.select(options, value=current if current in options else None, label='Obra correta',
                               with_input=True).classes('w-full').props('outlined dense')
            # Ensinar a obra: próximos e-mails parecidos já chegam pré-vinculados à obra certa.
            learn = ui.checkbox('Usar para identificar esta obra daqui em diante')
            with ui.column().classes('w-full gap-1').bind_visibility_from(learn, 'value'):
                alias = ui.input('Nome no assunto (opcional)', placeholder='ex.: ALMENARA').classes('w-full').props('outlined dense')
                use_ic = ui.checkbox(f'Cadastrar o IC {codes[0]} do assunto (se a obra ainda não tiver IC)', value=True) \
                    if len(codes) == 1 else None
                ui.label('Grava em Identificação das obras (menu ⋮).').classes('com-meta')
            def move():
                target = choice.value
                if not target:
                    ui.notify('Selecione a obra.', type='warning')
                    return None
                name = (alias.value or '').strip() if learn.value else ''
                if learn.value and name and len(name) < 3:
                    ui.notify('Use um nome com pelo menos 3 letras.', type='warning')
                    return None
                ic = codes[0] if learn.value and use_ic is not None and use_ic.value and not works[target]['ic'] else ''
                def apply(actor):
                    store.relocate(mid, target, actor)
                    if name or ic:
                        work = works[target]
                        aliases = work['aliases'] + ([name] if name and name.casefold() not in
                                                     {a.casefold() for a in work['aliases']} else [])
                        store.save_work(target, work['name'], work['ic'] or ic, aliases, work['confirmed'], actor)
                        store.reprocess(actor)
                dialog.close()
                learned = ' Identificação da obra atualizada.' if name or ic else ''
                return placement_action(apply, f'E-mail realocado para {options[target]}.{learned}')
            def unlink():
                dialog.close()
                return placement_action(lambda actor: store.relocate(mid, None, actor), 'E-mail desvinculado: obra a conferir.')
            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('Cancelar', on_click=dialog.close).props('flat no-caps')
                ui.button('Desvincular', on_click=unlink).props('outline no-caps').classes('com-btn')
                ui.button('Mover para obra', icon='drive_file_move', on_click=move
                          ).props('unelevated color=primary no-caps').classes('com-btn')
        dialog.open()

    def message_placement(m, header):
        """Cabeçalho: OK do coordenador + lixeira. Retorna o pré-vínculo (ou None fora de Meu e-mail)."""
        match = placement.matches.get(m['id'])
        if not match or match['bucket'] not in ('work', 'pending'):
            return None
        with header:
            if match.get('work'):
                ok_button([m['id']], match['work'], 'coordenador')
            if not match.get('coordinator_ok'):
                ui.button(icon='delete_outline').props('flat round dense').style('color: #c62828;').tooltip(
                    'Enviar à lixeira pessoal').on('click.stop', lambda mid=m['id']: to_trash([mid]))
        return match

    def message_actions(m, match):
        prefix = '' if match.get('coordinator_ok') else ('Pré-vínculo sugerido · ' if match['bucket'] == 'pending' else 'Pré-vinculada · ')
        ui.label(prefix + (match.get('reason') or '')).classes('com-meta').style('white-space: normal;')
        if match.get('coordinator_ok'):
            return
        with ui.row().classes('gap-1'):
            ui.button('Realocar obra', icon='drive_file_move',
                      on_click=lambda mid=m['id'], w=match.get('work'), s=m['subject']: relocate_dialog(mid, w, s)
                      ).props('flat dense no-caps')
            ui.button('Fora do escopo', icon='filter_alt', on_click=lambda mid=m['id']: to_spam(mid)).props('flat dense no-caps')
            ui.button('Lixeira', icon='delete_outline', on_click=lambda mid=m['id']: to_trash([mid])
                      ).props('flat dense no-caps color=negative')

    @ui.refreshable
    def placement_counters():
        """Meu e-mail: uma linha só; cada contador seleciona a mesma opção do campo Situação."""
        counts = {**contadores(placement.matches.values()), **placement.totals,
                  'mine': sum(awaiting_me(m) for m in placement.matches.values())}
        items = [('todos', 'mensagens', 'Todas as mensagens')]
        if counts['mine'] or status_filter.value == 'mine':
            items.append(('mine', 'aguardando meu OK', 'Pré-vinculadas nas obras em que você confirma o vínculo'))
        items += [('confirmed', 'vinculadas', 'Vínculo confirmado pelo OK do coordenador'),
                  ('placed', 'pré-vinculadas', 'Na pasta da obra, aguardando o OK do coordenador'),
                  ('unassigned', 'sem obra definida', 'Em "Obra a conferir"')]
        if counts.get('conflito'):
            items.append(('conflito', 'conflitos', 'Divergência de obra ou de identificação da mensagem'))
        if counts.get('equipe'):
            items.append(('equipe', 'já na equipe', TEAM_LABEL))
        items += [('spam', 'provável spam', 'Sem relação com obras ou processos da CAIXA'),
                  ('trash', 'na lixeira', 'Lixeira pessoal, recuperável')]
        with ui.element('div').classes('com-counters items-center'):
            for key, label, tip in items:
                active = status_filter.value == key
                css = 'com-counter' + (' ativo' if active else '')
                if key in ('unassigned', 'conflito', 'mine') and counts.get(key):
                    css += ' com-counter-alert'
                if active and key != 'todos':
                    tip += '. Clique de novo para ver todas.'
                with ui.element('div').classes(css).tooltip(tip).on('click', lambda k=key: pick_status(k)):
                    ui.html(f'<b>{counts.get(key, 0)}</b>', sanitize=False)
                    ui.label(label)
            if status_filter.value == 'mine' and counts['mine']:
                ui.button('Próximo pendente', icon='arrow_downward', on_click=scroll_to_next
                          ).props('unelevated dense no-caps color=primary').classes('com-btn')

    def message_text(row):
        """Texto da pesquisa: assunto, remetente e conteúdo."""
        return ' '.join((row['subject'] or '', row['sender'] or '', row.get('body') or '')).casefold()

    def found(row, term):
        """A pesquisa encontra a mensagem pelo texto ou pelo nome de um anexo."""
        return (not term or term in message_text(row)
                or any(term in (a['name'] or '').casefold() for a in row.get('attachments', [])))

    def render_spam_rules():
        if not placement.spam_senders:
            return
        with ui.expansion(f'Remetentes tratados sempre como spam ({len(placement.spam_senders)})',
                          icon='block').classes('w-full com-folder'):
            for address in placement.spam_senders:
                with ui.row().classes('w-full items-center gap-2 border-t').style('padding: 6px 16px;'):
                    ui.label(address).classes('com-title flex-1 ellipsis')
                    ui.button('Remover regra', icon='undo', on_click=lambda a=address: stop_spam_rule(a)
                              ).props('flat dense no-caps')

    def render_separated(rows, bucket, term):
        """Provável spam / Lixeira pessoal: lista com seleção em lote. Nada sai da caixa original."""
        chosen = sorted((r for r in rows if placement.matches.get(r['id'], {}).get('bucket') == bucket
                         and found(r, term)),
                        key=lambda r: (timestamp(r), r['id']), reverse=True)
        title = 'Provável spam' if bucket == 'spam' else 'Lixeira pessoal'
        ui.label(f'{title} • separação local e recuperável. Nenhum e-mail é apagado na KingHost.').classes('com-meta')
        if bucket == 'spam':
            render_spam_rules()
        if not chosen:
            ui.label('Nenhuma mensagem aqui.').classes('com-muted')
            return
        selected, checks = set(), {}
        def selection_changed(event, mid):
            selected.add(mid) if event.value else selected.discard(mid)
            selection_count.set_text(f'{len(selected)} de {len(chosen)} selecionados')
        def select_all(value):
            for checkbox in checks.values():
                checkbox.set_value(value)
        def batch(action):
            if not selected:
                ui.notify('Selecione ao menos um e-mail.', type='warning')
                return None
            return action(sorted(selected))
        with ui.row().classes('w-full items-center gap-2'):
            ui.button('Selecionar todos', icon='select_all', on_click=lambda: select_all(True)).props('outline dense no-caps').classes('com-btn')
            ui.button('Limpar seleção', on_click=lambda: select_all(False)).props('flat dense no-caps')
            if bucket == 'spam':
                ui.button('Enviar selecionados à lixeira', icon='delete_outline', on_click=lambda: batch(to_trash)
                          ).props('outline dense no-caps color=negative').classes('com-btn')
            ui.button('Restaurar selecionados', icon='restore', on_click=lambda: batch(restore)
                      ).props('outline dense no-caps').classes('com-btn')
            selection_count = ui.label(f'0 de {len(chosen)} selecionados').classes('com-meta')
        rules = set(placement.spam_senders)
        for r in chosen:
            match = placement.matches[r['id']]
            address = sender_address(r)
            with ui.row().classes('w-full items-start no-wrap gap-2'):
                checks[r['id']] = ui.checkbox(on_change=lambda e, mid=r['id']: selection_changed(e, mid))
                border = SENDER_BORDER[sender_color(r.get('sender', ''))]
                with ui.column().classes('com-mail-card gap-1 flex-1').style(f'border-left-color: {border};'):
                    ui.label(r['subject'] or '(Sem assunto)').classes('com-title ellipsis')
                    ui.label(f"{display_date(r['sent_date'])} · {sender_name(r['sender'])}").classes('com-meta')
                    ui.label(match.get('reason') or '').classes('com-meta').style('white-space: normal;')
                    with ui.row().classes('gap-1'):
                        ui.button('Abrir', icon='mail_outline', on_click=lambda mid=r['id']: details(mid)).props('flat dense no-caps')
                        ui.button('Não é spam' if bucket == 'spam' else 'Restaurar', icon='restore',
                                  on_click=lambda mid=r['id']: restore([mid])).props('flat dense no-caps')
                        if bucket == 'spam':
                            ui.button('Lixeira', icon='delete_outline', on_click=lambda mid=r['id']: to_trash([mid])
                                      ).props('flat dense no-caps color=negative')
                            if ('@' in address and address not in rules
                                    and address.rsplit('@', 1)[1] not in PROTECTED_DOMAINS):
                                ui.button('Sempre spam deste remetente', icon='block',
                                          on_click=lambda a=address: always_spam(a)).props('flat dense no-caps')

    def expansion_header(expansion):
        """Cabeçalho próprio da expansão: linha com título e detalhes em segundo plano."""
        slot = expansion.add_slot('header')
        with slot:
            return ui.row().classes('w-full items-center no-wrap gap-3').style('min-width: 0;')

    def render_conversation(g, wid, repository, shared):
        icon, _, situation = conversation_status(g)
        topic = topic_label(g['subject'], g.get('body', ''))
        icon = TOPIC_ICONS.get(topic, icon)
        key = ('conv', wid, g['id'])
        with kept_open(ui.expansion(value=start_open(key)), key).classes('w-full border-t') as conversation_folder:
            with expansion_header(conversation_folder):
                ui.icon(icon).classes('com-item-icon')
                with ui.column().classes('gap-0 flex-1').style('min-width: 0;'):
                    ui.label(topic).classes('com-title ellipsis')
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
                # OK da conversa: confirma de uma vez as mensagens pré-vinculadas a ESTA obra
                # (as encaixadas em outra obra ficam de fora).
                if not shared and wid != 'pending':
                    ours = [m['id'] for m in g['messages']
                            if placement.matches.get(m['id'], {}).get('bucket') in ('work', 'pending')
                            and placement.matches[m['id']].get('work') == wid]
                    if ours:
                        left = sum(not placement.matches[mid].get('coordinator_ok') for mid in ours)
                        ok_button(ours, wid, f'conversa · {left}' if left else 'conversa', many=len(ours))
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
                list_key = ('msgs', wid, g['id'])
                with kept_open(ui.expansion(f"Mensagens e respostas ({g['message_count']})", icon='mail',
                                            value=start_open(list_key)), list_key).classes('w-full'):
                    for m in g['messages']:
                        match = None if shared else placement.matches.get(m['id'])
                        message_key = ('msg', wid, m['id'])
                        if match and match['bucket'] in ('work', 'pending'):
                            # Cabeçalho próprio: data/remetente + OK do coordenador e lixeira.
                            message_folder = kept_open(ui.expansion(value=message_key in opened), message_key
                                                       ).classes('w-full border-t')
                            with message_folder:
                                with expansion_header(message_folder) as header:
                                    ui.icon('chat_bubble_outline').classes('com-item-icon')
                                    with ui.column().classes('gap-0 flex-1').style('min-width: 0;'):
                                        ui.label(f"{display_date(m['sent_date'])} — {sender_name(m['sender'])}").classes('com-title ellipsis')
                                        ui.label(m['subject'] or '(Sem assunto)').classes('com-meta ellipsis')
                                message_placement(m, header)
                        else:
                            match = None
                            message_folder = kept_open(ui.expansion(f"{display_date(m['sent_date'])} — {sender_name(m['sender'])}",
                                                                    caption=m['subject'], icon='chat_bubble_outline',
                                                                    value=message_key in opened), message_key
                                                       ).classes('w-full border-t')
                        with message_folder:
                            paint(message_folder, sender_color(m.get('sender', '')))
                            if match:
                                message_actions(m, match)
                            ui.label(m['body'] or '(Sem corpo de texto)').classes('mail-body p-2 text-sm')
                            ui.button('Conferir vínculo / ver detalhes', on_click=lambda mid=m['id']: details(mid, shared)).props('flat no-caps')
                if g['files']:
                    # Pesquisa pelo nome de um anexo: o painel já abre e o arquivo fica destacado.
                    term = (search.value or '').casefold()
                    file_hits = {f['sha256'] for f in g['files'] if term and any(term in n.casefold() for n in f['names'])}
                    with ui.expansion(f"Anexos da conversa ({len(g['files'])})", icon='attach_file',
                                      value=bool(file_hits)).classes('w-full') as files_panel:
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
                            with ui.row().classes('w-full items-center gap-2 border-t').style(
                                    'padding: 8px 4px;' + (' background: #fff8e1;' if f['sha256'] in file_hits else '')) as file_row:
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
        with kept_open(ui.expansion(value=('seg', wid) in opened), ('seg', wid)).classes('w-full border-t') as seguro_folder:
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

    def situation_icon(meta, size):
        icon, color = SITUACAO.get(meta.get('bucket'), SITUACAO_A_CONFERIR)
        ui.icon(icon, color=color, size=size).tooltip(
            f"Obras: {meta['status_texto']}" if meta.get('status_texto') else 'Situação a conferir na aba Obras')

    def render_section(wid, name, conversations, repository, shared, meta=None, notices=()):
        """meta: dados do cadastro de Obras (UF, IC, contrato, situação); sem ele, cabeçalho simples."""
        total = sum(g['message_count'] for g in conversations)
        age = communication_age([m for g in conversations for m in g['messages']])
        key = ('sec', wid)
        with kept_open(ui.expansion(value=start_open(key, section=True)), key).classes('w-full com-folder') as section:
            with expansion_header(section):
                if wid == 'pending' or meta is None:
                    ui.icon('help_outline' if wid == 'pending' else 'folder').classes('com-folder-icon')
                    ui.label(name).classes('com-folder-title ellipsis')
                else:
                    uf = meta.get('uf') or '?'
                    with ui.element('div').classes('com-uf').tooltip(f'UF {uf}' if uf != '?' else 'UF a conferir'):
                        ui.icon('folder').style(f'color: {cor_uf(uf)};')
                        ui.label(uf).classes('com-uf-label' + (' com-uf-long' if len(uf) > 2 else ''))
                    with ui.column().classes('gap-0').style('min-width: 0;'):
                        with ui.row().classes('items-center no-wrap gap-2').style('min-width: 0;'):
                            ui.label(name).classes('com-folder-title ellipsis')
                            situation_icon(meta, '18px')
                            ui.label(f"IC {meta.get('ic') or 'não cadastrado'}").classes('com-count').tooltip(
                                'IC do cadastro da obra; número e ano identificam o serviço')
                        ui.label(f"{'UF a conferir' if uf == '?' else uf} · {meta.get('contrato') or 'Contrato a conferir'}"
                                 f" · Obras: {meta.get('status_texto') or 'situação a conferir'}").classes('com-meta ellipsis')
                if conversations:
                    ui.label(f"{len(conversations)} assunto{'s' if len(conversations) != 1 else ''}").classes('com-count')
                    ui.label(f"{total} e-mail{'s' if total != 1 else ''}").classes('com-count gt-xs')
                if notices:
                    ui.label(f"{len(notices)} aviso{'s' if len(notices) != 1 else ''}").classes('com-chip com-chip-yellow').tooltip(
                        'E-mails desta obra que não foram importados')
                ui.space()
                ui.label(age).classes('com-meta gt-xs')
                if wid != 'pending' and meta is not None:
                    situation_icon(meta, '22px')

        # Conteúdo montado só na primeira abertura da pasta: com todas as obras
        # montadas de uma vez (seguros incluídos) a tela levava segundos para abrir.
        def fill():
            if notices:
                render_folder_notices(notices)
            if any(placement.matches.get(m['id'], {}).get('bucket') == 'pending' and m['obra_id'] != wid
                   for g in conversations for m in g['messages']) and wid != 'pending':
                ui.label('Inclui pré-vínculos sugeridos para facilitar a conferência; ainda não são vínculos confirmados.'
                         ).classes('com-warn-text').style('padding: 8px 16px 0;')
            if seguro_factory and wid != 'pending':
                render_insurance(wid, conversations, repository, shared)
            for g in conversations:
                if not seguro_factory or topic_label(g['subject']) != 'Seguro e garantia':
                    render_conversation(g, wid, repository, shared)
            if not conversations:
                ui.label('Nenhuma conversa neste filtro.').classes('com-muted').style('padding: 12px 16px;')
        fill_on_open(section, fill)
        if placement.auto_open and wid != 'pending':
            placement.sections.append(section)  # Fila: "Próximo pendente" abre as pastas ainda fechadas.

    def fill_on_open(expansion, build):
        """Monta o conteúdo na primeira abertura (ou já, se a pasta continuou aberta após atualizar)."""
        done = False
        def fill(_=None):
            nonlocal done
            if expansion.value and not done:
                done = True
                with expansion:
                    build()
        expansion.on_value_change(fill)
        fill()

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
            local_works = store.works()  # Cadastro de identificação da caixa pessoal, lido uma vez.
            permitted = allowed_ids() if shared else None
            show_automatic = status_filter.value == 'todas_auto'
            all_rows = [r for r in repository.messages() if not shared or r['obra_id'] in permitted]
            rows = repository.conversation_rows(permitted)
            # Na caixa pessoal: mensagens sem decisão que a equipe já publicou (só obras permitidas).
            team = {} if shared else team_pending(rows, shared_store, allowed_ids())
            for row in rows:
                row['team_obra'] = team.get(row['id'])
            counts = {s: sum(r['status'] == s and r['id'] not in team for r in all_rows) for s in LABELS}
            # Pré-vínculo por obra só na caixa pessoal; o histórico da equipe já é todo vinculado.
            if shared:
                placement.matches, placement.key = {}, None
            else:
                placement_matches(rows, local_works)
                placement.totals = {'todos': len(all_rows), 'conflito': counts['conflito'], 'equipe': len(team)}
            placement.confirmable, placement.ok_buttons, placement.ok_order = None, {}, []
            placement.auto_open = not shared and status_filter.value == 'mine'
            placement.auto_budget, placement.sections = AUTO_OPEN_LIMIT, []

            # ── Contadores (clicar = escolher a mesma opção do campo Situação) ──
            if shared:
                with ui.element('div').classes('com-counters'):
                    counters = [('todos', 'mensagens', len(all_rows)), ('vinculado', 'vinculadas', counts['vinculado']),
                                ('revisar', 'para conferir', counts['revisar']), ('conflito', 'conflitos', counts['conflito'])]
                    for key, label, number in counters:
                        css = 'com-counter'
                        if status_filter.value == key:
                            css += ' ativo'
                        if key in ('revisar', 'conflito') and number:
                            css += ' com-counter-alert'
                        with ui.element('div').classes(css).on('click', lambda k=key: pick_status(k)):
                            ui.html(f'<b>{number}</b>', sanitize=False)
                            ui.label(label)
            else:
                placement_counters()

            term = (search.value or '').casefold()
            if not shared and status_filter.value in SEPARATED:
                # Provável spam e Lixeira: lista própria, com seleção em lote.
                render_separated(rows, status_filter.value, term)
                return
            if not shared and status_filter.value != 'todas_auto':
                # Provável spam e lixeira pessoal não poluem as pastas das obras.
                rows = [r for r in rows if placement.matches[r['id']]['bucket'] not in SEPARATED]
            groups = build_conversations(rows)
            def status_matches(row):
                value = status_filter.value
                if value in ('todos', 'todas_auto'):
                    return True
                if value == 'mine':
                    return not shared and row['id'] in placement.matches and awaiting_me(placement.matches[row['id']])
                if value == 'equipe':
                    return bool(row.get('team_obra'))
                if not shared and value in CATEGORY_LABELS:
                    match = placement.matches.get(row['id'])
                    return match is not None and categoria(match) == value
                return row['status'] == value and not row.get('team_obra')
            def matches(row):
                prelinked = placement.matches.get(row['id'], {}).get('work')
                return (status_matches(row)
                        and (work_filter.value == 'todos' or work_filter.value in (row['obra_id'], row['suggestion'], prelinked))
                        and found(row, term))
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

            if presentation.value != 'conversations':
                render_skipped(store.skipped())

            if presentation.value == 'attachments':
                group_map = {g['id']: g for g in groups}
                # Com pesquisa: o arquivo aparece se o nome bate ou se a conversa bate pelo texto.
                text_hit = {g['id'] for g in groups if not term or any(term in message_text(m) for m in g['messages'])}
                file_rows = [{'id': f"{g['id']}-{f['id']}", 'group_id': g['id'],
                              'name': ' / '.join(f['names']), 'subject': g['subject'],
                              'work_name': g['work_name'] or 'A conferir',
                              'occurrences': len(f['origins']), 'size': f"{f['size'] / 1024:.1f} KB"}
                             for g in groups for f in g['files']
                             if g['id'] in text_hit or any(term in n.casefold() for n in f['names'])]
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
                    category = None if shared else categoria(placement.matches.get(row['id'], {'bucket': 'tecnico'}))
                    row['status_label'] = (TEAM_LABEL if row.get('team_obra') else
                                           CATEGORY_LABELS[category] if category else LABELS[row['status']])
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
                works = available_works() if available_works else local_works
                known = {w['id']: w for w in local_works}
                buckets = {str(w['id']): [] for w in works}
                pending = []
                for g in groups:
                    if shared:
                        candidate = obra_da_conversa(g, list(known.values()))
                    else:
                        # Encaixar primeiro: a conversa vai para a obra provável da mensagem mais recente
                        # (ou a única obra pré-vinculada na conversa); dúvida real fica em "Obra a conferir".
                        placed = {placement.matches[m['id']].get('work') for m in g['messages']
                                  if placement.matches[m['id']]['bucket'] in ('work', 'pending')} - {None}
                        latest = placement.matches[g['id']]
                        candidate = (latest.get('work') if latest['bucket'] in ('work', 'pending') and latest.get('work')
                                     else (next(iter(placed)) if len(placed) == 1 else None))
                        if candidate is None and latest['bucket'] == 'tecnico':
                            candidate = obra_da_conversa(g, list(known.values()))
                    if candidate in buckets:
                        buckets[candidate].append(g)
                    else:
                        pending.append(g)
                meta = current_meta()
                notices, unmatched = avisos_por_obra(store.skipped(), list(known.values()))
                unmatched += [n for wid, items in notices.items() if wid not in buckets for n in items]
                render_skipped(unmatched)
                sections = [(str(w['id']), w['name'].split(' / ')[0], buckets[str(w['id'])]) for w in works]
                sections.sort(key=lambda s: normalized(s[1]))
                if pending:
                    sections.insert(0, ('pending', 'Obra a conferir', pending))
                def section(wid, name, conversations):
                    render_section(wid, name, conversations, repository, shared,
                                   meta=None if meta is None else meta.get(wid, {}), notices=notices.get(wid, []))
                if work_filter.value != 'todos':
                    for wid, name, conversations in sections:
                        if wid == work_filter.value:
                            section(wid, name, conversations)
                else:
                    if situation.value != 'todos':
                        # Mesma regra da aba Obras; obra sem situação conhecida fica só em "Todos".
                        sections = [s for s in sections if (meta or {}).get(s[0], {}).get('bucket') == situation.value]
                    if status_filter.value not in ('todos', 'todas_auto'):
                        # Situação escolhida: só as pastas com e-mails dessa situação.
                        sections = [s for s in sections if s[2]]
                    active = [s for s in sections if s[2] or notices.get(s[0])]
                    empty = [s for s in sections if not (s[2] or notices.get(s[0]))]
                    for wid, name, conversations in active:
                        section(wid, name, conversations)
                    if not active:
                        with ui.element('div').classes('com-empty w-full'):
                            ui.icon('mark_email_unread').style('font-size: 40px; color: #c5cae9;')
                            ui.label('Nenhuma conversa neste filtro').classes('com-section-title').style('margin-top: 8px;')
                            ui.label('Conecte seu e-mail ou importe um .eml pelo menu ⋮ no topo.').classes('com-muted')
                    if empty:
                        # Montado só ao abrir: com dezenas de obras, recriar todas as pastas vazias
                        # a cada clique num filtro deixava a tela lenta.
                        group = kept_open(ui.expansion(f'Obras sem comunicação ({len(empty)})', icon='folder_open',
                                                       value=('sem_comunicacao',) in opened), ('sem_comunicacao',)
                                          ).classes('w-full com-folder-group')
                        def fill_empty():
                            with ui.column().classes('w-full gap-3'):
                                for wid, name, conversations in empty:
                                    section(wid, name, conversations)
                        fill_on_open(group, fill_empty)
        content()
        # OK humano de outro coordenador já vale aqui (sem travar a abertura da tela).
        ui.timer(0.5, lambda: adopt_from_team(refresh=True), once=True)
