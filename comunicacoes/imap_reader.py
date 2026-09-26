"""IMAP SSL em modo somente leitura, escopo explícito e retomada por UID."""
import imaplib
import json
import os
import re
import ssl
import threading
from dataclasses import dataclass, field
from datetime import date
from email import policy
from email.parser import BytesHeaderParser
from pathlib import Path

from .parser import MAX_MESSAGE, OVERSIZE_HINT
from .secrets import read_secret

_locks = {}
_locks_guard = threading.Lock()


class ImportCancelled(Exception):
    pass


class AuthFailed(RuntimeError):
    """O servidor recusou o login (e-mail ou senha)."""


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


# Escolhas pelo significado; o nome real de cada pasta é descoberto no servidor.
INBOX_KEY, SENT_KEY = 'inbox', 'sent'
FOLDER_LABELS = {INBOX_KEY: 'Caixa de entrada', SENT_KEY: 'Enviados'}
SENT_NAMES = ('SENT', 'SENT MESSAGES', 'SENT ITEMS', 'ENVIADOS', 'ITENS ENVIADOS', 'MENSAGENS ENVIADAS')
_LIST_LINE = re.compile(rb'^\((?P<flags>[^)]*)\)\s+(?P<delim>"(?:[^"\\]|\\.)*"|NIL)\s*(?P<name>.*)$', re.I)


def parse_list(response):
    """Resposta de LIST → [(nome, marcações)]. Nomes em UTF-7 modificado (ASCII)."""
    folders = []
    for item in response or []:
        literal = None
        if isinstance(item, tuple):
            item, literal = item[0], item[1]
        if not isinstance(item, bytes):
            continue
        match = _LIST_LINE.match(item.strip())
        if not match:
            continue
        raw = literal if literal is not None else match['name'].strip()
        if raw[:1] == b'"' and raw[-1:] == b'"':
            raw = re.sub(rb'\\(.)', rb'\1', raw[1:-1])
        name = raw.decode('ascii', errors='replace')
        if name:
            folders.append((name, set(match['flags'].decode('ascii', errors='replace').split())))
    return folders


def sent_folder(available):
    """Pasta de enviados: marcada como \\Sent pelo servidor ou, sem marcação, pelo nome."""
    for name, flags in available:
        if '\\sent' in {f.lower() for f in flags}:
            return name
    by_name = {re.split(r'[./]', name)[-1].strip().upper(): name for name, _ in available}
    return next((by_name[n] for n in SENT_NAMES if n in by_name), None)


def resolve_folders(requested, available):
    """Escolhas do usuário → ([(rótulo, nome real)], [rótulos não encontrados])."""
    names = {name for name, _ in available}
    resolved, missing, used = [], [], set()
    for choice in requested:
        if choice == INBOX_KEY or choice.upper() == 'INBOX':
            # INBOX existe sempre (RFC 3501), qualquer que seja a grafia devolvida pelo servidor.
            real = next((n for n in names if n.upper() == 'INBOX'), 'INBOX')
            label = FOLDER_LABELS[INBOX_KEY]
        elif choice == SENT_KEY:
            real = sent_folder(available)
            label = f'{FOLDER_LABELS[SENT_KEY]} ({real})' if real else FOLDER_LABELS[SENT_KEY]
        else:
            real = choice if choice in names else None
            label = choice
        if not real:
            missing.append(label)
        elif real not in used:
            used.add(real)
            resolved.append((label, real))
    return resolved, missing


def oversize_info(client, uid, size):
    """Só o cabeçalho (PEEK: não marca como lido) para o usuário localizar o e-mail na caixa."""
    info = {'size': size}
    try:
        status, data = client.uid('FETCH', uid, '(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])')
        raw = next((item[1] for item in data if isinstance(item, tuple) and isinstance(item[1], bytes)), b'')
        if status == 'OK' and raw:
            headers = BytesHeaderParser(policy=policy.default).parsebytes(raw)
            info.update(subject=str(headers.get('Subject', '')), sender=str(headers.get('From', '')),
                        date=str(headers.get('Date', '')))
    except Exception:
        pass  # Sem cabeçalho, o aviso mostra pasta e UID.
    return info


def oversize_note(size):
    return (f'E-mail com {size / 1024 / 1024:.1f} MB, acima do limite de {MAX_MESSAGE // 1024 // 1024} MB. '
            f'Os anexos não foram importados. {OVERSIZE_HINT}')


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
    logged_in = False
    try:
        rid = store.start_run()
        check_cancelled()
        client = factory(config.host, config.port, ssl_context=tls_context(), timeout=30)
        check_cancelled()
        client.login(config.username, config.password)
        logged_in = True
        check_cancelled()
        status, listing = client.list()
        if status != 'OK':
            raise RuntimeError('Não foi possível listar as pastas desta caixa.')
        available = parse_list(listing)
        store.save_folders(config.username, available)
        folders, missing = resolve_folders(config.folders, available)
        if not folders:
            raise RuntimeError('Nenhuma das pastas escolhidas existe nesta caixa; confira "Pastas a consultar".')
        consulted = []
        count = new = skipped = oversized = 0
        remaining = False
        since = date.fromisoformat(config.since)
        month = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][since.month - 1]
        search_date = f'{since.day:02d}-{month}-{since.year}'
        for label, folder in folders:
            check_cancelled()
            status, _ = client.select(quote(folder), readonly=True)
            if status != 'OK':
                # Pula a pasta e segue com as demais, em vez de interromper a atualização.
                missing.append(label)
                continue
            consulted.append(label)
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
                size = int(size_match[1])
                if size > MAX_MESSAGE:
                    store.skip(source, oversize_note(size), oversize_info(client, uid, size))
                    oversized += 1
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
        result = f'{new} novas; {skipped} inválidas.'
        if oversized:
            result += f' {oversized} acima de {MAX_MESSAGE // 1024 // 1024} MB (veja "E-mails não importados").'
        result += f' Pastas consultadas: {", ".join(consulted) or "nenhuma"}.'
        if missing:
            result += f' Não encontradas: {", ".join(missing)} (consulta seguiu com as demais).'
        result += f' Período desde {config.since} (data interna IMAP).'
        result += ' Há mais resultados: sincronize novamente.' if remaining else ' Consulta concluída no escopo configurado.'
        store.end_run(rid, 'parcial' if remaining or skipped or oversized or missing else 'concluido', result)
        return result
    except ImportCancelled:
        result = 'Atualização interrompida. As mensagens já importadas permanecem no seu histórico privado.'
        if rid:
            store.end_run(rid, 'interrompido', result)
        return result
    except Exception as error:
        # Mensagens de servidor podem conter credenciais ou dados privados: não registrar o texto bruto.
        # Só os RuntimeError levantados acima (textos próprios, sem dados do servidor) são repassados.
        if isinstance(error, imaplib.IMAP4.error) and not logged_in:
            detail = 'Falha de autenticação IMAP: confira o e-mail e a senha.'
            if rid:
                store.end_run(rid, 'falha', detail)
            raise AuthFailed(detail) from None
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
