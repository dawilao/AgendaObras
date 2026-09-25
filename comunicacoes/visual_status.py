"""Indicadores de leitura, sem alterar etapas, permissões ou aprovações."""
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from email.utils import getaddresses
from .matching import normalized
from .conversations import excerpt, topic_label

HEADER = {'red':'bg-red-50 text-red-800', 'yellow':'bg-amber-100 text-amber-900', 'green':'bg-green-100 text-green-900', 'blue':'bg-blue-100 text-blue-900', 'gray':'bg-slate-100 text-slate-700'}
ICONS = {'Acesso à obra':'meeting_room', 'Projetos':'architecture', 'Medições':'attach_money', 'Assinatura de contrato':'description'}

def sender_color(sender):
    """Classifica o endereço From, nunca o nome exibido ou texto encaminhado."""
    addresses=[a.strip().lower() for _,a in getaddresses([sender or ''])]
    domains=[a.rsplit('@',1)[1] for a in addresses if a.count('@')==1 and a.split('@')[0] and '.' in a.rsplit('@',1)[1]]
    if not domains:
        return 'gray'
    if len(domains)==1 and domains[0]=='caixa.gov.br':
        return 'blue'
    if len(domains)==1 and domains[0]=='machengenharia.com.br':
        return 'green'
    return 'yellow'

def readings_color(readings):
    latest=max(readings,key=lambda r:r['timestamp'],default=None)
    return sender_color(latest['source'].get('sender','')) if latest else 'gray'

def conversation_status(group):
    topic=topic_label(group['subject'],group.get('body',''))
    icon=ICONS.get(topic,'forum')
    if topic not in ICONS:
        return icon,'yellow','A conferir'
    if group.get('conflict'):
        return icon,'yellow','A conferir · divergência na conversa'
    # Só o trecho atual da mensagem mais recente; não toma citações antigas
    # nem o título isolado como confirmação de conclusão.
    body=normalized(excerpt(group.get('body','')))
    body=re.split(r'ATENCIOSAMENTE|CORDIALMENTE|\bATT\b',body)[0]
    noun={'Acesso à obra':r'ACESSO|ENTRADA|CREDENCIAMENTO', 'Projetos':r'PROJETO',
          'Medições':r'MEDICAO|BOLETIM', 'Assinatura de contrato':r'CONTRATO|ASSINATURA'}[topic]
    sentences=[s for s in re.split(r'[.!?;\n]',body) if re.search(noun,s)]
    addresses=[a.lower() for _,a in getaddresses([group.get('sender','')])]
    bank=any(a.endswith('@caixa.gov.br') for a in addresses)
    for s in sentences:
        if re.search(r'NAO (?:FOI |FORAM |ESTA |ESTAO |FOI AINDA )?(?:SOLICITAD|PEDID)',s):
            return icon,'red','Pendente · não solicitado'
        if re.search(r'REPROVAD|RECUSAD|INDEFERID|CORRIGIR|CORRECAO|AJUSTES? NECESSARI|FALTA |PENDENTE|NAO RECEB|NAO FOI RECEB|AGUARDAMOS (?:O |A )?(?:ENVIO|ASSINATURA)',s):
            return icon,'red','Pendente · '+{'Projetos':'recebimento ou correção do projeto','Acesso à obra':'regularizar solicitação de acesso','Medições':'envio ou correção da medição','Assinatura de contrato':'assinatura ou correção do contrato'}[topic]
    for s in sentences:
        if re.search(r'\bNAO\b|AGUARD|SOLICIT|FAVOR|PODER|SERA|PREVIST|\?',s):
            continue
        positive = r'ASSINADO POR (?:AMBAS|TODAS)|TODAS AS ASSINATURAS|CONTRATO DEVIDAMENTE ASSINADO' if topic=='Assinatura de contrato' else r'APROVAD|LIBERAD|AUTORIZAD'
        if bank and re.search(positive,s):
            if topic=='Acesso à obra':
                period=re.search(r'(\d{2}/\d{2}/\d{4})\s*(?:A|ATE|[-–])\s*(\d{2}/\d{2}/\d{4})',body)
                if not period:
                    return icon,'yellow','Liberação identificada · período a conferir'
                try:
                    start,end=[datetime.strptime(d,'%d/%m/%Y').date() for d in period.groups()]
                    today=datetime.now(ZoneInfo('America/Sao_Paulo')).date()
                    if start>end: raise ValueError('Período inválido')
                    if end<today:return icon,'red','Acesso vencido · solicitar renovação'
                    if start>today:return icon,'yellow','Acesso autorizado para período futuro'
                except ValueError:
                    return icon,'yellow','Liberação identificada · período a conferir'
            return icon,'green',{'Acesso à obra':'Liberação identificada · conferir período autorizado','Projetos':'Aprovação identificada','Medições':'Aprovação identificada · não indica pagamento','Assinatura de contrato':'Confirmação identificada · conferir assinaturas'}[topic]
    for s in sentences:
        if re.search(r'ENVIAMOS|ENCAMINHAMOS|SEGUE|SEGUEM|ENVIAD|ENCAMINHAD|RECEBEMOS|RECEBID|EM ANALISE|EM DISCUSSAO|SOLICITAMOS|SOLICITAD',s):
            return icon,'yellow',('Recebimento identificado · conferir' if re.search(r'RECEBEMOS|RECEBID',s) else 'Em tratamento · aguardando conclusão')
    return icon,'yellow','A conferir · situação não confirmada no último e-mail'

def insurance_color(state,title):
    if not state or 'Conferir sequência' in title:
        return 'yellow'
    if state.get('definitivo'):
        return 'green'
    current=state.get('atual')
    return 'yellow' if current and current.get('etapa')=='analise' else 'red'

def paint(folder,color):
    # Somente o cabeçalho recebe cor; a mensagem continua legível em fundo neutro.
    folder.props('header-class="'+HEADER[color]+'"')
