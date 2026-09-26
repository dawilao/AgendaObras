"""Anexos em disco, endereçados pelo sha256: cada conteúdo é gravado uma única vez."""
import hashlib
import os
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def default_root():
    return Path(os.getenv('AGENDA_MAIL_FILES_ROOT') or _PROJECT_ROOT / 'uploads' / 'comunicacoes')


class BlobStore:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def path(self, sha):
        if len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
            raise ValueError('Identificador de anexo inválido.')
        return self.root / sha[:2] / sha

    def put(self, data):
        sha = hashlib.sha256(data).hexdigest()
        target = self.path(sha)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temp = tempfile.mkstemp(dir=target.parent, prefix='.tmp-')
            try:
                with os.fdopen(fd, 'wb') as file:
                    file.write(data)
                os.replace(temp, target)
            except BaseException:
                try:
                    os.unlink(temp)
                except OSError:
                    pass
                raise
        return sha, len(data)

    def get(self, sha):
        try:
            data = self.path(sha).read_bytes()
        except OSError:
            raise ValueError('Arquivo do anexo indisponível no servidor.') from None
        if hashlib.sha256(data).hexdigest() != sha:
            raise ValueError('Arquivo do anexo indisponível no servidor.')
        return data
