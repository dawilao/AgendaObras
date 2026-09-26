"""Compacta sem perda os anexos já gravados e remove arquivos órfãos.

    python -m comunicacoes.compactar            (simula: nada é alterado)
    python -m comunicacoes.compactar --aplicar  [--orfaos] [--forcar]

Cada anexo só perde o formato original depois que a nova forma é conferida byte a byte.
"""
import argparse
import time
from collections import Counter

from . import zipdedup
from .blobs import BlobStore, default_root, worth_xz
from .espaco import (ORPHAN_GRACE, OrphanScanError, attachment_rows, databases, default_mail_root,
                     file_size, locations, mb, orphans, remove, too_many)

FORMATS = {'': 'mantidos', '.xz': 'lzma', '.zipm': 'zip'}


def disk_usage(store):
    return sum(file_size(path) for _, _, path in store.files())


def compact(mail_root, files_root, apply=False, remove_orphans=False, force=False):
    store = BlobStore(files_root, compact=True)
    before = disk_usage(store)
    plan, failures = Counter(), []
    for sha, suffix, _ in list(store.files()):
        if suffix:
            continue
        try:
            if apply:
                plan[FORMATS[store.compact_existing(sha)]] += 1
                continue
            data = store.get(sha)
        except (OSError, ValueError) as error:
            failures.append(f'{sha}: {error}')
            continue
        plan['zip' if zipdedup.split(data) else 'lzma' if worth_xz(data) else 'mantidos'] += 1

    lines = locations(mail_root, store)
    lines.append(f'{"Resultado" if apply else "Simulação"}: ' +
                 (', '.join(f'{name} {count}' for name, count in sorted(plan.items())) or 'nada a compactar'))
    if apply:
        lines.append(f'Em disco: {mb(before)} -> {mb(disk_usage(store))}')
    else:
        lines.append(f'Em disco: {mb(before)}. Rode com --aplicar para compactar '
                     '(python -m comunicacoes.espaco estima a economia).')
    if remove_orphans:
        lines += clean_orphans(store, mail_root, apply, force, failures)
    lines += [f'FALHA {item}' for item in failures]
    return '\n'.join(lines), failures


def clean_orphans(store, mail_root, apply, force, failures):
    rows, unreadable = attachment_rows(databases(mail_root))
    if unreadable or not databases(mail_root):
        # Sem ler todos os bancos, arquivos em uso pareceriam órfãos: nunca apagar às cegas.
        failures.append(f'bancos ilegíveis ou ausentes em {mail_root}; órfãos não verificados')
        return []
    now = time.time()
    try:
        lost = orphans(store, {sha for sha, _ in rows}, now)
    except OrphanScanError as error:
        failures.append(f'órfãos não verificados: {error}')
        return []
    total = sum(1 for _ in store.files())
    if too_many(lost, total) and not force:
        failures.append(f'{len(lost)} de {total} arquivos parecem órfãos; confira se as pastas acima '
                        'são as do serviço (use --forcar só se tiver certeza)')
        return []
    size = sum(file_size(path) for path in lost)
    if not apply:
        return [f'Órfãos a remover: {len(lost)} ({mb(size)})']
    return [f'Órfãos removidos: {remove(lost, now - ORPHAN_GRACE)} de {len(lost)} ({mb(size)})']


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--aplicar', action='store_true', help='Grava as mudanças (sem isso, só simula).')
    parser.add_argument('--orfaos', action='store_true', help='Inclui arquivos sem referência há mais de 24 h.')
    parser.add_argument('--forcar', action='store_true',
                        help='Remove órfãos mesmo quando parecem demais (mais de 10 e de 20%% dos arquivos).')
    parser.add_argument('--bancos', help='Pasta com <usuario>/comunicacoes.db (padrão: AGENDA_MAIL_ROOT).')
    parser.add_argument('--arquivos', help='Pasta dos anexos (padrão: AGENDA_MAIL_FILES_ROOT).')
    args = parser.parse_args(argv)
    text, failures = compact(args.bancos or default_mail_root(), args.arquivos or default_root(),
                             args.aplicar, args.orfaos, args.forcar)
    print(text)
    raise SystemExit(1 if failures else 0)


if __name__ == '__main__':
    main()
