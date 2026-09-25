"""Bloco visual nos detalhes da obra, sem login ou banco paralelo."""
import json
from datetime import datetime
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo
from nicegui import ui
from db.seguro_repo import COTACOES, TIPOS_SEGURO

ETAPAS = {'solicitado':'1. CAIXA solicitou o seguro', 'pedido':'2. Pedido à seguradora',
          'recebido':'3. Apólice e boleto recebidos - provisórios', 'analise':'4. Enviado à CAIXA - em análise',
          'ajustes':'5. CAIXA solicitou ajustes', 'aceito':'6. CAIXA aceitou a apólice',
          'sem_resposta':'6. Validação interna por ausência de resposta — sem aceite expresso do banco'}
ACOES = {'solicitacao':'Registrar solicitação da CAIXA','pedido':'Registrar pedido à seguradora',
         'recebimento':'Registrar apólice e boleto recebidos','envio':'Registrar envio à CAIXA',
         'ajustes':'Registrar ajustes solicitados','aceite':'Validar com aprovação do banco',
         'sem_resposta':'Validar por ausência de resposta',
         'nova_rodada':'Pedir correção / abrir nova rodada'}


def data_local(value):
    return datetime.fromisoformat(value).astimezone(ZoneInfo('America/Sao_Paulo')).strftime('%d/%m/%Y %H:%M:%S')


def titulo_seguro(state):
    readings=[r for r in state.get('leituras',[]) if not r['review'] and r['action']!='revisar']
    latest=max(readings,key=lambda r:r['timestamp'],default=None)
    changes=[h for h in state.get('historico',[]) if h['campo'].startswith('rodada:')]
    cutoff=0
    if changes:
        snapshot=json.loads(changes[0]['novo'])
        auto=json.loads(snapshot.get('vinculos') or '{}').get('automatico')
        cutoff=auto['timestamp'] if auto else datetime.fromisoformat(changes[0]['data_hora']).timestamp()
    if latest and latest['timestamp']>cutoff and latest['result']!='Registrado automaticamente':
        return 'Em processo · Identificado: '+latest['title']+' · Conferir sequência'
    return titulo_etapa(state)


def titulo_etapa(state):
    if state['definitivo']:
        return ('Validada internamente · Ausência de resposta do banco' if state['atual']['etapa']=='sem_resposta'
                else 'Aprovada pelo banco · Seguro e boleto definitivos')
    atual = state['atual']
    if not atual:
        if state['cotacao'] != 'Não informada':
            return 'Em processo · Cotação ' + state['cotacao'].lower() + ' · Registrar etapa do seguro'
        return 'Não solicitada · Sem solicitação registrada'
    etapa = atual['etapa']
    detalhes = {
        'solicitado': 'MACH precisa solicitar à seguradora',
        'pedido': 'Aguardando correção da seguradora' if atual['numero'] > 1 else 'Aguardando documentos da seguradora',
        'recebido': 'MACH precisa enviar à CAIXA',
        'analise': 'Em análise pela CAIXA',
        'ajustes': 'CAIXA pediu ajustes · MACH precisa solicitar correção',
        'aceito': 'CAIXA aceitou · Aguardando conferência final da MACH',
        'sem_resposta': 'Ausência de resposta · Aguardando conferência final da MACH',
    }
    if etapa=='solicitado' and json.loads(atual.get('vinculos') or '{}').get('automatico'):
        detalhes[etapa]='Solicitação CAIXA identificada · Pedido à seguradora não localizado'
    if etapa == 'analise':
        envio = next((h for h in state['historico'] if h['campo']=='rodada:envio' and h.get('rodada_id')==atual['id']),None)
        if envio:
            snapshot=json.loads(envio['novo'])
            ref=json.loads(snapshot.get('vinculos') or '{}').get('evidencia',{})
            try:
                sent=parsedate_to_datetime(ref['date'])
                if sent.tzinfo is None: raise ValueError('Sem fuso')
                days=(datetime.now(ZoneInfo('America/Sao_Paulo')).date()-sent.astimezone(ZoneInfo('America/Sao_Paulo')).date()).days
                detalhes[etapa]=f'Enviado à CAIXA há {days} dias · Nenhum pedido de alteração registrado' if days>=0 else 'Em análise pela CAIXA · Conferir data do envio'
            except (KeyError, ValueError, TypeError, OverflowError):
                detalhes[etapa]='Em análise pela CAIXA · Data do envio não identificada'
    if etapa in ('aceito','sem_resposta'):
        faltam = [nome for campo, nome in [('ok_seguro', 'OK Seguro'), ('ok_boleto', 'OK Boleto')] if not state[campo]]
        detalhes[etapa] += ' (' + ' e '.join(faltam) + ')'
    return 'Em processo · ' + detalhes[etapa]


def render_seguro(service, obra_id, on_state=None):
    fontes=getattr(service,'fontes',None)
    def open_mail(ref):
        try:
            service.obter(obra_id)
            message=fontes.mensagem(ref)
            with ui.dialog() as dialog, ui.card().classes('responsive-dialog').style('padding: 20px; max-height: 85vh; overflow-y: auto;'):
                ui.label(message['subject']).classes('text-lg font-bold')
                ui.label(message['sender']+' • '+message['sent_date']).classes('text-sm')
                ui.label(message['body']).style('white-space:pre-wrap;overflow-wrap:anywhere')
                ui.button('Fechar e-mail',on_click=dialog.close).props('flat')
            dialog.open()
        except (PermissionError,ValueError) as error: ui.notify(str(error),type='warning')
    def linked_files(rodada):
        if not fontes: return
        links=json.loads(rodada.get('vinculos') or '{}')
        with ui.row().classes('w-full gap-2'):
            if links.get('evidencia'):
                ui.button('Abrir e-mail da etapa',icon='mail',on_click=lambda r=links['evidencia']:open_mail(r)).props('flat dense')
            for field,title in [('apolice','Apólice desta versão'),('boleto','Boleto desta versão')]:
                if links.get(field):
                    def download(ref=links[field]):
                        try:
                            service.obter(obra_id)
                            attachment=fontes.anexo(ref)
                            ui.download.content(attachment['payload'],attachment['name'],'application/octet-stream')
                        except (PermissionError,ValueError) as error: ui.notify(str(error),type='warning')
                    ui.button(title,icon='download',on_click=download).props('outline dense')

    @ui.refreshable
    def painel():
        try:
            if hasattr(service,'interpretar_emails'):
                service.interpretar_emails()
            state, can_edit = service.obter(obra_id)
        except (PermissionError, ValueError) as error:
            if on_state:
                on_state(None)
            ui.label(str(error)).classes('text-red-700')
            return
        if on_state:
            on_state(state)
        with ui.card().classes('w-full').style('border: 1px solid #e8eaf0; border-radius: 12px; box-shadow: none; padding: 16px;'):
            ui.label(TIPOS_SEGURO.get(state.get('tipo'),'SEGURO')).style('font-size: 16px; font-weight: bold; color: #1976d2;')
            final_label = ('LIBERADO INTERNAMENTE / AUSÊNCIA DE RESPOSTA — SEM ACEITE EXPRESSO DO BANCO'
                           if state['atual'] and state['atual']['etapa']=='sem_resposta' else 'SEGURO DEFINITIVO / LIBERADO — APROVAÇÃO DO BANCO')
            ui.label(final_label if state['definitivo'] else 'AGUARDANDO VALIDAÇÃO').classes('w-full p-3 rounded font-bold').style('background: #e8f5e9; color: #1b5e20;' if state['definitivo'] else 'background: #fff8e1; color: #8d5800;')
            ui.label('Cotação aprovada não significa seguro validado. OK Boleto confirma o documento definitivo; não registra pagamento.').classes('text-sm text-gray-600')
            if fontes:
                ui.button('Atualizar situação pelos e-mails',icon='manage_search',on_click=painel.refresh).props('outline')
                ui.label('Leitura automática local dos e-mails importados. Etapas claras são registradas com evidência; lacunas e ambiguidades ficam para conferência. Os dois OKs finais continuam humanos.').classes('text-sm text-blue-800')
                readings=sorted(state.get('leituras',[]),key=lambda r:r['timestamp'],reverse=True)
                if readings:
                    strong=next((r for r in readings if not r['review'] and r['action']!='revisar'),None)
                    if strong:
                        ui.label('Última situação identificada nos e-mails: '+strong['title']).classes('font-bold text-amber-800')
                        ui.label(strong['result']+' • '+strong['source']['date']).classes('text-sm')
                    with ui.expansion(f'Leitura dos e-mails • {len(readings)} mensagens interpretadas',icon='manage_search').classes('w-full'):
                        for reading in readings:
                            with ui.column().classes('w-full border-t py-2 gap-1'):
                                ui.label(reading['title']+' • '+reading['result']).classes('font-bold')
                                ui.label(reading['source']['date']+' • '+reading['source']['sender']).classes('text-xs')
                                ui.label('Encontrado em: '+reading['source'].get('topic','Assunto original')+' • '+reading['source']['subject']).classes('text-sm text-blue-800')
                                ui.label(reading['reason']).classes('text-sm')
                                if reading['forwarded']: ui.label('Fonte encaminhada; data exibida é a do encaminhamento.').classes('text-xs')
                                ui.label(reading['excerpt']).classes('text-sm').style('white-space:pre-wrap')
                                ui.button('Abrir e-mail que fundamenta a leitura',on_click=lambda ref=reading['source']:open_mail(ref)).props('flat dense')
                else:
                    ui.label('Nenhuma etapa de seguro identificada nas mensagens disponíveis. Isso não significa que ela não aconteceu.').classes('text-sm')
            def change(field, value):
                try:
                    service.alterar(obra_id, field, value, state['revisao'])
                    ui.notify('Validação atualizada e registrada no histórico.', type='positive')
                except (PermissionError, ValueError) as error:
                    ui.notify(str(error), type='warning')
                painel.refresh()
            cotacao = ui.select(list(COTACOES), value=state['cotacao'], label='Cotação', on_change=lambda e: change('cotacao',e.value)).classes('w-full').props('outlined')
            if not can_edit: cotacao.disable()
            atual=state['atual']
            ui.separator()
            ui.label(f"Rodada {atual['numero']} • {ETAPAS[atual['etapa']]}" if atual else '1. Aguardando registro da solicitação da CAIXA').classes('font-bold')
            if atual:
                if atual['etapa']=='analise':
                    ui.label(titulo_seguro(state)).classes('font-bold text-amber-800')
                    ui.label('A leitura considera apenas mensagens importadas. Confira os pedidos de alteração identificados antes de validar por ausência de resposta.').classes('text-xs text-gray-600')
                ui.label('Apólice desta rodada: '+(atual['apolice'] or 'Não identificada nesta rodada'))
                ui.label('Boleto desta rodada: '+(atual['boleto'] or 'Não identificado nesta rodada'))
                ui.label('Referência da etapa: '+atual['evidencia']).classes('text-sm')
                linked_files(atual)
                if atual['motivo']: ui.label('Ajustes / motivo: '+atual['motivo']).classes('text-sm text-amber-800')
            def dialog_etapa(action):
                with ui.dialog() as dialog, ui.card().classes('responsive-dialog-sm').style('padding: 20px;'):
                    ui.label(ACOES[action]).style('font-size: 22px; font-weight: bold; color: #1976d2;')
                    if fontes:
                        catalogue=fontes.catalogo()
                        email_options={key:f"{m['sent_date']} | {m['sender']} | {m['subject']}" for key,m in catalogue.items()}
                        file_options={str(a['id']):f"{a['name']} | {m['sent_date']} | {m['subject']}" for m in catalogue.values() for a in m['attachments']}
                        evidence=ui.select(email_options,label='E-mail que comprova esta etapa',with_input=True).classes('w-full')
                        apolice=ui.select(file_options,label='Anexo da apólice desta rodada',with_input=True).classes('w-full')
                        boleto=ui.select(file_options,label='Anexo do boleto correspondente',with_input=True).classes('w-full')
                        def preview_selected():
                            try:
                                ref=fontes.preparar('solicitacao',{'email_id':evidence.value})['vinculos']['evidencia']
                                open_mail(ref)
                            except (ValueError,PermissionError) as error: ui.notify(str(error),type='warning')
                        ui.button('Ler e-mail selecionado',on_click=preview_selected).props('flat dense')
                        if not email_options: ui.label('Nenhum e-mail elegível. Importe as mensagens e confirme/publice o vínculo com a obra.').classes('text-amber-800')
                    else:
                        evidence=ui.textarea('Referência do e-mail/documento (assunto, data, remetente ou identificador)').classes('w-full')
                        apolice=ui.input('Apólice: número, versão e nome do arquivo').classes('w-full')
                        boleto=ui.input('Boleto correspondente: identificação e nome do arquivo').classes('w-full')
                    reason=ui.textarea('Motivo / ajustes solicitados').classes('w-full')
                    apolice.set_visibility(action=='recebimento'); boleto.set_visibility(action=='recebimento')
                    reason.set_visibility(action in ('ajustes','nova_rodada','sem_resposta'))
                    if action=='sem_resposta':
                        ui.label('Selecione o e-mail de envio à CAIXA e justifique a liberação interna. Esta decisão não registra aprovação expressa do banco. Confira se a consulta de mensagens está atualizada.').classes('text-amber-800')
                    if action=='nova_rodada':
                        ui.label('A nova rodada começa sem OKs. As aprovações e os documentos anteriores permanecem no histórico.').classes('text-amber-800')
                    if action=='aceite':
                        ui.label('Informe a evidência do aceite do banco para a apólice indicada nesta rodada. Os dois OKs finais ainda serão confirmados separadamente.')
                    ui.label('Confira o conteúdo antes de registrar: o e-mail e os arquivos selecionados serão vinculados a esta obra e rodada.' if fontes else 'Nesta versão, os documentos e e-mails são identificados por referência; nenhum arquivo é anexado por este formulário.').classes('text-xs text-gray-600')
                    ui.label('Confira se a apólice, o boleto e o aceite pertencem a '+TIPOS_SEGURO.get(state.get('tipo'),'este seguro')+'. Um documento do outro seguro não libera este controle.').classes('text-sm text-amber-800')
                    def save():
                        try:
                            dados = dict(email_id=evidence.value,apolice_id=apolice.value,boleto_id=boleto.value,motivo=reason.value) if fontes else dict(evidencia=evidence.value,apolice=apolice.value,boleto=boleto.value,motivo=reason.value)
                            service.registrar_etapa(obra_id,action,dados,state['revisao'])
                            dialog.close(); painel.refresh()
                        except (ValueError,PermissionError) as error:
                            ui.notify(str(error),type='warning')
                    ui.button('Registrar etapa',on_click=save).props('unelevated color=primary')
                    ui.button('Cancelar',on_click=dialog.close).props('flat')
                dialog.open()
            actions = ['solicitacao'] if not atual else {
                'solicitado':['pedido'],'pedido':['recebimento'],'recebido':['envio','nova_rodada'],
                'analise':['ajustes','aceite','sem_resposta','nova_rodada'],'ajustes':['nova_rodada'],'aceito':['nova_rodada'],'sem_resposta':['nova_rodada']}[atual['etapa']]
            if can_edit:
                with ui.row().classes('w-full gap-2'):
                    for action in actions:
                        ui.button(ACOES[action],on_click=lambda a=action: dialog_etapa(a)).props('outline')
            ui.label('7. Validação final da apólice e do boleto desta rodada').classes('font-bold mt-3')
            with ui.row().classes('w-full gap-6'):
                for field, title in [('ok_seguro','OK Seguro'),('ok_boleto','OK Boleto')]:
                    with ui.column().classes('gap-1'):
                        check = ui.checkbox(title, value=bool(state[field]), on_change=lambda e, f=field: change(f,e.value))
                        if not can_edit or not atual or atual['etapa'] not in ('aceito','sem_resposta'): check.disable()
                        ui.label(title if state[field] else 'Pendente').classes('font-bold')
                        latest = next((h for h in state['historico'] if h['campo']==field and atual and h.get('rodada_id')==atual['id']),None)
                        if latest:
                            prefix = 'Validado por' if state[field] else 'Última alteração por'
                            ui.label(f"{prefix}: {latest['usuario_nome']}").classes('text-xs')
                            ui.label(data_local(latest['data_hora'])).classes('text-xs')
            if not can_edit:
                ui.label('Somente usuários autorizados podem alterar as validações.').classes('text-sm text-gray-600')
            ui.label('Para documentos corrigidos, cancelamento ou nova emissão, abra uma nova rodada. Os OKs anteriores não são transferidos.').classes('text-sm text-gray-600')
            ui.button('Atualizar situação', icon='refresh', on_click=painel.refresh).props('flat dense')
            with ui.expansion('Rodadas anteriores e versões dos documentos', icon='folder').classes('w-full'):
                for rodada in state['rodadas']:
                    with ui.card().classes('w-full'):
                        ui.label(f"Rodada {rodada['numero']} - {'ATUAL' if atual and rodada['id']==atual['id'] else 'SUBSTITUÍDA / HISTÓRICO'}").classes('font-bold')
                        ui.label(ETAPAS[rodada['etapa']])
                        ui.label('Apólice: '+(rodada['apolice'] or 'Não recebida'))
                        ui.label('Boleto: '+(rodada['boleto'] or 'Não recebido'))
                        ui.label('Referência: '+rodada['evidencia'])
                        linked_files(rodada)
                        ui.label(f"OK Seguro: {'Sim' if rodada['ok_seguro'] else 'Pendente'} • OK Boleto: {'Sim' if rodada['ok_boleto'] else 'Pendente'}")
            with ui.expansion('Histórico de validações', icon='history').classes('w-full'):
                for h in state['historico']:
                    if h['campo']=='leitura:email': continue
                    def label(value):
                        decoded = json.loads(value)
                        if isinstance(decoded,dict): return f"Rodada {decoded['numero']}: {ETAPAS[decoded['etapa']]} | Apólice: {decoded['apolice'] or 'pendente'} | Boleto: {decoded['boleto'] or 'pendente'} | Referência: {decoded['evidencia']}"
                        return ('OK' if decoded else 'Pendente') if type(decoded) is bool else ('Início' if decoded is None else str(decoded))
                    if fontes and h['campo'].startswith('rodada:'):
                        snapshot=json.loads(h['novo'])
                        links=json.loads(snapshot.get('vinculos') or '{}')
                        if links.get('evidencia'):
                            ui.button(f"E-mail • rodada {snapshot['numero']} • {data_local(h['data_hora'])}",on_click=lambda ref=links['evidencia']:open_mail(ref)).props('flat dense')
                    title = {'cotacao':'Cotação','ok_seguro':'Seguro','ok_boleto':'Boleto'}.get(h['campo'],h['campo'])
                    ui.label(f"{title}: {label(h['anterior'])} → {label(h['novo'])} | {h['usuario_nome']} | {data_local(h['data_hora'])}").classes('text-sm')
                if not state['historico']: ui.label('Nenhuma alteração registrada.')
            if state.get('legado'):
                with ui.expansion('Histórico anterior à separação dos seguros — somente consulta',icon='history').classes('w-full'):
                    ui.label('O tipo desses registros antigos não foi presumido. Os OKs antigos foram preservados aqui e não liberam nenhum dos dois controles novos.').classes('text-sm text-amber-800')
                    for old in state['legado']:
                        ui.label(f"Rodada antiga {old['numero']} • {ETAPAS.get(old['etapa'],old['etapa'])}")
                        ui.label('Apólice: '+(old['apolice'] or 'Não identificada'))
                        ui.label('Boleto: '+(old['boleto'] or 'Não identificado'))
                        ui.label('Referência: '+old['evidencia']).classes('text-sm')
                        ui.label(f"OK Seguro antigo: {bool(old['ok_seguro'])} • OK Boleto antigo: {bool(old['ok_boleto'])}")
                        linked_files(old)
    painel()
