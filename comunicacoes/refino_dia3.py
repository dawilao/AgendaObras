"""Reavaliação do Dia 3: contexto, privacidade e correções persistentes."""
import re
from .matching import normalized, ics, match_message
from .conversations import excerpt

def coordinator_counts(matches):
    """Indicadores visuais: confiança automática não substitui OK humano."""
    counts=dict(confirmed=0,placed=0,unassigned=0,spam=0,trash=0)
    for match in matches:
        bucket=match['bucket']
        if bucket in ('spam','trash'):counts[bucket]+=1
        elif not match.get('work'):counts['unassigned']+=1
        elif match.get('coordinator_ok'):counts['confirmed']+=1
        else:counts['placed']+=1
    return counts

def work_codes(value):
    """Identificadores explicitamente de IC/contrato; não extrai números de ATA/ARP."""
    text=normalized(value)
    found=ics(value)
    pattern=r'\b(?:IC|CONTRATO|INSTRUMENTO CONTRATUAL)(?:\s+(?:COM\s+GARANTIA|N[º°O.]?))*\s*[:#-]?\s*0*(\d{1,7})\s*[/.-]\s*(20\d{2})(?!\d)'
    found.update(f'{int(n):05d}/{year}' for n,year in re.findall(pattern,text))
    return found

def out_of_scope(message):
    subject=normalized(message.get('subject',''))
    text=subject+' '+normalized(excerpt(message.get('body','')))
    if re.search(r'(?:SENHA|CODIGO DE (?:ACESSO|VERIFICACAO)|TOKEN).{0,40}(?:ACESSO|ALTERAD|REDEFIN|TEMPORAR)|(?:ALTERAD|REDEFIN).{0,30}SENHA',text):
        return 'Aviso de acesso à conta; não é autorização de entrada na obra.'
    if work_codes(text) or re.search(r'\bART\b|ANOTACAO DE RESPONSABILIDADE',text):
        return None
    if re.search(r'WORKSHOP|WEBINAR|INSCREVA.SE|DESCADASTRAR|OFERTA IMPERDIVEL',text):
        return 'Divulgação ou evento; sem identificação de obra.'
    if re.search(r'CARTAO CORPORATIVO VEXPENSE|SEU VOO|VOO PARA|ALTERACAO DE DADOS CADASTRAIS|ARMARIO ARQUIVO GABINETE',text):
        return 'Aviso administrativo ou pessoal sem identificação de obra CAIXA.'
    return None

def classify(message, works, decision=None, reference_works=(), allow_out_of_scope=True):
    """allow_out_of_scope=False: o usuário já disse "não é spam"; só procura a obra."""
    if decision and decision.get('bucket'):
        reason=('OK coordenador encaixe · '+decision.get('validated_at','')+' · '+decision.get('validated_by','')) if decision.get('coordinator_ok') else 'Correção manual preservada.'
        return dict(bucket=decision['bucket'],work=decision.get('work'),reason=reason,safe=decision['bucket']=='work' and bool(decision.get('work')),coordinator_ok=bool(decision.get('coordinator_ok')))
    excluded=out_of_scope(message) if allow_out_of_scope else None
    if excluded: return dict(bucket='spam',work=None,reason=excluded,safe=False)
    subject=message['subject']
    # Normaliza apenas para identificação; preserva o assunto original exibido.
    codes=work_codes(subject)
    enriched=subject+' '+ ' '.join('IC '+c for c in sorted(codes))
    match=match_message(enriched,message['body'],works,reference_works)
    if match.status=='tecnico': return dict(bucket='spam',work=None,reason=match.reason,safe=False)
    # Cidade repetida não deve esconder o IC exato nem juntar cadastros distintos.
    named={w['id'] for w in works if any(re.search(r'(?<!\w)'+re.escape(normalized(a))+r'(?!\w)',normalized(subject)) for a in w['aliases'] if a.strip())}
    exact=[w for w in works if w.get('ic') in codes]
    if len(named)>1 and not codes:
        numbers=set(re.findall(r'\bIC\s*[:#-]?\s*0*(\d{1,7})(?!\d)',normalized(subject)))
        candidates=[w for w in works if w['id'] in named and w.get('ic') and str(int(w['ic'].split('/')[0])) in numbers]
        if len(numbers)==1 and len(candidates)==1 and not (set(reference_works)-{candidates[0]['id']}):
            return dict(bucket='pending',work=candidates[0]['id'],reason='Cidade com mais de uma obra: encaixe pelo número do IC no assunto; conferir o ano antes do OK.',safe=False)
    if match.status=='conflito' and len(named)>1 and len(codes)==1 and len(exact)==1 and exact[0]['id'] in named and not (set(reference_works)-{exact[0]['id']}):
        return dict(bucket='pending',work=exact[0]['id'],reason='Há obras na mesma cidade; encaixe pelo IC completo '+exact[0]['ic']+'. Conferir antes do OK.',safe=False)
    # Complemento: IC único no trecho atual, nunca só numa assinatura/citação antiga.
    if match.status=='revisar' and not work_codes(message['subject']):
        codes=work_codes(excerpt(message['body']))
        exact=[w for w in works if w['ic'] in codes and w['confirmed']]
        if len(codes)==1 and len(exact)==1:
            candidate=exact[0]['id']
            if not match.suggestion or match.suggestion==candidate:
                return dict(bucket='work',work=candidate,reason='IC completo no trecho atual e cadastro confirmado.',safe=True)
    if match.status=='vinculado':
        current=work_codes(excerpt(message['body']))
        expected=next(w['ic'] for w in works if w['id']==match.obra_id)
        if current and current!={expected}:
            return dict(bucket='pending',work=match.obra_id,reason='IC do corpo diverge da obra identificada.',safe=False)
        return dict(bucket='work',work=match.obra_id,reason=match.reason,safe=True)
    suggestion=match.suggestion
    if not suggestion:
        names=[w['id'] for w in works if any(re.search(r'(?<!\w)'+re.escape(normalized(a))+r'(?!\w)',normalized(message['subject'])) for a in w['aliases'] if a.strip())]
        if len(names)==1:suggestion=names[0]
    reason=match.reason
    if not suggestion:
        # Número sem ano nunca confirma vínculo: serve só para localizar a dúvida.
        codes=work_codes(message['subject'])
        candidates=[w for w in works if w['ic'] and any(c.split('/')[0]==w['ic'].split('/')[0] for c in codes)]
        if len(codes)==1 and len(candidates)==1:
            suggestion=candidates[0]['id']
            reason=f"Encaixe sugerido pelo número do IC; e-mail {next(iter(codes))}, cadastro {candidates[0]['ic']}. Conferir ano e grafia da obra."
    return dict(bucket='pending',work=suggestion,reason=reason,safe=False)
