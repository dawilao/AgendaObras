"""Anexos em disco, endereçados pelo sha256: cada conteúdo é gravado uma única vez.

A compactação é sempre sem perda: `get` devolve exatamente os bytes recebidos e confere o
sha256. No disco, cada conteúdo fica em um de três formatos:
  <sha>       bytes originais
  <sha>.xz    original comprimido com lzma
  <sha>.zipm  manifesto de ZIP; os trechos comprimidos grandes são blobs próprios
"""
import base64
import hashlib
import json
import lzma
import os
import tempfile
from pathlib import Path

from core.config import COMUNICACOES_COMPACTAR
from . import zipdedup

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
SUFFIXES = ('', '.xz', '.zipm')
MIN_XZ = 4 * 1024
# Amostra: janelas espalhadas pelo arquivo, para que um trecho atípico não decida sozinho.
WINDOWS, WINDOW = 8, 16 * 1024
# Manifestos podem citar outros manifestos (ZIP dentro de ZIP); o limite barra ciclos forjados.
MAX_DEPTH = 8
# Formatos que já chegam comprimidos (JPEG, PNG, GIF, DWG, 7z, RAR, gzip, ZIP): lzma não ganha nada.
_PACKED = (b'\xff\xd8\xff', b'\x89PNG', b'GIF8', b'AC10', b"7z\xbc\xaf'\x1c", b'Rar!', b'\x1f\x8b', b'PK\x03\x04')
_UNAVAILABLE = 'Arquivo do anexo indisponível no servidor.'


def default_root():
    return Path(os.getenv('AGENDA_MAIL_FILES_ROOT') or _PROJECT_ROOT / 'uploads' / 'comunicacoes')


def already_packed(data):
    return (data.startswith(_PACKED) or (data[:4] == b'RIFF' and data[8:12] == b'WEBP')
            or data[4:8] == b'ftyp')


def sample_ratio(data):
    """Quanto janelas espalhadas pelo arquivo encolhem com lzma; None quando nem vale tentar.
    Só o começo engana: PDFs costumam ter o cabeçalho em texto e o resto já comprimido."""
    if len(data) < MIN_XZ or already_packed(data):
        return None
    if len(data) <= WINDOWS * WINDOW:
        sample = data
    else:
        step = (len(data) - WINDOW) // (WINDOWS - 1)
        sample = b''.join(data[i * step:i * step + WINDOW] for i in range(WINDOWS))
    return len(lzma.compress(sample)) / len(sample)


def worth_xz(data):
    """Só vale comprimir o arquivo inteiro se a amostra encolher bem."""
    ratio = sample_ratio(data)
    return ratio is not None and ratio < 0.85


class BlobStore:
    def __init__(self, root, compact=None):
        self.root = Path(root).resolve()
        self.compact = COMUNICACOES_COMPACTAR if compact is None else compact

    def path(self, sha, suffix=''):
        if len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
            raise ValueError('Identificador de anexo inválido.')
        return self.root / sha[:2] / (sha + suffix)

    def exists(self, sha):
        return any(self.path(sha, suffix).exists() for suffix in SUFFIXES)

    def files(self):
        """(sha, sufixo, caminho) de cada arquivo gravado; temporários ficam de fora."""
        for path in self.root.glob('??/*'):
            sha, dot, suffix = path.name.partition('.')
            if len(sha) == 64 and path.is_file() and (dot + suffix) in SUFFIXES:
                yield sha, dot + suffix, path

    def put(self, data, nested=False):
        sha = hashlib.sha256(data).hexdigest()
        if not self._touch(sha):
            suffix, content = self._encode(data, nested)
            self._write(self.path(sha, suffix), content)
        return sha, len(data)

    def get(self, sha, depth=0):
        data = self._read(sha, depth)
        if data is None or hashlib.sha256(data).hexdigest() != sha:
            raise ValueError(_UNAVAILABLE)
        return data

    def compact_existing(self, sha):
        """Converte um blob gravado no formato original. Devolve o sufixo final ('' se ficou igual)."""
        raw = self.path(sha)
        data = self.get(sha)
        suffix, content = self._encode(data)
        if not suffix:
            return suffix
        target = self.path(sha, suffix)
        self._write(target, content)
        if self._decode(suffix, content) != data:
            target.unlink()
            raise ValueError(_UNAVAILABLE)
        # Só apaga o original depois de conferir a nova forma; até lá, `get` prefere o original.
        raw.unlink()
        return suffix

    def manifest_refs(self, sha):
        """Blobs de trechos citados por um manifesto de ZIP."""
        manifest = json.loads(lzma.decompress(self.path(sha, '.zipm').read_bytes()))
        return [part[1] for part in manifest['parts'] if part[0] == 'b']

    def _touch(self, sha):
        """Renova a data do arquivo já gravado: conteúdo reaproveitado não passa por órfão antigo."""
        found = False
        for suffix in SUFFIXES:
            try:
                os.utime(self.path(sha, suffix))
                found = True
            except FileNotFoundError:
                pass
            except OSError:  # Existe, só não deu para mudar a data.
                found = True
        return found

    def _encode(self, data, nested=False):
        if self.compact:
            parts = None if nested else zipdedup.split(data)
            if parts:
                manifest = []
                for is_blob, chunk in parts:
                    if is_blob:
                        manifest.append(['b', *self.put(chunk, nested=True)])
                    else:
                        manifest.append(['i', base64.b64encode(chunk).decode('ascii')])
                return '.zipm', lzma.compress(json.dumps({'v': 1, 'parts': manifest}).encode('utf-8'))
            if worth_xz(data):
                packed = lzma.compress(data)
                if len(packed) < 0.9 * len(data):
                    return '.xz', packed
        return '', data

    def _decode(self, suffix, content, depth=0):
        if suffix == '.xz':
            return lzma.decompress(content)
        if suffix == '.zipm':
            if depth >= MAX_DEPTH:
                raise ValueError(_UNAVAILABLE)
            manifest = json.loads(lzma.decompress(content))
            return b''.join(base64.b64decode(part[1], validate=True) if part[0] == 'i'
                            else self.get(part[1], depth + 1) for part in manifest['parts'])
        return content

    def _read(self, sha, depth):
        for suffix in SUFFIXES:
            try:
                content = self.path(sha, suffix).read_bytes()
            except OSError:
                continue
            try:
                return self._decode(suffix, content, depth)
            except (lzma.LZMAError, ValueError, KeyError, IndexError, TypeError):
                return None
        return None

    def _write(self, target, content):
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=target.parent, prefix='.tmp-')
        try:
            with os.fdopen(fd, 'wb') as file:
                file.write(content)
            os.replace(temp, target)
        except BaseException:
            try:
                os.unlink(temp)
            except OSError:
                pass
            raise
