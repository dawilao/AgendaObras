"""Regras conservadoras: o ano faz parte do IC; cidade sozinha apenas sugere."""
import re
import unicodedata
from dataclasses import dataclass


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value or '')
                   if not unicodedata.combining(c)).upper()


def ics(value):
    return {f'{int(n):05d}/{year}' for n, year in re.findall(
        r'\bIC\s*[:#-]?\s*0*(\d{1,7})\s*[/.-]\s*(20\d{2})\b', normalized(value))}


def clean_ic(value):
    found = ics('IC ' + value)
    if len(found) != 1 or not re.fullmatch(r'\s*\d{1,7}\s*[/.-]\s*20\d{2}\s*', value):
        raise ValueError('Informe o IC com número e ano, por exemplo 03738/2026.')
    return next(iter(found))


@dataclass
class Match:
    status: str
    obra_id: str | None
    reason: str
    suggestion: str | None = None


def match_message(subject, body, works, reference_works=()):
    text = normalized(subject)
    technical = re.match(r'^(LIDA:|READ:|DELIVERED:|CONFIRMACAO DE LEITURA)', text)
    if technical or ('TAREFAS EM ALERTA' in text and 'OBRA ' in text):
        return Match('tecnico', None, 'Recibo ou alerta automático; não gera tarefa.')
    found = ics(subject)
    names = {w['id'] for w in works if any(
        re.search(r'(?<!\w)' + re.escape(normalized(a)) + r'(?!\w)', text)
        for a in w['aliases'] if a.strip())}
    exact = {w['id'] for w in works if w['ic'] and w['ic'] in found}
    year_conflict = any(w['ic'] and any(i.split('/')[0] == w['ic'].split('/')[0]
                        and i != w['ic'] for i in found) for w in works)
    refs = set(reference_works)
    if len(found) > 1 or year_conflict or len(names) > 1 or len(exact | refs) > 1:
        return Match('conflito', None, 'Identificadores, anos ou obras divergentes; revisar.')
    if exact:
        wid = next(iter(exact))
        work = next(w for w in works if w['id'] == wid)
        if names and wid not in names:
            return Match('conflito', None, 'O nome da obra diverge do IC no assunto.')
        if work['confirmed']:
            return Match('vinculado', wid, 'IC completo no assunto e mapeamento confirmado.')
        return Match('revisar', None, 'IC candidato; confirme o cadastro da obra.', wid)
    if found:
        return Match('revisar', None, 'IC sem correspondência confirmada.', next(iter(names), None))
    if len(refs) == 1 and (not names or names == refs):
        wid = next(iter(refs))
        # Identificadores no corpo podem pertencer ao histórico citado: revisão obrigatória.
        body_ids = ics(body)
        known = next((w['ic'] for w in works if w['id'] == wid), None)
        if body_ids and body_ids != {known}:
            return Match('conflito', None, 'Conversa conhecida com IC divergente no corpo.')
        return Match('vinculado', wid, 'Resposta com cabeçalho de referência a mensagem vinculada.')
    if refs and names and refs != names:
        return Match('conflito', None, 'A conversa e o nome da obra apontam para obras diferentes.')
    if names:
        return Match('revisar', None, 'Nome no assunto; confirmar serviço e obra.', next(iter(names)))
    body_hits = {w['id'] for w in works if w['ic'] and w['ic'] in ics(body)}
    return Match('revisar', None, 'Sem identificação inequívoca no assunto.',
                 next(iter(body_hits)) if len(body_hits) == 1 else None)
