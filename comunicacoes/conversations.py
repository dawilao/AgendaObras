"""Agrupamento de leitura: não apaga, vincula ou publica mensagens."""
import json
import re
from datetime import timezone
from email.utils import getaddresses, parsedate_to_datetime
from .matching import normalized, ics


def timestamp(row):
    try:
        dt = parsedate_to_datetime(row['sent_date'])
        return (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt).timestamp()
    except (ValueError, TypeError, OverflowError):
        return 0


def subject_key(subject):
    return re.sub(r'^(?:(?:RE|RES|RESPOSTA|ENC|FW|FWD)\s*:\s*)+', '',
                  normalized(subject).strip()).strip()


def excerpt(body):
    """Trecho literal antes do histórico citado; não é resumo interpretativo."""
    lines = []
    for line in (body or '').splitlines():
        stripped = line.strip()
        if (stripped.startswith('>') or re.match(r'^(?:Em .+ escreveu:|On .+ wrote:|De:|From:|[-_]{3,})', stripped, re.I)):
            break
        if stripped:
            lines.append(stripped)
    text = ' '.join(lines)
    return text[:450] + ('…' if len(text) > 450 else '')


def build_conversations(rows):
    rows = sorted(rows, key=lambda r: (timestamp(r), r['id']))
    parents = list(range(len(rows)))
    probable = set()
    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    def join(a, b):
        parents[root(b)] = root(a)
    tokens = {}
    for i, row in enumerate(rows):
        if row['status'] in ('tecnico', 'ignorado'):
            continue
        refs = json.loads(row.get('refs') or '[]')
        for token in set(refs + ([row['message_id']] if row.get('message_id') else [])):
            if token in tokens:
                join(i, tokens[token])
            tokens[token] = i
    # Sem cabeçalho suficiente, assunto idêntico (fora Re/Enc) + obra conhecida
    # e correspondentes coincidentes sugerem continuidade, sem confirmação automática.
    subjects = {}
    for i, row in enumerate(rows):
        if row['status'] in ('tecnico', 'ignorado', 'conflito'):
            continue
        work = row.get('obra_id') or row.get('suggestion')
        key = subject_key(row['subject'])
        sender = {a.lower() for _, a in getaddresses([row.get('sender') or '']) if a}
        recipients = {a.lower() for _, a in getaddresses([row.get('recipients') or '', row.get('cc') or '']) if a}
        if not work or not key:
            continue
        for j, previous_sender, previous_recipients in subjects.get((work, key), []):
            previous = rows[j]
            if abs(timestamp(row) - timestamp(previous)) > 45 * 86400:
                continue
            # A própria caixa em todos os destinatários não prova continuidade.
            peers = sender & previous_sender or (sender & previous_recipients and previous_sender & recipients)
            if peers and root(i) != root(j):
                join(i, j)
                probable.update((i, j))
        subjects.setdefault((work, key), []).append((i, sender, recipients))
    groups = {}
    for i, row in enumerate(rows):
        groups.setdefault(root(i), []).append((i, row))
    output = []
    for members in groups.values():
        messages = sorted([r for _, r in members], key=lambda r: (timestamp(r), r['id']), reverse=True)
        latest = messages[0]
        work_ids = {r.get('obra_id') or r.get('suggestion') for r in messages} - {None, ''}
        ic_ids = set().union(*(ics(r['subject']) for r in messages))
        conflict = any(r['status'] == 'conflito' for r in messages) or len(work_ids) > 1 or len(ic_ids) > 1
        inferred = any(i in probable for i, _ in members)
        files = {}
        for message in messages:
            for attachment in message.get('attachments', []):
                # Mesmo nome com bytes diferentes permanece em entradas separadas.
                item = files.setdefault(attachment['sha256'], {**attachment, 'origins': [], 'names': []})
                item['origins'].append({'mid': message['id'], 'subject': message['subject'], 'date': message['sent_date']})
                if attachment['name'] not in item['names']:
                    item['names'].append(attachment['name'])
        output.append({**latest, 'messages': messages, 'files': list(files.values()),
                       'message_count': len(messages), 'attachment_count': len(files),
                       'excerpt': excerpt(latest['body']), 'conflict': conflict,
                       'group_reason': 'Conferir divergência na conversa' if conflict else
                           ('Continuidade provável: assunto e correspondentes' if inferred else
                            ('Conversa identificada pelos cabeçalhos' if len(messages) > 1 else 'Mensagem isolada'))})
    return sorted(output, key=lambda r: (timestamp(r), r['id']), reverse=True)


def topic_label(subject, body=''):
    text = normalized(subject)
    # A ação principal precede os termos acessórios do assunto.
    if 'ASSINATURA' in text and 'CONTRAT' in text:
        return 'Assinatura de contrato'
    if 'ACESSO' in text or 'BIOMETRIA' in text:
        return 'Acesso à obra'
    if 'SEGURO' in text or 'GARANTIA' in text or 'APOLICE' in text or 'ENDOSSO' in text:
        return 'Seguro e garantia'
    if 'PROJETO' in text or 'MATERIAL TECNICO' in text:
        return 'Projetos'
    if re.search(r'\bAIO\b|VISTORIA', text):
        return 'Vistoria / início da obra'
    if 'MEDICAO' in text:
        return 'Medições'
    if 'RELATORIO' in text:
        return 'Relatórios'
    # Preserva os temas existentes. Para os demais, resume primeiro o assunto;
    # consulta apenas o trecho atual do corpo quando o assunto não esclarece.
    themes = [
        (r'FATURAMENTO|NOTA FISCAL|\bNF[SE]?\b', 'Faturamento'),
        (r'PAGAMENTO|COBRANCA|VENCIMENTO|BOLETO', 'Pagamento'),
        (r'INFILTRAC|VAZAMENTO|DEFEITO|PATOLOGIA|PROBLEMA|AVARIA|RETRABALHO', 'Problema na obra'),
        (r'ATRASO|PARALISAC|PARALISAD', 'Atraso da obra'),
        (r'CRONOGRAMA|PRAZO|PRORROGAC', 'Prazo da obra'),
        (r'ORCAMENTO|COTACAO|PROPOSTA', 'Orçamento'),
        (r'MATERIAL|FORNECIMENTO|ENTREGA', 'Materiais e entrega'),
        (r'ADITIVO|REAJUSTE', 'Aditivo contratual'),
        (r'DOCUMENTAC|DOCUMENTO|CERTIDAO', 'Documentação'),
        (r'REUNIAO|AGENDAMENTO', 'Agendamento'),
        (r'CONCLUSAO|ENCERRAMENTO', 'Conclusão da obra'),
    ]
    for candidate in (text, normalized(excerpt(body))):
        for pattern, label in themes:
            if re.search(pattern, candidate):
                return 'Outros assuntos: ' + label
    original = re.sub(r'^(?:(?:RE|RES|RESPOSTA|ENC|FW|FWD)\s*:\s*)+', '', subject or '', flags=re.I)
    original = ' '.join(original.split()).strip()
    return 'Outros assuntos: ' + ((original[:67] + '…') if len(original)>70 else original or 'Tema não identificado')
