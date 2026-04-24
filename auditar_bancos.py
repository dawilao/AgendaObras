"""
Auditoria de bancos para deploy Linux do AgendaObras.

Valida:
- integridade SQLite
- status de migrações
- formato de datas
- consistência entre agendaobras.db e contratos.db

Uso:
python auditar_bancos.py --agenda-db /srv/agenda/agendaobras.db --contratos-db /srv/agenda/contratos.db --users-db /srv/agenda/users.db
"""

import argparse
import json
import os
import sqlite3
import sys
from typing import Dict, List, Tuple

EXPECTED_LATEST_MIGRATION = 9


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    return cursor.fetchone() is not None


def _integrity_check(db_path: str) -> Tuple[bool, str]:
    try:
        conn = _connect(db_path)
        cursor = conn.cursor()
        cursor.execute('PRAGMA integrity_check')
        row = cursor.fetchone()
        conn.close()
        value = row[0] if row else 'unknown'
        return value == 'ok', str(value)
    except Exception as e:
        return False, f'erro: {e}'


def _agenda_checks(agenda_db: str) -> Dict:
    result = {
        'integrity_ok': False,
        'integrity_msg': '',
        'migrations_count': 0,
        'migrations_max': 0,
        'migrations_pending': None,
        'invalid_dates_count': 0,
        'checklist_fk_orphans': 0,
    }

    integrity_ok, integrity_msg = _integrity_check(agenda_db)
    result['integrity_ok'] = integrity_ok
    result['integrity_msg'] = integrity_msg

    conn = _connect(agenda_db)
    cursor = conn.cursor()

    if _table_exists(conn, 'schema_migrations'):
        cursor.execute('SELECT COUNT(*) AS total, COALESCE(MAX(version), 0) AS maxv FROM schema_migrations')
        row = cursor.fetchone()
        result['migrations_count'] = int(row['total'])
        result['migrations_max'] = int(row['maxv'])
        result['migrations_pending'] = max(0, EXPECTED_LATEST_MIGRATION - result['migrations_max'])

    if _table_exists(conn, 'obras'):
        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM obras
            WHERE (data_inicio IS NOT NULL AND TRIM(data_inicio) != '' AND data_inicio NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]')
               OR (data_assinatura IS NOT NULL AND TRIM(data_assinatura) != '' AND data_assinatura NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]')
               OR (data_aio IS NOT NULL AND TRIM(data_aio) != '' AND data_aio NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]')
               OR (data_acionamento IS NOT NULL AND TRIM(data_acionamento) != '' AND data_acionamento NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]')
            """
        )
        result['invalid_dates_count'] = int(cursor.fetchone()['total'])

    if _table_exists(conn, 'obra_checklist') and _table_exists(conn, 'obras'):
        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM obra_checklist oc
            LEFT JOIN obras o ON o.id = oc.obra_id
            WHERE o.id IS NULL
            """
        )
        result['checklist_fk_orphans'] = int(cursor.fetchone()['total'])

    conn.close()
    return result


def _contratos_checks(contratos_db: str) -> Dict:
    result = {
        'integrity_ok': False,
        'integrity_msg': '',
        'has_contratos': False,
        'has_contrato_usuarios': False,
        'vinculos_orfaos': 0,
    }

    integrity_ok, integrity_msg = _integrity_check(contratos_db)
    result['integrity_ok'] = integrity_ok
    result['integrity_msg'] = integrity_msg

    conn = _connect(contratos_db)
    cursor = conn.cursor()

    result['has_contratos'] = _table_exists(conn, 'contratos')
    result['has_contrato_usuarios'] = _table_exists(conn, 'contrato_usuarios')

    if result['has_contratos'] and result['has_contrato_usuarios']:
        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM contrato_usuarios cu
            LEFT JOIN contratos c ON c.nome = cu.contrato_nome
            WHERE c.nome IS NULL
            """
        )
        result['vinculos_orfaos'] = int(cursor.fetchone()['total'])

    conn.close()
    return result


def _repair_contratos_schema(contratos_db: str) -> None:
    conn = _connect(contratos_db)
    cursor = conn.cursor()

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS contrato_usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contrato_nome TEXT NOT NULL,
            usuario_id INTEGER NOT NULL,
            data_vinculacao TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(contrato_nome, usuario_id)
        )
        '''
    )
    cursor.execute(
        '''
        CREATE INDEX IF NOT EXISTS idx_contrato_usuarios_usuario
        ON contrato_usuarios(usuario_id)
        '''
    )
    cursor.execute(
        '''
        CREATE INDEX IF NOT EXISTS idx_contrato_usuarios_contrato
        ON contrato_usuarios(contrato_nome)
        '''
    )

    conn.commit()
    conn.close()


def _cross_checks(agenda_db: str, contratos_db: str) -> Dict:
    result = {
        'obras_contrato_orfao_count': 0,
        'obras_contrato_orfao_samples': [],
    }

    agenda_conn = _connect(agenda_db)
    contratos_conn = _connect(contratos_db)

    agenda_cursor = agenda_conn.cursor()
    contratos_cursor = contratos_conn.cursor()

    contratos_nomes = set()
    if _table_exists(contratos_conn, 'contratos'):
        contratos_cursor.execute('SELECT nome FROM contratos')
        contratos_nomes = {str(row['nome']).strip() for row in contratos_cursor.fetchall()}

    if _table_exists(agenda_conn, 'obras'):
        agenda_cursor.execute('SELECT id, nome_contrato, cliente FROM obras')
        orfaos: List[Dict] = []
        for row in agenda_cursor.fetchall():
            cliente = str(row['cliente'] or '').strip()
            if cliente and cliente not in contratos_nomes:
                orfaos.append(
                    {
                        'id': int(row['id']),
                        'nome_contrato': row['nome_contrato'],
                        'cliente': row['cliente'],
                    }
                )

        result['obras_contrato_orfao_count'] = len(orfaos)
        result['obras_contrato_orfao_samples'] = orfaos[:20]

    agenda_conn.close()
    contratos_conn.close()
    return result


def _users_checks(users_db: str) -> Dict:
    result = {
        'integrity_ok': False,
        'integrity_msg': '',
        'has_usuarios': False,
        'total_usuarios': 0,
    }

    integrity_ok, integrity_msg = _integrity_check(users_db)
    result['integrity_ok'] = integrity_ok
    result['integrity_msg'] = integrity_msg

    conn = _connect(users_db)
    cursor = conn.cursor()

    result['has_usuarios'] = _table_exists(conn, 'usuarios')
    if result['has_usuarios']:
        cursor.execute('SELECT COUNT(*) AS total FROM usuarios')
        result['total_usuarios'] = int(cursor.fetchone()['total'])

    conn.close()
    return result


def run_audit(agenda_db: str, contratos_db: str, users_db: str = '') -> Dict:
    report = {
        'paths': {
            'agenda_db': agenda_db,
            'contratos_db': contratos_db,
            'users_db': users_db,
        },
        'agenda': _agenda_checks(agenda_db),
        'contratos': _contratos_checks(contratos_db),
        'users': _users_checks(users_db) if users_db and os.path.exists(users_db) else {
            'integrity_ok': False,
            'integrity_msg': 'arquivo ausente',
            'has_usuarios': False,
            'total_usuarios': 0,
        },
        'cross': _cross_checks(agenda_db, contratos_db),
        'blockers': [],
        'warnings': [],
    }

    if not report['agenda']['integrity_ok']:
        report['blockers'].append('agendaobras.db com falha em PRAGMA integrity_check')
    if not report['contratos']['integrity_ok']:
        report['blockers'].append('contratos.db com falha em PRAGMA integrity_check')
    if users_db and os.path.exists(users_db) and not report['users']['integrity_ok']:
        report['blockers'].append('users.db com falha em PRAGMA integrity_check')
    elif not users_db or not os.path.exists(users_db):
        report['warnings'].append('users.db ausente no caminho informado; checagem de usuários foi ignorada')

    if report['agenda']['migrations_pending'] is None:
        report['blockers'].append('schema_migrations ausente no agendaobras.db')
    elif report['agenda']['migrations_pending'] > 0:
        report['blockers'].append(
            f"há {report['agenda']['migrations_pending']} migração(ões) pendente(s) no agendaobras.db"
        )

    if report['agenda']['checklist_fk_orphans'] > 0:
        report['blockers'].append('existem itens de obra_checklist sem obra correspondente')

    if report['contratos']['has_contrato_usuarios'] is False:
        report['warnings'].append('tabela contrato_usuarios ausente (schema legado)')

    if report['contratos']['vinculos_orfaos'] > 0:
        report['warnings'].append('existem vínculos de usuário para contratos inexistentes')

    if report['cross']['obras_contrato_orfao_count'] > 0:
        report['warnings'].append('existem obras com cliente sem correspondência em contratos.nome')

    if report['agenda']['invalid_dates_count'] > 0:
        report['warnings'].append('existem datas fora do formato ISO YYYY-MM-DD no agendaobras.db')

    return report


def _default_path(name: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), name)


def main() -> int:
    parser = argparse.ArgumentParser(description='Audita bancos do AgendaObras para deploy Linux.')
    parser.add_argument('--agenda-db', default=os.getenv('AGENDA_OBRAS_DB_PATH', _default_path('agendaobras.db')))
    parser.add_argument('--contratos-db', default=os.getenv('AGENDA_OBRAS_CONTRATOS_DB_PATH', _default_path('contratos.db')))
    parser.add_argument('--users-db', default=os.getenv('AGENDA_OBRAS_USERS_DB_PATH', _default_path('users.db')))
    parser.add_argument('--json-out', default='', help='Caminho para salvar relatório em JSON.')
    parser.add_argument(
        '--auto-fix-contratos-schema',
        action='store_true',
        help='Aplica correção de schema legado em contratos.db (cria contrato_usuarios e índices).',
    )
    args = parser.parse_args()

    missing = [p for p in [args.agenda_db, args.contratos_db] if not os.path.exists(p)]
    if missing:
        print('ERRO: arquivo(s) de banco não encontrado(s):')
        for path in missing:
            print(f' - {path}')
        return 2

    if args.auto_fix_contratos_schema:
        _repair_contratos_schema(args.contratos_db)

    report = run_audit(args.agenda_db, args.contratos_db, args.users_db)

    print('=== Auditoria AgendaObras (Linux readiness) ===')
    print(f"Agenda DB: {report['paths']['agenda_db']}")
    print(f"Contratos DB: {report['paths']['contratos_db']}")
    print(f"Users DB: {report['paths']['users_db']}")
    print()

    print('Resumo agendaobras.db:')
    print(f" - integrity_check: {report['agenda']['integrity_msg']}")
    print(f" - migrações aplicadas: {report['agenda']['migrations_count']} (max version: {report['agenda']['migrations_max']})")
    print(f" - migrações pendentes: {report['agenda']['migrations_pending']}")
    print(f" - datas inválidas: {report['agenda']['invalid_dates_count']}")
    print(f" - orfãos obra_checklist->obras: {report['agenda']['checklist_fk_orphans']}")
    print()

    print('Resumo contratos.db:')
    print(f" - integrity_check: {report['contratos']['integrity_msg']}")
    print(f" - tabela contratos: {report['contratos']['has_contratos']}")
    print(f" - tabela contrato_usuarios: {report['contratos']['has_contrato_usuarios']}")
    print(f" - vínculos órfãos: {report['contratos']['vinculos_orfaos']}")
    print()

    print('Resumo users.db:')
    print(f" - caminho: {report['paths']['users_db']}")
    print(f" - integrity_check: {report['users']['integrity_msg']}")
    print(f" - tabela usuarios: {report['users']['has_usuarios']}")
    print(f" - total usuários: {report['users']['total_usuarios']}")
    print()

    print('Checagens cruzadas agendaobras.db x contratos.db:')
    print(f" - obras com contrato órfão: {report['cross']['obras_contrato_orfao_count']}")
    if report['cross']['obras_contrato_orfao_samples']:
        print(' - exemplos (até 20):')
        for row in report['cross']['obras_contrato_orfao_samples']:
            print(f"   id={row['id']} | nome={row['nome_contrato']} | cliente={row['cliente']}")
    print()

    if report['warnings']:
        print('Warnings:')
        for warning in report['warnings']:
            print(f' - {warning}')
        print()

    if report['blockers']:
        print('Blockers:')
        for blocker in report['blockers']:
            print(f' - {blocker}')
        status = 2
    else:
        print('Sem blockers detectados.')
        status = 0

    if args.json_out:
        with open(args.json_out, 'w', encoding='utf-8') as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        print(f'Relatório JSON salvo em: {args.json_out}')

    return status


if __name__ == '__main__':
    raise SystemExit(main())
