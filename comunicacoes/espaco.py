"""Relatório de espaço dos anexos das Comunicações. Somente leitura.

    python -m comunicacoes.espaco

Mostra o que está em disco, por tipo, e quanto a compactação sem perda
(`python -m comunicacoes.compactar`) ainda pode economizar.
"""
import argparse
import hashlib
import math
import sqlite3
import time
from collections import defaultdict
from contextlib import closing
from pathlib import Path

from . import zipdedup
from .blobs import SUFFIXES, BlobStore, default_root, sample_ratio

ORPHAN_GRACE = 24 * 3600
# Órfãos demais indicam pastas erradas (ex.: shell sem as variáveis do serviço), não lixo.
MAX_ORPHANS = 10
MAX_ORPHAN_SHARE = 0.2
_KINDS = ((b'PK\x03\x04', 'zip'), (b'%PDF', 'pdf'), (b'AC10', 'dwg'),
          (b'\xff\xd8\xff', 'jpeg'), (b'\x89PNG', 'png'))


class OrphanScanError(Exception):
    """Não dá para saber com segurança o que está em uso: nada deve ser apagado."""


def kind(data):
    return next((name for magic, name in _KINDS if data.startswith(magic)), 'outros')


def default_mail_root():
    from .runtime import mail_root
    return mail_root()


def databases(mail_root):
    return sorted(Path(mail_root).glob('*/comunicacoes.db'))


def file_size(path):
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def file_mtime(path):
    """Arquivo removido durante a varredura conta como recente: nunca entra na limpeza."""
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return math.inf


def attachment_rows(db_paths):
    """(sha256, tamanho) de cada anexo, sem abrir os bancos para escrita, e os bancos que não
    puderam ser lidos (ex.: formato antigo, com o anexo guardado dentro do banco)."""
    rows, unreadable = [], []
    for path in db_paths:
        try:
            with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as db:
                # Excluído de vez não segura o arquivo; na lixeira, sim (pode ser restaurado).
                purged = 'purged_at' in {r[1] for r in db.execute('PRAGMA table_info(attachments)')}
                rows.extend(db.execute('SELECT sha256, size FROM attachments' +
                                       (' WHERE purged_at IS NULL' if purged else '')).fetchall())
        except sqlite3.Error:
            unreadable.append(path)
    return rows, unreadable


def reachable(store, roots):
    """Anexos citados pelos bancos mais os trechos citados pelos manifestos de ZIP."""
    seen, pending = set(), list(roots)
    while pending:
        sha = pending.pop()
        if sha in seen:
            continue
        seen.add(sha)
        if store.path(sha, '.zipm').exists():
            try:
                pending.extend(store.manifest_refs(sha))
            except Exception as error:
                # Sem saber o que o manifesto cita, os trechos dele pareceriam órfãos.
                raise OrphanScanError(f'manifesto ilegível {sha} ({type(error).__name__})') from error
    return seen


def orphans(store, roots, now=None, grace=ORPHAN_GRACE):
    """Arquivos sem referência (e temporários esquecidos) mais antigos que a carência."""
    limit = (now or time.time()) - grace
    alive = reachable(store, roots)
    found = [path for sha, _, path in store.files() if sha not in alive]
    found += store.root.glob('??/.tmp-*')
    return [path for path in found if file_mtime(path) < limit]


def too_many(lost, total):
    return len(lost) > max(MAX_ORPHANS, MAX_ORPHAN_SHARE * total)


def remove(paths, limit):
    """Apaga conferindo a data de novo: um arquivo reaproveitado desde a varredura fica."""
    removed = 0
    for path in paths:
        if file_mtime(path) < limit:
            try:
                path.unlink()
                removed += 1
            except FileNotFoundError:
                pass
    return removed


def release(store, shas, db_paths, now=None, grace=ORPHAN_GRACE):
    """Tira do disco os conteúdos informados (e os trechos dos seus ZIPs) que nenhum anexo ativo usa.
    Conteúdo gravado ou reaproveitado há menos que a carência fica para a próxima rodada."""
    rows, unreadable = attachment_rows(db_paths)
    if unreadable or not db_paths:
        raise OrphanScanError('bancos ilegíveis ou ausentes')
    alive = reachable(store, {sha for sha, _ in rows})
    candidates = reachable(store, set(shas))
    paths = [store.path(sha, suffix) for sha in candidates - alive for suffix in SUFFIXES]
    return remove([path for path in paths if path.exists()], (now or time.time()) - grace)


def locations(mail_root, store):
    return [f'Bancos em: {Path(mail_root).resolve()}', f'Anexos em: {store.root}']


def report(mail_root, files_root):
    store = BlobStore(files_root)
    rows, unreadable_dbs = attachment_rows(databases(mail_root))
    roots = {sha for sha, _ in rows}
    lines = locations(mail_root, store)
    lines.append(f'Bancos: {len(databases(mail_root))}  |  anexos: {len(rows)}  |  '
                 f'tamanho recebido: {mb(sum(size for _, size in rows))}')
    lines += [f'ATENÇÃO: banco sem a coluna sha256 (formato antigo?) ignorado: {path}' for path in unreadable_dbs]

    on_disk = defaultdict(lambda: [0, 0])
    forms = defaultdict(set)
    for sha, suffix, path in store.files():
        on_disk[suffix or 'original'][0] += 1
        on_disk[suffix or 'original'][1] += file_size(path)
        forms[sha].add(suffix)
    lines.append(f'Em disco: {mb(sum(v[1] for v in on_disk.values()))}')
    lines += [f'  {name:<9} {count:>6} arquivos  {mb(size)}' for name, (count, size) in sorted(on_disk.items())]

    by_kind = defaultdict(lambda: [0, 0])
    stored = set(forms)
    zip_saving = xz_saving = unreadable = 0
    for sha, suffixes in forms.items():
        if sha not in roots:
            continue
        try:
            data = store.get(sha)
        except ValueError:
            unreadable += 1
            continue
        by_kind[kind(data)][0] += 1
        by_kind[kind(data)][1] += len(data)
        if suffixes != {''}:
            continue
        parts = zipdedup.split(data)
        if parts:
            for is_blob, chunk in parts:
                if not is_blob:
                    continue
                chunk_sha = hashlib.sha256(chunk).hexdigest()
                if chunk_sha in stored:
                    zip_saving += len(chunk)
                stored.add(chunk_sha)
            continue
        ratio = sample_ratio(data)
        if ratio is not None and ratio < 0.85:
            xz_saving += int(len(data) * (1 - ratio))
    lines.append('Por tipo (conteúdo único):')
    lines += [f'  {name:<7} {count:>6} arquivos  {mb(size)}' for name, (count, size) in
              sorted(by_kind.items(), key=lambda item: -item[1][1])]
    lines.append(f'Economia ainda possível: ZIPs {mb(zip_saving)} (trechos repetidos)  |  '
                 f'lzma ~{mb(xz_saving)} (estimativa por amostras)')
    if unreadable_dbs:
        lines.append('Órfãos: não verificados enquanto houver banco ilegível.')
    else:
        try:
            lost = orphans(store, roots)
        except OrphanScanError as error:
            lines.append(f'Órfãos: não verificados: {error}.')
        else:
            lines.append(f'Órfãos com mais de 24 h: {len(lost)} ({mb(sum(file_size(p) for p in lost))})')
            if too_many(lost, sum(count for count, _ in on_disk.values())):
                lines.append('ATENÇÃO: órfãos demais. Confira se as pastas acima são as do serviço.')
    if unreadable:
        lines.append(f'ATENÇÃO: {unreadable} anexo(s) ilegível(is) ou adulterado(s).')
    return '\n'.join(lines)


def mb(size):
    return f'{size / 1024 / 1024:.1f} MB'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--bancos', help='Pasta com <usuario>/comunicacoes.db (padrão: AGENDA_MAIL_ROOT).')
    parser.add_argument('--arquivos', help='Pasta dos anexos (padrão: AGENDA_MAIL_FILES_ROOT).')
    args = parser.parse_args(argv)
    print(report(args.bancos or default_mail_root(), args.arquivos or default_root()))


if __name__ == '__main__':
    main()
