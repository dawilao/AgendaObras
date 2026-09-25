"""IMAP SSL em modo somente leitura, escopo explícito e retomada por UID."""
import imaplib
import json
import os
import re
import ssl
import threading
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .parser import MAX_MESSAGE
from .secrets import read_secret

_locks = {}
_locks_guard = threading.Lock()


class ImportCancelled(Exception):
    pass


def tls_context():
    """Verificação TLS completa, com as autoridades do sistema e as do certifi.

    No Windows o Python só enxerga as raízes já instaladas no repositório local; raízes
    que o Windows baixaria sob demanda (ex.: GlobalSign R6, usada pela KingHost) faltam
    e a verificação falha. O certifi completa a lista sem desligar a verificação.
    """
    context = ssl.create_default_context()
    try:
        import certifi
        context.load_verify_locations(cafile=certifi.where())
    except (ImportError, OSError):
        pass
    return context


@dataclass
class IMAPConfig:
    host: str
    username: str
    password: str = field(repr=False)
    folders: list[str] = field(default_factory=lambda: ['INBOX'])
    terms: list[str] = field(default_factory=list)
    since: str = '2026-01-01'
    port: int = 993
    batch: int = 100

    @classmethod
    def from_env(cls):
        password = os.getenv('AGENDA_IMAP_PASSWORD', '')
        secret_file = os.getenv('AGENDA_IMAP_PASSWORD_FILE', '')
        if secret_file:
            password = read_secret(secret_file)
        config = cls(os.getenv('AGENDA_IMAP_HOST', ''), os.getenv('AGENDA_IMAP_USER', ''), password,
                     json.loads(os.getenv('AGENDA_IMAP_FOLDERS', '["INBOX"]')),
                     json.loads(os.getenv('AGENDA_IMAP_TERMS', '[]')),
                     os.getenv('AGENDA_IMAP_SINCE', '2026-01-01'),
                     int(os.getenv('AGENDA_IMAP_PORT', '993')),
                     int(os.getenv('AGENDA_IMAP_BATCH', '100')))
        config.validate()
        return config

    def validate(self):
        if not self.host or not self.username or not self.password:
            raise ValueError('Configure servidor, usuário e credencial IMAP no servidor.')
        if not isinstance(self.folders, list) or not self.folders or not isinstance(self.terms, list) or not self.terms:
            raise ValueError('Defina pastas e termos explícitos para a consulta piloto.')
        for value in self.folders + self.terms:
            if not isinstance(value, str) or not value or any(ord(c) < 32 or ord(c) > 126 for c in value):
                raise ValueError('Use nomes IMAP de pastas e termos ASCII válidos (ex.: TUBAR).')
        date.fromisoformat(self.since)
        if not 1 <= self.batch <= 500 or not 1 <= self.port <= 65535:
            raise ValueError('Porta ou tamanho de lote inválido.')


def quote(value):
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def sync_mail(store, config, factory=imaplib.IMAP4_SSL, cancel=None):
    config.validate()
    with _locks_guard:
        lock = _locks.setdefault(store.path, threading.Lock())
    if not lock.acquire(blocking=False):
        return 'Já existe uma sincronização em execução.'
    def check_cancelled():
        if cancel is not None and cancel.is_set():
            raise ImportCancelled()
    client = None
    rid = None
    try:
        rid = store.start_run()
        check_cancelled()
        client = factory(config.host, config.port, ssl_context=tls_context(), timeout=30)
        check_cancelled()
        client.login(config.username, config.password)
        check_cancelled()
        count = new = skipped = 0
        remaining = False
        since = date.fromisoformat(config.since)
        month = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][since.month - 1]
        search_date = f'{since.day:02d}-{month}-{since.year}'
        for folder in config.folders:
            check_cancelled()
            status, _ = client.select(quote(folder), readonly=True)
            if status != 'OK':
                raise RuntimeError(f'Pasta "{folder}" indisponível nesta caixa; desmarque-a em "Pastas a consultar".')
            _, values = client.response('UIDVALIDITY')
            if not values or not values[0] or not values[0].isdigit():
                raise RuntimeError('Servidor não informou UIDVALIDITY válido.')
            validity = values[0].decode('ascii')
            all_uids = set()
            for term in config.terms:
                check_cancelled()
                status, data = client.uid('SEARCH', None, 'SINCE', search_date, 'SUBJECT', quote(term))
                if status != 'OK':
                    raise RuntimeError('Falha na pesquisa IMAP.')
                all_uids.update((data[0] or b'').split())
            for uid in sorted(all_uids, key=int):
                check_cancelled()
                source = (config.username, folder, validity, uid.decode('ascii'))
                if store.seen(source):
                    continue
                if count >= config.batch:
                    remaining = True
                    break
                status, meta = client.uid('FETCH', uid, '(RFC822.SIZE)')
                check_cancelled()
                size_match = re.search(rb'RFC822.SIZE\s+(\d+)', b' '.join(m for m in meta if isinstance(m, bytes)))
                if status != 'OK' or not size_match:
                    raise RuntimeError('Não foi possível verificar o tamanho de uma mensagem.')
                count += 1
                if int(size_match[1]) > MAX_MESSAGE:
                    store.skip(source, 'Excede 15 MB; requer importação por outro meio ou revisão do limite.')
                    skipped += 1
                    continue
                status, data = client.uid('FETCH', uid, '(BODY.PEEK[])')
                check_cancelled()
                if status != 'OK':
                    raise RuntimeError('Falha ao consultar mensagem.')
                payloads = [item[1] for item in data if isinstance(item, tuple) and isinstance(item[1], bytes)]
                if not payloads:
                    raise RuntimeError('Mensagem sem conteúdo na resposta IMAP.')
                try:
                    _, fresh = store.import_message(payloads[0], source)
                    new += int(fresh)
                except (ValueError, UnicodeError):
                    store.skip(source, 'Conteúdo inválido ou acima do limite; conferir manualmente.')
                    skipped += 1
        result = f'{new} novas; {skipped} fora do limite ou inválidas. Período desde {config.since} (data interna IMAP).'
        result += ' Há mais resultados: sincronize novamente.' if remaining else ' Consulta concluída no escopo configurado.'
        store.end_run(rid, 'parcial' if remaining or skipped else 'concluido', result)
        return result
    except ImportCancelled:
        result = 'Atualização interrompida. As mensagens já importadas permanecem no seu histórico privado.'
        if rid:
            store.end_run(rid, 'interrompido', result)
        return result
    except Exception as error:
        # Mensagens de servidor podem conter credenciais ou dados privados: não registrar o texto bruto.
        # Só os RuntimeError levantados acima (textos próprios, sem dados do servidor) são repassados.
        if isinstance(error, imaplib.IMAP4.error):
            detail = 'Falha de autenticação IMAP: confira o e-mail e a senha.'
        elif isinstance(error, RuntimeError):
            detail = str(error)
        elif isinstance(error, ssl.SSLCertVerificationError):
            detail = f'O certificado de {config.host} não pôde ser verificado; confira as autoridades certificadoras instaladas (pacote certifi).'
        elif isinstance(error, OSError):
            detail = f'Não foi possível conectar a {config.host}:{config.port}; confira a internet ou o firewall.'
        else:
            detail = 'Falha na consulta IMAP; verifique conexão, configuração e disponibilidade.'
        if rid:
            store.end_run(rid, 'falha', detail)
        raise RuntimeError(detail) from None
    finally:
        if client:
            try:
                client.logout()  # Sem CLOSE, EXPUNGE, STORE, APPEND ou envio SMTP.
            except Exception:
                pass
        lock.release()
