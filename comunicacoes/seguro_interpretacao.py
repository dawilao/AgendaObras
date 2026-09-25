"""Leitura local e determinística de evidências; nunca concede OKs financeiros.

Somente o trecho atual é classificado. Encaminhamentos completos têm origem
explicitamente indicada e não são usados como aceite expresso automático.
Não executa instruções do corpo, não envia dados a serviços externos.
"""
import re
from email.utils import getaddresses, parsedate_to_datetime
from .matching import normalized, ics

VERSION = 'regras-locais-2-tipos'
TITULOS = {
    'solicitacao': 'Solicitação do seguro pela CAIXA',
    'pedido': 'Pedido / tratativa com a seguradora',
    'recebimento': 'Apólice e boleto recebidos',
    'envio': 'Apólice enviada à CAIXA',
    'ajustes': 'Pedido de alteração identificado',
    'aceite': 'Aceite expresso identificado — conferir versão dos documentos',
    'revisar': 'Mensagem de seguro precisa de conferência',
}


def addresses(value):
    return [a.lower() for _, a in getaddresses([value or ''])]


def domain(value, suffix):
    return any(a.rsplit('@', 1)[-1] == suffix for a in addresses(value))


def trecho_atual(message):
    body=message.get('body') or ''
    sender=message.get('sender') or ''
    forwarded=False
    # Formato de encaminhamento completo observado no piloto. Não explorar
    # arbitrariamente cada citação antiga dentro de uma resposta recente.
    if re.match(r'^\s*-+\s*Mensagem original\s*-+', body, re.I):
        match=re.search(r'(?ims)^\s*DE:\s*(.*?)^\s*PARA:\s*.*?\n\s*\n',body)
        if match:
            sender=match.group(1).strip()
            body=body[match.end():]
            forwarded=True
    body=re.split(r'(?im)^\s*(?:>.*|Em\s+.{0,220}escreveu:|On\s+.{0,220}wrote:|De:|From:|Atenciosamente\b|##\s*INFORMA)',body)[0]
    return body.strip(),sender,forwarded


def tipos_no_texto(value):
    text=' '.join(normalized(value).split())
    tipos=[]
    if re.search(r'SEGURO[ -]+GARANTIA|GARANTIA CONTRATUAL|ASSINATURA.{0,60}COM GARANTIA',text): tipos.append('garantia')
    if re.search(r'RISCO[S]? DE ENGENHARIA|RESPONSABILIDADE CIVIL|\bRE\s*[/&-]\s*RC\b|SEGURO (?:DA|DE) OBRA',text): tipos.append('obra')
    return tipos


def tipos_mensagem(message):
    body,_,_=trecho_atual(message)
    explicit=tipos_no_texto(body+' '+message.get('subject','')+' '+' '.join(a['name'] for a in message.get('attachments',[])))
    context=message.get('_tipos_conversa',[])
    return explicit or (context if len(context)==1 else [])


def interpretar(message, work):
    body,sender,forwarded=trecho_atual(message)
    text=' '.join(normalized(body).split())
    subject=normalized(message.get('subject',''))
    types=tipos_mensagem(message)
    if not types and not re.search(r'\b(SEGUROS?|APOLICES?|ENDOSSO|GARANTIA)\b',text+' '+subject+' '+' '.join(normalized(a['name']) for a in message.get('attachments',[]))):
        return None
    action='revisar'; reason='O texto não permite identificar uma etapa com segurança.'
    bank=domain(sender,'caixa.gov.br')
    mach=domain(sender,'machengenharia.com.br')
    recipients=(message.get('recipients') or '')+', '+(message.get('cc') or '')
    # Negação e pedido de correção têm prioridade sobre palavras de aprovação.
    correction=re.search(r'NAO (?:ESTA |ESTAO |FOI |FORAM )?APROVAD|NAO ATENDE|APOLICE CORRIGIDA|(?:SOLICIT|PEDIM|NECESSARI|REITERAMOS).{0,140}(?:CORRECAO|CORRIGIR|RETIFIC|AJUST|REVISAO|ENDOSSO)|(?:CORRECAO|RETIFICACAO).{0,70}(?:APOLICE|SEGURO)',text)
    acceptance=re.search(r'(?:APOLICES?|SEGUROS?|DOCUMENTOS?).{0,60}(?:ESTA[O]? |FOI |FORAM |ENCONTRA.SE )?(?:APROVAD[AO]S?|ACEIT[AO]S?)\b|(?:APROVAMOS|VALIDAMOS|ACEITAMOS).{0,60}(?:APOLICE|SEGURO)',text)
    conditional=re.search(r'\b(SE |CASO |APOS |PARA APROVACAO|AGUARD|NAO |AINDA |PENDENTE|PODERA|DEVERA)',text)
    request=re.search(r'OBRIGATORIEDADE DE APRESENTACAO|SOLICITAMOS.{0,100}(?:ENVIO|EMISSAO|APRESENTACAO)|REITERAMOS A SOLICITACAO|CONTRATO ASSINADO DEVERA VIR ACOMPANHADO DA GARANTIA',text)
    sent=re.search(r'\b(?:SEGUE[M]?|ENCAMINHAMOS|ENVIAMOS)\b[^.!?]{0,180}(?:APOLICE|SEGURO)',text)
    if re.search(r'SEGURO.{0,40}(?:EM CONFECCAO|SERA ENVIADO|AINDA NAO)|NAO (?:ENVIAMOS|ENCAMINHAMOS)',text): sent=None
    if bank and correction:
        action='ajustes'; reason='A CAIXA solicita correção ou informa que o documento não atende.'
    elif bank and acceptance and not conditional and not forwarded:
        action='aceite'; reason='Há declaração expressa de aceite no trecho atual da mensagem da CAIXA.'
    elif bank and request:
        action='solicitacao'; reason='A CAIXA pede apresentação ou emissão do seguro.'
    elif mach and sent and domain(recipients,'caixa.gov.br'):
        action='envio'; reason='A MACH informa envio da apólice, com a CAIXA entre os destinatários.'
    elif mach and re.search(r'(?:ENCAMINHAD[AO]S?|ENVIAD[AO]S?).{0,45}SEGURADORA|SOLICITAMOS.{0,65}(?:EMISSAO|COTACAO)',text):
        action='pedido'; reason='O trecho atual informa pedido ou encaminhamento à seguradora.'
    files=message.get('attachments',[])
    policies=[a for a in files if re.search(r'APOLICE',normalized(a['name'])) and a['name'].lower().endswith('.pdf')]
    bills=[a for a in files if re.search(r'BOLETO',normalized(a['name'])) and a['name'].lower().endswith('.pdf')]
    if action=='revisar' and not bank and not mach and sent and len(policies)==1 and len(bills)==1:
        action='recebimento'; reason='A mensagem anuncia envio e contém um PDF de apólice e um PDF de boleto.'
    # Associação direta: não usar apenas a pertença provável à conversa.
    evidence_text=subject+' '+text
    aliases=[normalized(a) for a in work.get('aliases',[]) if a.strip()]
    codes=ics(evidence_text)
    for num,year in re.findall(r'\b(?:CONTRATO|IC|CT)(?: COM GARANTIA)?\s*(?:N[Oº°.]?\s*)?[-:]?\s*(\d{1,6})\s*/\s*(20\d{2})',evidence_text):
        codes.add(num.zfill(5)+'/'+year)
    direct=any(re.search(r'(?<!\w)'+re.escape(a)+r'(?!\w)',evidence_text) for a in aliases)
    if work.get('ic'):
        direct=direct or work['ic'] in codes
        wrong_year=any(c.split('/')[0]==work['ic'].split('/')[0] and c!=work['ic'] for c in codes)
    else: wrong_year=False
    review=action=='revisar' or not direct or wrong_year or message.get('status')=='conflito'
    if not direct: reason='Obra identificada apenas pela conversa; conferir vínculo. '+reason
    if wrong_year or message.get('status')=='conflito': reason='Divergência de identificação da obra/IC. '+reason
    if message.get('_tipos_conversa') and not tipos_no_texto(body+' '+message.get('subject','')+' '+' '.join(a['name'] for a in files)) and types:
        reason='Tipo identificado pelo contexto da conversa, com uma única modalidade. '+reason
    try:
        date=parsedate_to_datetime(message['sent_date'])
        if date.tzinfo is None: raise ValueError()
        stamp=date.timestamp()
    except (KeyError,TypeError,ValueError,OverflowError):
        stamp=0; review=True; reason='Data da mensagem inválida; conferir. '+reason
    return dict(action=action,title=TITULOS[action],reason=reason,review=review,
                excerpt=body[:900],timestamp=stamp,forwarded=forwarded,
                email_id=str(message['id']),fingerprint=message['fingerprint'],version=VERSION,types=types,
                apolice_id=str(policies[0]['id']) if len(policies)==1 else None,
                boleto_id=str(bills[0]['id']) if len(bills)==1 else None)
