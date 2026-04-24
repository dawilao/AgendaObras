"""
CLI para manutenção do catálogo de contratos (contratos.db) em produção.

Permite:
- listar contratos
- adicionar contrato
- editar (renomear) contrato
- remover contrato

Regras de segurança:
- Renomeação propaga para:
  * contratos.nome
  * contrato_usuarios.contrato_nome
  * obras.cliente (agendaobras.db)
- Remoção só é permitida sem uso em vínculos/obras,
  ou com --replace-with para migrar referências antes de excluir.

Uso (exemplos):
    python edit_contratos.py list
    python edit_contratos.py add --nome "C.E.F XYZ - 1234.2026"
    python edit_contratos.py edit --old "C.E.F XYZ - 1234.2026" --new "C.E.F XYZ - 1234.2026 (REV A)"
    python edit_contratos.py remove --nome "C.E.F XYZ - 1234.2026" --replace-with "C.E.F BAHIA - 4922.2024"
"""

import argparse
import os
import sqlite3
import sys
from dataclasses import dataclass
from typing import Optional, Tuple

from contratos_database import ContratosDatabase
from database import CAMINHO_DB
from error_logger import log_error


def _normalizar_nome(nome: str) -> str:
    return (nome or '').strip()


def _resolver_caminho_obras_db(caminho_informado: Optional[str] = None) -> str:
    """Resolve caminho do agendaobras.db com fallback local no VPS."""
    if caminho_informado:
        return caminho_informado

    pasta_caminho_padrao = os.path.dirname(CAMINHO_DB)
    if pasta_caminho_padrao and os.path.isdir(pasta_caminho_padrao):
        return CAMINHO_DB

    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'agendaobras.db')


@dataclass
class UsoContrato:
    vinculos_usuarios: int
    obras_cliente: int

    @property
    def total(self) -> int:
        return self.vinculos_usuarios + self.obras_cliente


class ContratosEditor:
    def __init__(self, contratos_db_path: Optional[str] = None, obras_db_path: Optional[str] = None):
        self.contratos_db = ContratosDatabase(db_name=contratos_db_path)
        self.obras_db_path = _resolver_caminho_obras_db(obras_db_path)

    def _conexao_obras(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.obras_db_path, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=30000')
        return conn

    def listar(self) -> int:
        contratos = self.contratos_db.listar_contratos()
        if not contratos:
            print('ℹ️ Nenhum contrato cadastrado.')
            return 0

        print('\n📋 Contratos cadastrados:')
        for indice, nome in enumerate(contratos, start=1):
            print(f'  {indice:>3}. {nome}')
        print(f'\nTotal: {len(contratos)}')
        return 0

    def _contrato_existe(self, nome: str) -> bool:
        nome = _normalizar_nome(nome)
        if not nome:
            return False
        return nome in set(self.contratos_db.listar_contratos())

    def _contar_uso_contrato(self, contrato_nome: str) -> UsoContrato:
        contrato_nome = _normalizar_nome(contrato_nome)

        conn_contratos = None
        conn_obras = None
        try:
            conn_contratos = self.contratos_db.get_connection()
            cursor_contratos = conn_contratos.cursor()
            cursor_contratos.execute(
                'SELECT COUNT(*) AS total FROM contrato_usuarios WHERE contrato_nome = ?',
                (contrato_nome,),
            )
            vinculos = int(cursor_contratos.fetchone()['total'])

            obras = 0
            if os.path.exists(self.obras_db_path):
                conn_obras = self._conexao_obras()
                cursor_obras = conn_obras.cursor()
                cursor_obras.execute(
                    'SELECT COUNT(*) AS total FROM obras WHERE cliente = ?',
                    (contrato_nome,),
                )
                obras = int(cursor_obras.fetchone()['total'])

            return UsoContrato(vinculos_usuarios=vinculos, obras_cliente=obras)
        finally:
            if conn_contratos:
                conn_contratos.close()
            if conn_obras:
                conn_obras.close()

    def adicionar(self, nome: str) -> int:
        nome = _normalizar_nome(nome)
        if not nome:
            print('❌ Nome do contrato é obrigatório.')
            return 1

        if self._contrato_existe(nome):
            print(f'⚠️ Contrato já existe: "{nome}"')
            return 1

        conn = None
        try:
            conn = self.contratos_db.get_connection()
            cursor = conn.cursor()
            cursor.execute('INSERT INTO contratos (nome) VALUES (?)', (nome,))
            conn.commit()
            print(f'✅ Contrato adicionado: "{nome}"')
            return 0
        except sqlite3.IntegrityError:
            print(f'⚠️ Contrato já existe: "{nome}"')
            return 1
        except Exception as e:
            if conn:
                conn.rollback()
            log_error(e, 'edit_contratos', f'Adicionar contrato: {nome}')
            print(f'❌ Erro ao adicionar contrato: {e}')
            return 1
        finally:
            if conn:
                conn.close()

    def editar(self, old_nome: str, new_nome: str) -> int:
        old_nome = _normalizar_nome(old_nome)
        new_nome = _normalizar_nome(new_nome)

        if not old_nome or not new_nome:
            print('❌ Informe --old e --new com valores válidos.')
            return 1

        if old_nome == new_nome:
            print('ℹ️ Nome antigo e novo são iguais. Nenhuma alteração necessária.')
            return 0

        if not self._contrato_existe(old_nome):
            print(f'❌ Contrato não encontrado: "{old_nome}"')
            return 1

        if self._contrato_existe(new_nome):
            print(f'❌ Já existe outro contrato com o nome de destino: "{new_nome}"')
            return 1

        conn_contratos = None
        conn_obras = None
        try:
            conn_contratos = self.contratos_db.get_connection()
            cursor_contratos = conn_contratos.cursor()

            cursor_contratos.execute('UPDATE contratos SET nome = ? WHERE nome = ?', (new_nome, old_nome))
            cursor_contratos.execute(
                'UPDATE contrato_usuarios SET contrato_nome = ? WHERE contrato_nome = ?',
                (new_nome, old_nome),
            )

            obras_alteradas = 0
            if os.path.exists(self.obras_db_path):
                conn_obras = self._conexao_obras()
                cursor_obras = conn_obras.cursor()
                cursor_obras.execute(
                    'UPDATE obras SET cliente = ? WHERE cliente = ?',
                    (new_nome, old_nome),
                )
                obras_alteradas = cursor_obras.rowcount

            conn_contratos.commit()
            if conn_obras:
                conn_obras.commit()

            print('✅ Contrato renomeado com sucesso:')
            print(f'   • De: "{old_nome}"')
            print(f'   • Para: "{new_nome}"')
            print(f'   • Obras atualizadas: {obras_alteradas}')
            return 0
        except sqlite3.IntegrityError as e:
            if conn_contratos:
                conn_contratos.rollback()
            if conn_obras:
                conn_obras.rollback()
            log_error(e, 'edit_contratos', f'Editar contrato (integridade): {old_nome} -> {new_nome}')
            print('❌ Falha de integridade ao renomear contrato. Verifique duplicidade de vínculos.')
            return 1
        except Exception as e:
            if conn_contratos:
                conn_contratos.rollback()
            if conn_obras:
                conn_obras.rollback()
            log_error(e, 'edit_contratos', f'Editar contrato: {old_nome} -> {new_nome}')
            print(f'❌ Erro ao editar contrato: {e}')
            return 1
        finally:
            if conn_contratos:
                conn_contratos.close()
            if conn_obras:
                conn_obras.close()

    def remover(self, nome: str, replace_with: Optional[str] = None) -> int:
        nome = _normalizar_nome(nome)
        replace_with = _normalizar_nome(replace_with) if replace_with else ''

        if not nome:
            print('❌ Nome do contrato é obrigatório para remoção.')
            return 1

        if not self._contrato_existe(nome):
            print(f'❌ Contrato não encontrado: "{nome}"')
            return 1

        if replace_with:
            if replace_with == nome:
                print('❌ --replace-with deve ser diferente do contrato removido.')
                return 1
            if not self._contrato_existe(replace_with):
                print(f'❌ Contrato de substituição não existe: "{replace_with}"')
                return 1

        uso = self._contar_uso_contrato(nome)
        tem_uso = uso.total > 0

        if tem_uso and not replace_with:
            print('❌ Não é possível remover contrato em uso sem substituição.')
            print(f'   • Vínculos de usuários: {uso.vinculos_usuarios}')
            print(f'   • Obras vinculadas: {uso.obras_cliente}')
            print('   Use --replace-with "OUTRO CONTRATO" para migrar e remover.')
            return 1

        if replace_with:
            resultado_edicao = self.editar(nome, replace_with)
            if resultado_edicao != 0:
                return resultado_edicao
            print(f'ℹ️ Remoção concluída via migração para "{replace_with}".')
            return 0

        conn = None
        try:
            conn = self.contratos_db.get_connection()
            cursor = conn.cursor()
            cursor.execute('DELETE FROM contratos WHERE nome = ?', (nome,))
            conn.commit()
            print(f'✅ Contrato removido: "{nome}"')
            return 0
        except Exception as e:
            if conn:
                conn.rollback()
            log_error(e, 'edit_contratos', f'Remover contrato: {nome}')
            print(f'❌ Erro ao remover contrato: {e}')
            return 1
        finally:
            if conn:
                conn.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Gerencia contratos em produção (add/edit/remove/list) com validações de integridade.'
    )
    parser.add_argument(
        '--contratos-db',
        default=None,
        help='Caminho customizado para contratos.db (opcional).',
    )
    parser.add_argument(
        '--obras-db',
        default=None,
        help='Caminho customizado para agendaobras.db (opcional).',
    )

    subparsers = parser.add_subparsers(dest='command', required=True)

    subparsers.add_parser('list', help='Lista contratos cadastrados.')

    parser_add = subparsers.add_parser('add', help='Adiciona novo contrato.')
    parser_add.add_argument('--nome', required=True, help='Nome do contrato.')

    parser_edit = subparsers.add_parser('edit', help='Edita (renomeia) contrato.')
    parser_edit.add_argument('--old', required=True, help='Nome atual do contrato.')
    parser_edit.add_argument('--new', required=True, help='Novo nome do contrato.')

    parser_remove = subparsers.add_parser('remove', help='Remove contrato.')
    parser_remove.add_argument('--nome', required=True, help='Nome do contrato a remover.')
    parser_remove.add_argument(
        '--replace-with',
        default=None,
        help='Nome de contrato existente para migrar referências antes de remover.',
    )

    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    editor = ContratosEditor(
        contratos_db_path=args.contratos_db,
        obras_db_path=args.obras_db,
    )

    if args.command == 'list':
        return editor.listar()

    if args.command == 'add':
        return editor.adicionar(args.nome)

    if args.command == 'edit':
        return editor.editar(args.old, args.new)

    if args.command == 'remove':
        return editor.remover(args.nome, args.replace_with)

    parser.print_help()
    return 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as e:
        log_error(e, 'edit_contratos', 'Erro fatal no script')
        print(f'❌ Erro fatal: {e}')
        raise SystemExit(1)
