"""MIME convertido em texto inerte. Nunca renderiza HTML de e-mail."""
import hashlib
import json
import re
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser

from core.config import COMUNICACOES_MAX_MB

MAX_MESSAGE = COMUNICACOES_MAX_MB * 1024 * 1024
OVERSIZE_HINT = 'Baixe os anexos direto no e-mail e salve no Drive.'


class PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        if tag in ('p', 'br', 'div', 'tr', 'li'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def parse_message(raw):
    if len(raw) > MAX_MESSAGE:
        raise ValueError(f'Mensagem excede o limite de {COMUNICACOES_MAX_MB} MB. {OVERSIZE_HINT}')
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    plain, html, attachments = [], [], []
    def parts(part):
        if part.get_filename() or part.get_content_disposition() == 'attachment':
            yield part
        elif part.is_multipart():
            for child in part.iter_parts():
                yield from parts(child)
        else:
            yield part
    for part in parts(msg):
        payload = part.get_payload(decode=True)
        if payload is None and part.get_content_type() == 'message/rfc822':
            nested = part.get_payload()
            payload = nested[0].as_bytes() if isinstance(nested, list) and nested else b''
        payload = payload or b''
        filename = part.get_filename()
        if filename or part.get_content_disposition() == 'attachment':
            # Nome é metadado: nunca é utilizado como caminho no disco.
            name = re.split(r'[/\\]', filename or 'anexo')[-1]
            name = re.sub(r'[\x00-\x1f\x7f]', '', name)[:180] or 'anexo'
            attachments.append({'name': name, 'type': part.get_content_type(),
                                'data': payload, 'sha': hashlib.sha256(payload).hexdigest()})
        elif part.get_content_type() in ('text/plain', 'text/html'):
            try:
                content = payload.decode(part.get_content_charset() or 'utf-8', errors='replace')
            except LookupError:
                content = payload.decode('utf-8', errors='replace')
            (plain if part.get_content_type() == 'text/plain' else html).append(content)
    if plain:
        body = '\n'.join(plain)
    else:
        reader = PlainHTML()
        reader.feed('\n'.join(html))
        body = ''.join(reader.parts)
    headers = {key: str(msg.get(name, '')) for key, name in
               [('subject', 'Subject'), ('sender', 'From'), ('recipients', 'To'),
                ('cc', 'Cc'), ('date', 'Date'), ('message_id', 'Message-ID')]}
    headers['body'] = body.replace('\r\n', '\n')
    headers['references'] = re.findall(r'<[^<>\s]+>',
                                     str(msg.get('References', '')) + ' ' + str(msg.get('In-Reply-To', '')))
    fingerprint = json.dumps({**headers, 'attachments': [(a['name'], a['sha']) for a in attachments]},
                             sort_keys=True, ensure_ascii=False).encode('utf-8')
    return {**headers, 'key': hashlib.sha256(fingerprint).hexdigest(), 'attachments': attachments}
