"""Encaixe por obra: o e-mail vai primeiro para a pasta provável; só o OK humano confirma.

Lê o MailStore sem alterá-lo. O estado vem das colunas que já existem:
  ignorado                 → lixeira pessoal (recuperável; nada é apagado na KingHost)
  spam                     → provável spam por decisão do usuário
  vinculado + reviewed     → vínculo seguro (OK do coordenador ou confirmação humana)
  revisar/conflito+reviewed→ correção manual preservada (realocado/restaurado), aguardando OK
  tecnico                  → avisos automáticos, tratados como hoje pela tela
  demais                   → refino_dia3.classify (encaixe automático ou provável spam)
"""
import json
import re
from email.utils import parseaddr

from .matching import normalized
from .refino_dia3 import classify

# Sem obra identificada nas duas pontas: 'unassigned' vai para "Obra a conferir".
BUCKETS = ('confirmed', 'placed', 'unassigned', 'spam', 'trash')

# Ícones por assunto (topic_label). Cores continuam indicando o remetente.
TOPIC_ICONS = {
    'Medições': 'straighten',
    'Relatórios': 'description',
    'Projetos': 'architecture',
    'Assinatura de contrato': 'draw',
    'Acesso à obra': 'meeting_room',
    'Seguro e garantia': 'verified_user',
    'Vistoria / início da obra': 'fact_check',
    'Outros assuntos: Faturamento': 'receipt_long',
    'Outros assuntos: Pagamento': 'payments',
    'Outros assuntos: Problema na obra': 'construction',
    'Outros assuntos: Atraso da obra': 'schedule',
    'Outros assuntos: Prazo da obra': 'event',
    'Outros assuntos: Orçamento': 'request_quote',
    'Outros assuntos: Materiais e entrega': 'local_shipping',
    'Outros assuntos: Aditivo contratual': 'post_add',
    'Outros assuntos: Documentação': 'folder_copy',
    'Outros assuntos: Agendamento': 'event_available',
    'Outros assuntos: Conclusão da obra': 'task_alt',
}

# Nome do estado ou cidade-sede no nome do contrato → UF. A ordem importa:
# "SERGIPE ALAGOAS" antes de "ALAGOAS"/"SERGIPE".
UF_POR_NOME = [
    ('SERGIPE ALAGOAS', 'SE/AL'), ('MINAS GERAIS', 'MG'), ('MATO GROSSO DO SUL', 'MS'),
    ('MATO GROSSO', 'MT'), ('RIO GRANDE DO SUL', 'RS'), ('RIO GRANDE DO NORTE', 'RN'),
    ('SANTA CATARINA', 'SC'), ('ESPIRITO SANTO', 'ES'), ('DISTRITO FEDERAL', 'DF'),
    ('RIO DE JANEIRO', 'RJ'), ('SAO PAULO', 'SP'), ('BAHIA', 'BA'), ('PIAUI', 'PI'),
    ('SERGIPE', 'SE'), ('ALAGOAS', 'AL'), ('PERNAMBUCO', 'PE'), ('PARAIBA', 'PB'),
    # "PARÁ" fica de fora: sem acento colide com a preposição "para".
    ('CEARA', 'CE'), ('MARANHAO', 'MA'), ('PARANA', 'PR'), ('AMAZONAS', 'AM'),
    ('AMAPA', 'AP'), ('RORAIMA', 'RR'), ('RONDONIA', 'RO'), ('ACRE', 'AC'), ('TOCANTINS', 'TO'),
    ('GOIAS', 'GO'), ('MANAUS', 'AM'), ('CURITIBA', 'PR'), ('NITEROI', 'RJ'), ('TUBARAO', 'SC'),
]
COR_UF = {'MG': '#8b5cf6', 'SC': '#0284c7', 'AL': '#d97706', 'PI': '#059669', 'BA': '#db2777',
          'SE': '#0d9488', 'SE/AL': '#0d9488', 'AM': '#65a30d', 'PR': '#2563eb', 'RJ': '#dc2626'}
COR_UF_PADRAO = '#64748b'

# Situação da obra (bucket de ObrasHelper.obter_bucket_grade) → (ícone, cor Quasar).
SITUACAO = {'concluido': ('check_circle', 'green'), 'atrasado': ('warning', 'red'),
            'em_andamento': ('schedule', 'orange')}
SITUACAO_A_CONFERIR = ('help_outline', 'grey')


def uf_contrato(cliente):
    """('MG', '8756.2025') a partir de 'C.E.F MINAS GERAIS - 8756.2025'. UF desconhecida → '?'."""
    text = normalized(cliente or '')
    uf = next((sigla for nome, sigla in UF_POR_NOME if re.search(r'(?<![A-Z])' + nome + r'(?![A-Z])', text)), '?')
    number = (cliente or '').rsplit(' - ', 1)[-1].strip() if ' - ' in (cliente or '') else (cliente or '').strip()
    return uf, number or 'Contrato a conferir'


def cor_uf(uf):
    return COR_UF.get(uf, COR_UF_PADRAO)


def _decisao(row):
    """Decisão humana já registrada no store (ou None para classificar)."""
    status = row['status']
    if status == 'ignorado':
        return dict(bucket='trash', work=None, reason=row.get('reason') or 'Na lixeira.', safe=False)
    if status == 'spam':
        return dict(bucket='spam', work=None, reason=row.get('reason') or 'Marcado como fora do escopo.', safe=False)
    if status == 'tecnico':
        work = row.get('obra_id') or row.get('suggestion')
        return dict(bucket='tecnico', work=work, reason=row.get('reason') or 'Evento automático.', safe=False)
    if row.get('reviewed') and status == 'vinculado' and row.get('obra_id'):
        return dict(bucket='work', work=row['obra_id'], reason=row.get('reason') or 'Encaixe confirmado.',
                    safe=True, coordinator_ok=True)
    if row.get('reviewed'):
        return dict(bucket='pending', work=row.get('suggestion'),
                    reason=row.get('reason') or 'Correção manual preservada.', safe=False)
    return None


def sender_address(row):
    return parseaddr(row.get('sender') or '')[1].strip().lower()


def _automatico(row, works, spam_senders, reference_works=()):
    """Classificação sem decisão humana. "Não é spam" (not_spam) vence o fora do escopo e a regra
    de remetente; a regra de remetente nunca vence um vínculo seguro por IC."""
    allow_spam = not row.get('not_spam')
    match = classify(row, works, None, reference_works, allow_out_of_scope=allow_spam)
    if (allow_spam and match['bucket'] != 'spam' and not match.get('safe')
            and sender_address(row) in spam_senders):
        return dict(bucket='spam', work=None, reason='Remetente marcado como fora do escopo.', safe=False)
    return match


def encaixar(rows, works, spam_senders=()):
    """{id da mensagem: encaixe}. Mensagens pendentes herdam a obra de respostas já seguras."""
    works = [dict(w, ic=w.get('ic') or '', aliases=w.get('aliases') or [], confirmed=bool(w.get('confirmed')))
             for w in works]
    spam_senders = set(spam_senders)
    matches, safe_refs = {}, {}
    for row in rows:
        match = _decisao(row) or _automatico(row, works, spam_senders)
        matches[row['id']] = match
        if match.get('safe') and row.get('message_id'):
            safe_refs[row['message_id']] = match['work']
    for row in rows:
        if matches[row['id']]['bucket'] == 'pending' and _decisao(row) is None:
            parents = {safe_refs[x] for x in json.loads(row.get('refs') or '[]') if x in safe_refs}
            if parents:
                matches[row['id']] = _automatico(row, works, spam_senders, parents)
    return matches


def categoria(match):
    """Contador em que o e-mail entra (um de BUCKETS); None para avisos automáticos."""
    bucket = match['bucket']
    if bucket == 'tecnico':
        return None
    if bucket in ('spam', 'trash'):
        return bucket
    if not match.get('work'):
        return 'unassigned'
    return 'confirmed' if match.get('coordinator_ok') else 'placed'


def contadores(matches):
    """Vinculadas (confirmed) só com OK humano; avisos automáticos ficam fora dos contadores."""
    counts = dict.fromkeys(BUCKETS, 0)
    for match in matches:
        key = categoria(match)
        if key:
            counts[key] += 1
    return counts


def avisos_por_obra(skipped, works):
    """Avisos de e-mails não importados → ({obra: [avisos]}, [sem obra]). Só organiza; não importa nada."""
    works = [dict(w, ic=w.get('ic') or '', aliases=w.get('aliases') or [], confirmed=bool(w.get('confirmed')))
             for w in works]
    by_work, unmatched = {}, []
    for item in skipped:
        if not (item.get('subject') or '').strip():
            unmatched.append(item)
            continue
        probe = dict(subject=item.get('subject') or '', body='', sender=item.get('sender') or '')
        work = classify(probe, works).get('work')
        if work:
            by_work.setdefault(str(work), []).append(item)
        else:
            unmatched.append(item)
    return by_work, unmatched
