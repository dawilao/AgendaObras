"""Atualização voluntária por usuário. Credenciais somente na memória da operação."""
import threading
from .imap_reader import sync_mail

_active = {}
_guard = threading.Lock()


def register(owner):
    event = threading.Event()
    with _guard:
        _active.setdefault(str(owner), set()).add(event)
    return event


def unregister(owner, event):
    with _guard:
        events = _active.get(str(owner), set())
        events.discard(event)
        if not events:
            _active.pop(str(owner), None)


def disconnect_user(owner):
    with _guard:
        for event in _active.get(str(owner), ()):
            event.set()


def temporary_import(store, config, event, reader=sync_mail):
    try:
        return reader(store, config, cancel=event)
    finally:
        # Não persistir nem reutilizar em outra conexão. Não promete apagamento físico da RAM.
        config.password = ''
